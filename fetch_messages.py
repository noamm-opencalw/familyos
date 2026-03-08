#!/usr/bin/env python3
"""
FamilyOS — fetch_messages.py
שולף הודעות WhatsApp מ-sessions של OpenClaw ומוסיף ל-data.json

מופעל מ-cron או ידנית:
  cd /tmp/familyos && python3 fetch_messages.py
"""

import json, os, glob, re
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
SESSIONS_DIR = Path.home() / ".openclaw/agents/main/sessions"
DATA_JSON    = Path("/tmp/familyos/data.json")
HOURS_BACK   = 48  # כמה שעות אחורה לסרוק

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

RINAT_PHONE = "0546702373"

# ── Helpers ───────────────────────────────────────────────────────────────────
def is_junk(text):
    """סינון הודעות סתמיות"""
    if not text: return True
    text = text.strip()
    if len(text) <= 3: return True
    if re.match(r'^[\U00010000-\U0010ffff\u2600-\u27BF\s]+$', text): return True  # emoji only
    words = text.split()
    if len(words) <= 2 and text.lower() in ["תודה","בסדר","אוקיי","כן","לא","אכן","ממש","חן","👍","❤️","💪"]:
        return True
    return False

def classify_priority(text, sender_phone=""):
    if sender_phone and RINAT_PHONE in sender_phone:
        return "urgent", True
    text_low = text.lower()
    if any(w in text for w in ["מחר","היום","דחוף","חשוב","⚠️","❗","מבחן","שיעורי בית","להביא","הכנ"]):
        return "high", True
    if any(w in text for w in ["תכנון","לימוד","זום","מפגש","הגשה","תזכורת"]):
        return "normal", False
    return "normal", False

def parse_session(session_file, group_jid, cutoff_ts):
    """קורא session JSONL ומחלץ הודעות WhatsApp"""
    messages = []
    try:
        with open(session_file, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line: continue
                try:
                    d = json.loads(line)
                except: continue

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
                pdf_name = ""

                if isinstance(content, list):
                    for c in content:
                        if isinstance(c, dict):
                            t = c.get('text', '')
                            if t:
                                text_parts.append(t)
                elif isinstance(content, str):
                    text_parts.append(content)

                full_text = '\n'.join(text_parts)

                # זיהוי PDF/media
                media_match = re.search(r'\[media attached: (.+?)\s*\(application/pdf\)\]', full_text)
                if media_match:
                    pdf_path = media_match.group(1)
                    pdf_name = Path(pdf_path).stem.split('---')[0]
                    has_pdf = True

                # חלץ sender name מה-metadata JSON
                sender_match = re.search(r'"sender":\s*"([^"]+)"', full_text)
                sender = sender_match.group(1) if sender_match else "לא ידוע"
                sender_phone_match = re.search(r'"e164":\s*"([^"]+)"', full_text)
                sender_phone = sender_phone_match.group(1) if sender_phone_match else ""

                # חלץ את גוף ההודעה — הטקסט שמגיע אחרי ה-metadata blocks
                # Strategy: remove all ```json...``` blocks and [media...] then trim
                body = re.sub(r'```json[\s\S]*?```', '', full_text)
                body = re.sub(r'\[media attached:[^\]]+\]', '', body)
                body = re.sub(r'To send an image back[\s\S]*', '', body)
                body = re.sub(r'Conversation info \(untrusted metadata\):', '', body)
                body = re.sub(r'Sender \(untrusted metadata\):', '', body)
                # נקה שורות ריקות מרובות
                body = re.sub(r'\n{3,}', '\n\n', body).strip()

                if not body and not has_pdf:
                    continue

                if is_junk(body) and not has_pdf:
                    continue

                priority, pinned = classify_priority(body, sender_phone)
                is_rinat = RINAT_PHONE.lstrip('0') in sender_phone

                msg_obj = {
                    "from": sender,
                    "group": GROUP_NAME.get(group_jid, group_jid),
                    "child": GROUP_CHILD.get(group_jid, "all"),
                    "text": body if body else f"📎 {pdf_name}" if pdf_name else "[media]",
                    "summary": body[:100] if body else f"קובץ: {pdf_name}",
                    "time": ts.isoformat(),
                    "isRinat": is_rinat,
                    "pinned": pinned or is_rinat,
                    "read": False,
                    "priority": "urgent" if is_rinat else priority,
                    "source": "whatsapp",
                }
                if has_pdf:
                    msg_obj["hasAttachment"] = True
                    msg_obj["attachmentName"] = pdf_name

                messages.append(msg_obj)

    except Exception as e:
        print(f"  שגיאה ב-{session_file}: {e}")

    return messages

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("📱 FamilyOS — שליפת הודעות WhatsApp")

    cutoff = datetime.now(timezone.utc) - timedelta(hours=HOURS_BACK)
    sessions_map = {}

    # קרא sessions.json
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

    all_new_messages = []
    for jid, sid in sessions_map.items():
        session_file = SESSIONS_DIR / f"{sid}.jsonl"
        if not session_file.exists():
            continue
        msgs = parse_session(session_file, jid, cutoff)
        if msgs:
            print(f"  ✅ {GROUP_NAME.get(jid, jid)}: {len(msgs)} הודעות")
            all_new_messages.extend(msgs)
        else:
            print(f"  ⚪ {GROUP_NAME.get(jid, jid)}: אין הודעות חדשות")

    if not all_new_messages:
        print("  אין הודעות חדשות לאחרונות 48 שעות")
        return

    # קרא data.json קיים
    if DATA_JSON.exists():
        with open(DATA_JSON) as f:
            data = json.load(f)
    else:
        data = {"messages": [], "academics": [], "events": [], "actions": [], "custody": {"today": False}}

    # הסר הודעות WhatsApp ישנות (מה-48 שעות האחרונות) כדי לא לכפול
    existing = [m for m in data.get("messages", []) if m.get("source") != "whatsapp"]
    # הוסף timestamps כ-IDs
    for i, m in enumerate(all_new_messages):
        m["id"] = 1000 + i

    data["messages"] = all_new_messages + existing
    data["updated_at"] = datetime.now(timezone.utc).isoformat()

    with open(DATA_JSON, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"✅ data.json עודכן — {len(all_new_messages)} הודעות WhatsApp + {len(existing)} אחרות")

if __name__ == "__main__":
    main()
