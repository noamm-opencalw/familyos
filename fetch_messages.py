#!/usr/bin/env python3
"""
FamilyOS — fetch_messages.py v2
שולף הודעות WhatsApp מ-sessions של OpenClaw.
כשיש PDF מצורף — קורא אותו, מסכם, ומזין אירועים ללוח שנה.
"""

import json, os, re, subprocess, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
SESSIONS_DIR  = Path.home() / ".openclaw/agents/main/sessions"
MEDIA_DIR     = Path.home() / ".openclaw/media/inbound"
DATA_JSON     = Path("/tmp/familyos/data.json")
HOURS_BACK    = 168  # 7 ימים אחורה לסרוק

# ── Group → child/name mapping ────────────────────────────────────────────────
GROUP_CHILD = {
    "120363297963911587@g.us": "alon",
    "120363280306116883@g.us": "alon",
    "972528618633-1597665940@g.us": "noga",
    "120363307180171348@g.us": "ran",
    "120363151256867420@g.us": "itai",
    "120363166861908196@g.us": "itai",
}
GROUP_NAME = {
    "120363297963911587@g.us": "שכבה ב׳ לביא",
    "120363280306116883@g.us": "כיתה ב׳ לביא",
    "972528618633-1597665940@g.us": "כיתה ו׳2",
    "120363307180171348@g.us": "הורי יא׳7",
    "120363151256867420@g.us": "הורי ט׳3",
    "120363166861908196@g.us": "הורי ט׳3",
}

# ילד → שם קצר לאירועים
CHILD_LABEL = {"alon": "אלון", "noga": "נוגה", "ran": "רן", "itai": "איתי"}

RINAT_PHONE = "0546702373"

# ── PDF extraction ─────────────────────────────────────────────────────────────
def extract_pdf_text(pdf_path: str) -> str:
    """חלץ טקסט מ-PDF באמצעות pdftotext"""
    try:
        result = subprocess.run(
            ["pdftotext", "-layout", pdf_path, "-"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except FileNotFoundError:
        pass
    # fallback: strings
    try:
        result = subprocess.run(["strings", pdf_path], capture_output=True, text=True, timeout=5)
        return result.stdout.strip()
    except:
        pass
    return ""


def parse_schedule_from_text(text: str, child: str, msg_date: datetime) -> dict:
    """
    מנתח טקסט של מערכת שעות → מחזיר:
      summary: str         — סיכום הוdash
      events:  list[dict]  — אירועים ללוח שנה
      actions: list[dict]  — פעולות נדרשות
    """
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    summary_parts = []
    events = []
    actions = []

    # זיהוי תאריך — חפש תאריך מפורש ב-PDF
    date_match = re.search(r'(\d{1,2})[./](\d{1,2})[./](\d{2,4})', text)
    event_date = msg_date
    if date_match:
        d_val = int(date_match.group(1))
        m_val = int(date_match.group(2))
        y_val = int(date_match.group(3))
        if y_val < 100: y_val += 2000
        try:
            event_date = datetime(y_val, m_val, d_val, tzinfo=timezone.utc)
        except:
            pass
    else:
        # אם אין תאריך מפורש — ה-PDF הוא כנראה ל"מחר" ביחס לשליחת ההודעה
        event_date = msg_date + timedelta(days=1)
        # אם msg_date הוא שבת (5) → קדמה ביום (יום ראשון)
        if event_date.weekday() == 6:  # Sunday
            pass  # טוב
        elif event_date.weekday() == 5:  # Saturday
            event_date = msg_date + timedelta(days=2)

    date_str = event_date.strftime("%Y-%m-%d")
    child_label = CHILD_LABEL.get(child, child)

    # ── זיהוי שעות ופעילויות (גישה לפי blocks) ──
    # הגדרת activity patterns ידועים
    ACTIVITY_MAP = [
        (r'זום\s+רגשי\s*1',           "זום רגשי — קבוצה 1"),
        (r'זום\s+רגשי\s*2',           "זום רגשי — קבוצה 2"),
        (r'זום\s+רגשי',               "זום רגשי"),
        (r'זום\s+לימוד',              "זום לימודי"),
        (r'זום\s+עם\s+(\w+)',         None),   # "זום עם אביטל" -> dynamic
        (r'זום',                       "מפגש זום"),
        (r'סקר\s+בוקר',              "סקר בוקר טוב"),
        (r'שיעור\s+(\w+)',             None),   # "שיעור עברית" -> dynamic
        (r'משימה\s+מתוקשבת',         "משימה מתוקשבת"),
        (r'משימה\s+ב(\w+)',            None),   # "משימה בעברית" -> dynamic
    ]

    time_range_re = re.compile(r'(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})')
    time_any_re   = re.compile(r'\b(\d{1,2}:\d{2})\b')

    # מצא כל הזכרת שעה
    time_matches = list(time_any_re.finditer(text))
    seen_times = set()

    for tm in time_matches:
        start_time = tm.group(1)
        if start_time in seen_times:
            continue

        # בדוק טווח
        range_m = time_range_re.search(text[max(0, tm.start()-1):tm.end()+8])
        end_time = range_m.group(2) if range_m else ""

        # חפש פעילות ב-window של ±150 תווים
        w_start = max(0, tm.start() - 150)
        w_end   = min(len(text), tm.end() + 150)
        window  = text[w_start:w_end]

        desc = ""
        for pattern, label in ACTIVITY_MAP:
            m = re.search(pattern, window, re.IGNORECASE)
            if m:
                if label is None:
                    # dynamic — חלץ את הקבוצה הראשונה
                    desc = m.group(0).strip()
                    # נקה את הפורמט
                    desc = re.sub(r'\s+', ' ', desc).strip()
                else:
                    desc = label
                break

        if not desc:
            continue

        seen_times.add(start_time)
        time_label = f"{start_time}–{end_time}" if end_time else start_time
        summary_parts.append(f"• {time_label} — {desc}")
        events.append({
            "id": len(events) + 500,
            "child": child,
            "title": f"📚 [{child_label}] {desc[:40]}",
            "date": f"{date_str}T{start_time}:00+02:00",
            "group": "לוח שנה",
            "source": "whatsapp-pdf"
        })

    # זיהוי "להביא" / ציוד
    needs = re.findall(r'(?:יש להביא|להכין|נדרש)[^\n.]+', text)
    for n in needs:
        n = n.strip()
        if len(n) > 5:
            actions.append({
                "id": len(actions) + 200,
                "child": child,
                "title": f"⚠️ {child_label}: {n[:60]}",
                "priority": "high",
                "dueDate": f"{date_str}T07:00:00+02:00",
                "done": False,
                "source": "whatsapp-pdf"
            })
            summary_parts.append(f"⚠️ {n[:60]}")

    # סיכום
    if not summary_parts:
        # fallback — שלוש שורות ראשונות עם תוכן
        content_lines = [l for l in lines if len(l) > 8][:4]
        summary_parts = content_lines

    summary = "\n".join(summary_parts[:8])
    return {"summary": summary, "events": events, "actions": actions}


# ── Helpers ───────────────────────────────────────────────────────────────────
def is_junk(text):
    if not text: return True
    text = text.strip()
    if len(text) <= 3: return True
    if re.match(r'^[\U00010000-\U0010ffff\u2600-\u27BF\s]+$', text): return True
    return False


def classify_priority(text, sender_phone=""):
    if sender_phone and RINAT_PHONE.lstrip('0') in sender_phone:
        return "urgent", True
    if any(w in text for w in ["מחר","היום","דחוף","חשוב","⚠️","❗","מבחן","להביא","הכנ"]):
        return "high", True
    if any(w in text for w in ["תכנון","לימוד","זום","מפגש","הגשה","תזכורת"]):
        return "normal", False
    return "normal", False


def find_pdf_path(stem_name: str) -> str | None:
    """מחפש PDF לפי stem name ב-media/inbound"""
    pattern = f"{MEDIA_DIR}/{stem_name}---*.pdf"
    matches = list(Path(MEDIA_DIR).glob(f"{stem_name}---*.pdf"))
    if not matches:
        # נסה חיפוש חלקי
        for f in MEDIA_DIR.glob("*.pdf"):
            if stem_name.replace("_", " ") in f.stem or stem_name in f.stem:
                return str(f)
    return str(matches[0]) if matches else None


# ── Session parser ─────────────────────────────────────────────────────────────
def parse_session(session_file, group_jid, cutoff_ts):
    """קורא session JSONL → (messages, events, actions)"""
    messages = []
    all_events = []
    all_actions = []

    try:
        entries = []
        with open(session_file, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line: continue
                try:
                    entries.append(json.loads(line))
                except:
                    pass

        # עבור על entries — זיהוי הודעות ו-PDF
        i = 0
        while i < len(entries):
            d = entries[i]
            i += 1

            if d.get('type') != 'message': continue
            msg = d.get('message', {})
            if msg.get('role') != 'user': continue

            ts_str = d.get('timestamp', '')
            try:
                ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
            except:
                continue

            if ts < cutoff_ts: continue

            # חלץ תוכן
            content = msg.get('content', '')
            text_parts = []
            has_pdf = False
            pdf_stem = ""
            pdf_full_path = None

            if isinstance(content, list):
                for c in content:
                    if isinstance(c, dict):
                        text_parts.append(c.get('text', ''))
            elif isinstance(content, str):
                text_parts.append(content)

            full_text = '\n'.join(text_parts)

            # זיהוי PDF
            media_match = re.search(r'\[media attached: (.+?)\s*\(application/pdf\)\]', full_text)
            if media_match:
                pdf_full_path = media_match.group(1).strip()
                pdf_stem = Path(pdf_full_path).stem.split('---')[0]
                has_pdf = True

            # חלץ sender
            sender_match = re.search(r'"sender":\s*"([^"]+)"', full_text)
            sender = sender_match.group(1) if sender_match else "לא ידוע"
            sender_phone_match = re.search(r'"e164":\s*"([^"]+)"', full_text)
            sender_phone = sender_phone_match.group(1) if sender_phone_match else ""

            # נקה body
            body = re.sub(r'```json[\s\S]*?```', '', full_text)
            body = re.sub(r'\[media attached:[^\]]+\]', '', body)
            body = re.sub(r'To send an image back[\s\S]*', '', body)
            body = re.sub(r'Conversation info \(untrusted metadata\):', '', body)
            body = re.sub(r'Sender \(untrusted metadata\):', '', body)
            body = re.sub(r'\n{3,}', '\n\n', body).strip()

            if not body and not has_pdf:
                continue
            if is_junk(body) and not has_pdf:
                continue

            child = GROUP_CHILD.get(group_jid, "all")
            priority, pinned = classify_priority(body, sender_phone)
            is_rinat = RINAT_PHONE.lstrip('0') in sender_phone

            # ── PDF processing ──
            pdf_summary = ""
            pdf_events = []
            pdf_actions = []

            if has_pdf:
                # נסה למצוא את הקובץ
                actual_path = pdf_full_path if os.path.exists(pdf_full_path) else find_pdf_path(pdf_stem)
                if actual_path and os.path.exists(actual_path):
                    pdf_text = extract_pdf_text(actual_path)
                    if pdf_text:
                        parsed = parse_schedule_from_text(pdf_text, child, ts)
                        pdf_summary = parsed["summary"]
                        pdf_events = parsed["events"]
                        pdf_actions = parsed["actions"]
                        all_events.extend(pdf_events)
                        all_actions.extend(pdf_actions)
                        print(f"    📄 {pdf_stem}: {len(pdf_events)} אירועים, {len(pdf_actions)} פעולות")

            # בנה text מלא להצגה
            if body and pdf_summary:
                display_text = f"{body}\n\n📋 מהמסמך:\n{pdf_summary}"
            elif pdf_summary:
                display_text = f"📎 {pdf_stem}\n\n{pdf_summary}"
            elif body:
                display_text = body
            else:
                display_text = f"📎 {pdf_stem}"

            msg_obj = {
                "from": sender,
                "group": GROUP_NAME.get(group_jid, group_jid),
                "child": child,
                "text": display_text,
                "summary": (pdf_summary[:120] if pdf_summary else body[:120]) or f"קובץ: {pdf_stem}",
                "time": ts.isoformat(),
                "isRinat": is_rinat,
                "pinned": pinned or is_rinat or bool(pdf_events),
                "read": False,
                "priority": "urgent" if is_rinat else ("high" if pdf_events else priority),
                "source": "whatsapp",
            }
            if has_pdf:
                msg_obj["hasAttachment"] = True
                msg_obj["attachmentName"] = pdf_stem

            messages.append(msg_obj)

    except Exception as e:
        print(f"  שגיאה ב-{session_file}: {e}")
        import traceback; traceback.print_exc()

    return messages, all_events, all_actions


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("📱 FamilyOS — שליפת הודעות WhatsApp + PDFs")

    cutoff = datetime.now(timezone.utc) - timedelta(hours=HOURS_BACK)
    sessions_map = {}

    sessions_json = SESSIONS_DIR / "sessions.json"
    if sessions_json.exists():
        with open(sessions_json) as f:
            sessions = json.load(f)
        for key, val in sessions.items():
            if "whatsapp:group:" in key:
                jid = key.split("whatsapp:group:")[-1]
                if jid in GROUP_CHILD:
                    sid = val.get("sessionId") if isinstance(val, dict) else None
                    if sid:
                        sessions_map[jid] = sid

    print(f"  מצאתי {len(sessions_map)} קבוצות מוניטור")

    all_messages = []
    all_events = []
    all_actions = []

    for jid, sid in sessions_map.items():
        session_file = SESSIONS_DIR / f"{sid}.jsonl"
        if not session_file.exists():
            continue
        msgs, evts, acts = parse_session(session_file, jid, cutoff)
        if msgs:
            print(f"  ✅ {GROUP_NAME.get(jid, jid)}: {len(msgs)} הודעות")
            all_messages.extend(msgs)
        else:
            print(f"  ⚪ {GROUP_NAME.get(jid, jid)}: אין הודעות")
        all_events.extend(evts)
        all_actions.extend(acts)

    # קרא data.json קיים
    if DATA_JSON.exists():
        with open(DATA_JSON) as f:
            data = json.load(f)
    else:
        data = {"messages": [], "academics": [], "events": [], "actions": [], "custody": {"today": False}}

    # הסר WhatsApp ישן
    existing_msgs    = [m for m in data.get("messages", []) if m.get("source") != "whatsapp"]
    existing_events  = [e for e in data.get("events", []) if e.get("source") != "whatsapp-pdf"]
    existing_actions = [a for a in data.get("actions", []) if a.get("source") != "whatsapp-pdf"]

    for i, m in enumerate(all_messages):
        m["id"] = 1000 + i

    combined = all_messages + existing_msgs
    combined.sort(key=lambda m: m.get("time", ""), reverse=False)  # ישן → חדש
    data["messages"] = combined
    data["events"]   = all_events + existing_events
    data["actions"]  = all_actions + existing_actions
    data["updated_at"] = datetime.now(timezone.utc).isoformat()

    with open(DATA_JSON, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"✅ data.json עודכן — {len(all_messages)} הודעות | {len(all_events)} אירועים חדשים | {len(all_actions)} פעולות")

if __name__ == "__main__":
    main()
