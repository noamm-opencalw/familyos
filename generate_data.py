#!/usr/bin/env python3
"""
FamilyOS — generate_data.py
שולף נתונים אמיתיים מ-Gmail + Google Calendar ומייצר data.json
"""

import json, subprocess, re, sys, os
from datetime import datetime, timezone, timedelta

ACCOUNT = "noammeir@gmail.com"
OUTPUT = "data.json"

# ── Helpers ────────────────────────────────────────────────────────────────────

def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  ⚠️  stderr: {r.stderr.strip()[:200]}", file=sys.stderr)
    return r.stdout.strip()

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def parse_date_str(s):
    """Convert gog date string → ISO — handles '2026-02-25 15:59', '2026-03-09T11:00:00+02:00', '2026-03-08'"""
    if not s:
        return datetime.now(timezone.utc).isoformat()
    s = s.strip()
    # gog --plain date format: "2026-02-25 15:59" (no seconds, no tz)
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    ):
        try:
            clean = s
            # strip trailing Z then try
            if clean.endswith("Z"):
                clean = clean[:-1]
            # strip +HH:MM tz offset before strptime if no %z
            if "%z" not in fmt:
                clean = re.sub(r"[+-]\d{2}:\d{2}$", "", clean)
            d = datetime.strptime(clean, fmt)
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            return d.isoformat()
        except:
            pass
    # last resort: keep original
    return s

def parse_cal_dt(obj):
    """Parse Google Calendar start/end object {date: ...} or {dateTime: ...}"""
    if not obj:
        return None
    if "dateTime" in obj:
        return parse_date_str(obj["dateTime"])
    if "date" in obj:
        return parse_date_str(obj["date"])
    return None

# ── Child detection ──────────────────────────────────────────────────────────

def email_to_child(from_field, subject):
    f = from_field.lower()
    s = subject.lower()
    if "naale" in f or "schoolnaale" in f or "לביא" in from_field:
        if any(w in s for w in ["שכבה ב", "כיתה ב", "ב'"]):
            return "alon"
        if any(w in s for w in ["כיתה ו", "ו2", "ו'"]):
            return "noga"
        # fallback — both noga and alon
        return "noga"
    if "ort" in f or "modiin.ort" in f or "admin.ort" in f:
        return "itai"
    if "mashov" in f:
        return "ran"
    if "payschool" in f:
        if "לביא" in s:
            return "alon"
        return "all"
    return "all"

def detect_priority(subject, body=""):
    subj = subject.lower()
    text = (subject + " " + body).lower()
    if any(w in text for w in ["אישור הורים", "urgent", "דחוף", "מחר", "היום"]):
        return "urgent", True
    if any(w in text for w in ["חוב", "תשלום", "payschool", "מבחן", "בגרות", "בחינה"]):
        return "high", False
    return "normal", False

def guess_child_from_event(title):
    if "רן" in title:  return "ran"
    if "איתי" in title: return "itai"
    if "נוגה" in title: return "noga"
    if "אלון" in title: return "alon"
    return "all"

# ── Fetch Gmail messages with FULL BODY ──────────────────────────────────────

def fetch_messages():
    print("📧 Fetching Gmail message list...")
    result = run([
        "gog", "gmail", "messages", "search",
        "from:(schoolnaale@gmail.com OR payschool.co.il OR mashov.info OR modiin.ort.org.il OR admin.ort.org.il) newer_than:30d",
        "--max", "20", "--account", ACCOUNT, "--json"
    ])

    try:
        data = json.loads(result)
        msg_list = data.get("messages", [])
    except:
        print(f"  ⚠️  Failed to parse gmail list JSON", file=sys.stderr)
        msg_list = []

    messages = []
    for i, msg in enumerate(msg_list):
        msg_id  = msg.get("id", "")
        subject = msg.get("subject", "(ללא נושא)")
        from_field = msg.get("from", "")
        date_str = msg.get("date", "")

        from_name = re.sub(r'<[^>]+>', '', from_field).replace('"', '').strip()
        if not from_name:
            from_name = from_field

        child = email_to_child(from_field, subject)

        # Fetch full body
        body_text = subject  # fallback
        print(f"  📩 Fetching body for {msg_id} ({subject[:40]})")
        body_result = run([
            "gog", "gmail", "get", msg_id,
            "--account", ACCOUNT, "--json"
        ])
        try:
            body_data = json.loads(body_result)
            raw_body = body_data.get("body", "")
            if raw_body:
                body_text = raw_body.strip()
        except:
            pass

        priority, pinned = detect_priority(subject, body_text)

        messages.append({
            "id": msg_id,
            "from": from_name,
            "group": "מייל — " + from_name.split("(")[0].strip(),
            "child": child,
            "text": subject,
            "body": body_text,
            "time": parse_date_str(date_str),
            "pinned": pinned,
            "read": False,
            "priority": priority,
            "source": "email"
        })

    return messages

# ── Fetch Calendar events ─────────────────────────────────────────────────────

def fetch_calendar():
    print("📅 Fetching Calendar events...")
    today = datetime.now().strftime("%Y-%m-%d")
    future = (datetime.now() + timedelta(days=45)).strftime("%Y-%m-%d")

    result = run([
        "gog", "calendar", "events", "primary",
        "--from", today, "--to", future,
        "--max", "60", "--account", ACCOUNT, "--json"
    ])

    try:
        data = json.loads(result)
        raw_events = data.get("events", [])
    except:
        print("  ⚠️  Failed to parse calendar JSON", file=sys.stderr)
        raw_events = []

    events = []
    custody_periods = []
    actions = []

    for ev in raw_events:
        ev_id    = ev.get("id", "")
        title    = ev.get("summary", "(ללא שם)")
        desc     = ev.get("description", "") or ""
        location = ev.get("location", "") or ""
        html_link = ev.get("htmlLink", "")

        start_obj = ev.get("start", {})
        end_obj   = ev.get("end", {})
        start_dt  = parse_cal_dt(start_obj)
        end_dt    = parse_cal_dt(end_obj)

        # custody events
        if "ילדים" in title:
            custody_periods.append({
                "start": start_dt,
                "end": end_dt,
            })
            continue

        child = guess_child_from_event(title)

        # horses
        if "סוסים" in title or "כפר רות" in title:
            child = "alon"

        events.append({
            "id": ev_id,
            "calendarEventId": ev_id,
            "child": child,
            "title": title,
            "date": start_dt,
            "endDate": end_dt,
            "description": desc,
            "location": location,
            "group": "לוח שנה",
            "htmlLink": html_link,
        })

        # אישור הורים → action item
        if "אישור הורים" in title or "אישור הורים" in desc:
            actions.append({
                "id": ev_id + "_action",
                "child": child,
                "title": f"לאשר: {title}",
                "priority": "high",
                "dueDate": start_dt,
                "done": False,
                "source": "לוח שנה"
            })

    return events, custody_periods, actions

# ── Actions from emails ───────────────────────────────────────────────────────

def extract_actions_from_messages(messages):
    actions = []
    for msg in messages:
        text = (msg.get("text", "") + " " + msg.get("body", "")).lower()
        subject = msg.get("text", "")
        child = msg.get("child", "all")
        if "אישור הורים" in text:
            actions.append({
                "id": msg["id"] + "_action",
                "child": child,
                "title": f"אישור הורים: {subject[:60]}",
                "priority": "urgent",
                "dueDate": msg.get("time", now_iso()),
                "done": False,
                "source": msg.get("from", "מייל")
            })
        elif any(w in text for w in ["תשלום", "חוב", "payschool"]):
            actions.append({
                "id": msg["id"] + "_pay",
                "child": child,
                "title": f"תשלום: {subject[:60]}",
                "priority": "high",
                "dueDate": msg.get("time", now_iso()),
                "done": False,
                "source": msg.get("from", "מייל")
            })
    return actions

# ── Custody today / next ──────────────────────────────────────────────────────

def custody_today_next(periods):
    now = datetime.now(timezone.utc)
    is_today = False
    current  = None
    next_p   = None

    for p in sorted(periods, key=lambda x: x.get("start", "")):
        try:
            s = datetime.fromisoformat(p["start"])
            e = datetime.fromisoformat(p["end"])
            if s.tzinfo is None: s = s.replace(tzinfo=timezone.utc)
            if e.tzinfo is None: e = e.replace(tzinfo=timezone.utc)
            if s <= now <= e:
                is_today = True
                current  = p
            elif s > now and next_p is None:
                next_p = p
        except:
            pass

    return is_today, current, next_p

# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    messages = fetch_messages()
    events, custody_periods, cal_actions = fetch_calendar()

    # ── WhatsApp messages ──────────────────────────────────────────────────────
    wa_messages = []
    wa_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wa_messages.json")
    if os.path.exists(wa_file):
        try:
            with open(wa_file) as f:
                wa_messages = json.load(f)
            print(f"💬 Loaded {len(wa_messages)} WhatsApp messages from wa_messages.json")
        except Exception as e:
            print(f"  ⚠️  Failed to load wa_messages.json: {e}", file=sys.stderr)

    all_messages = messages + wa_messages
    # sort by time descending
    def sort_key(m):
        try:
            return m.get("time","") or ""
        except:
            return ""
    all_messages.sort(key=sort_key, reverse=True)

    email_actions = extract_actions_from_messages(messages)
    all_actions = email_actions + cal_actions

    # deduplicate actions by title
    seen_titles = set()
    deduped_actions = []
    for a in all_actions:
        if a["title"] not in seen_titles:
            seen_titles.add(a["title"])
            deduped_actions.append(a)

    is_custody, current_period, next_custody = custody_today_next(custody_periods)

    data = {
        "updated_at": now_iso(),
        "custody": {
            "today": is_custody,
            "current": current_period,
            "next": next_custody,
            "periods": custody_periods[:10]
        },
        "messages": all_messages,
        "events": events,
        "actions": deduped_actions,
    }

    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\n✅ data.json נוצר:")
    print(f"   {len(messages)} הודעות")
    print(f"   {len(events)} אירועים")
    print(f"   {len(deduped_actions)} משימות")
    print(f"   {len(custody_periods)} תקופות משמורת")
    print(f"   עודכן: {data['updated_at']}")

if __name__ == "__main__":
    main()
