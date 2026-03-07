#!/usr/bin/env python3
"""
FamilyOS — generate_data.py
שולף נתונים אמיתיים מ-Gmail + Google Calendar ומייצר data.json
"""

import json, subprocess, re, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ACCOUNT = "noammeir@gmail.com"
TELEGRAM_CHAT_ID = "671957209"
OUTPUT = "data.json"
WA_MESSAGES_FILE = Path(__file__).parent / "wa_messages.json"

# ── Helpers ────────────────────────────────────────────────────────────────────

def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.stdout.strip()

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def parse_date(s):
    """Convert gog date string → ISO"""
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            d = datetime.strptime(s.split("+")[0].split("-0")[0].rstrip("Z"), fmt.rstrip("%z"))
            return d.replace(tzinfo=timezone.utc).isoformat()
        except:
            continue
    return datetime.now(timezone.utc).isoformat()

def days_from_now(iso_str):
    try:
        d = datetime.fromisoformat(iso_str.replace("Z",""))
        return (d - datetime.now()).days
    except:
        return 0

# ── Group JID → child mapping ─────────────────────────────────────────────────
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

# ── Email sender → child ───────────────────────────────────────────────────────
def email_to_child(from_field, subject):
    f = from_field.lower()
    s = subject.lower()
    if "לביא" in f or "naale" in f or "schoolnaale" in f:
        if "שכבה ב" in s or "כיתה ב" in s: return "alon"
        if "כיתה ו" in s or "ו2" in s: return "noga"
        return "noga"  # default לביא = נוגה/אלון, prefer נוגה
    if "ort" in f or "ironi" in f and "ד" in f: return "itai"
    if "mashov" in f or "ironi" in f: return "ran"
    if "payschool" in f:
        if "לביא" in s: return "alon"
        return "all"
    return "all"

# ── Fetch Gmail messages ────────────────────────────────────────────────────────
def fetch_messages():
    print("📧 Fetching Gmail...")
    raw = run([
        "gog","gmail","messages","search",
        "from:(schoolnaale@gmail.com OR payschool.co.il OR mashov.info OR modiin.ort.org.il OR admin.ort.org.il) newer_than:14d",
        "--max","20","--account", ACCOUNT,"--plain"
    ])
    messages = []
    for i, line in enumerate(raw.splitlines()):
        if not line or line.startswith("ID"): continue
        parts = line.split("\t")
        if len(parts) < 5: continue
        msg_id, _, date_str, from_field, subject = parts[0], parts[1], parts[2], parts[3], parts[4]
        child = email_to_child(from_field, subject)
        from_name = re.sub(r'<.*?>', '', from_field).replace('"','').strip()

        # classify priority
        subj_low = subject.lower()
        priority = "normal"
        pinned = False
        if any(w in subj_low for w in ["אישור הורים","urgent","דחוף","מחר","היום"]):
            priority = "urgent"; pinned = True
        elif any(w in subj_low for w in ["חוב","תשלום","payschool","מבחן","בגרות"]):
            priority = "high"

        messages.append({
            "id": i+1,
            "from": from_name,
            "group": "מייל — " + from_name.split("(")[0].strip(),
            "child": child,
            "text": subject,
            "summary": subject,
            "time": parse_date(date_str),
            "isRinat": False,
            "pinned": pinned,
            "read": False,
            "priority": priority,
            "source": "email"
        })
    return messages

# ── Fetch Calendar events ────────────────────────────────────────────────────────
def fetch_calendar():
    print("📅 Fetching Calendar...")
    today = datetime.now().strftime("%Y-%m-%d")
    future = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")

    raw = run([
        "gog","calendar","events","primary",
        "--from", today, "--to", future,
        "--max","50","--account", ACCOUNT,"--plain"
    ])

    events = []
    custody_periods = []
    actions = []

    for i, line in enumerate(raw.splitlines()):
        if not line or line.startswith("ID"): continue
        parts = line.split("\t")
        if len(parts) < 4: continue
        _, start, end, title = parts[0], parts[1], parts[2], parts[3]

        if "ילדים" in title:
            custody_periods.append({"start": parse_date(start), "end": parse_date(end)})
            continue

        if "סוסים" in title or "כפר רות" in title:
            events.append({
                "id": i+1, "child":"alon", "title": "🐴 רכיבת סוסים — כפר רות",
                "date": parse_date(start), "group": "חוג"
            })
            continue

        # generic event
        child_guess = "all"
        tl = title.lower()
        if "רן" in title: child_guess = "ran"
        elif "איתי" in title: child_guess = "itai"
        elif "נוגה" in title: child_guess = "noga"
        elif "אלון" in title: child_guess = "alon"

        events.append({
            "id": i+1, "child": child_guess, "title": title,
            "date": parse_date(start), "group": "לוח שנה"
        })

        # אישור הורים → action
        if "אישור הורים" in title:
            actions.append({
                "id": len(actions)+1, "child": child_guess,
                "title": f"לאשר: {title}",
                "priority": "high",
                "dueDate": parse_date(start),
                "done": False, "source": "לוח שנה"
            })

    return events, custody_periods, actions

# ── Custody today ─────────────────────────────────────────────────────────────
def custody_today(periods):
    now = datetime.now(timezone.utc)
    for p in periods:
        try:
            s = datetime.fromisoformat(p["start"].replace("Z","")).replace(tzinfo=timezone.utc)
            e = datetime.fromisoformat(p["end"].replace("Z","")).replace(tzinfo=timezone.utc)
            if s <= now <= e:
                return True, p
        except:
            pass
    return False, None

# ── Fetch WhatsApp messages ────────────────────────────────────────────────────
def fetch_wa_messages():
    if not WA_MESSAGES_FILE.exists():
        return []
    try:
        msgs = json.loads(WA_MESSAGES_FILE.read_text(encoding="utf-8"))
        print(f"📱 WA: {len(msgs)} הודעות שמורות")
        return msgs
    except:
        return []

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    messages  = fetch_messages()
    wa_messages = fetch_wa_messages()
    events, custody_periods, cal_actions = fetch_calendar()

    is_custody, current_period = custody_today(custody_periods)

    # next custody
    now = datetime.now(timezone.utc)
    next_custody = None
    for p in sorted(custody_periods, key=lambda x: x["start"]):
        try:
            s = datetime.fromisoformat(p["start"].replace("Z","")).replace(tzinfo=timezone.utc)
            if s > now:
                next_custody = p
                break
        except:
            pass

    # merge email + WA, sort by time (newest first)
    all_messages = messages + wa_messages
    all_messages.sort(key=lambda m: m.get("time",""), reverse=True)

    data = {
        "updated_at": now_iso(),
        "custody": {
            "today": is_custody,
            "current": current_period,
            "next": next_custody,
            "periods": custody_periods[:8]
        },
        "messages": all_messages,
        "academics": [],
        "events": events,
        "actions": cal_actions,
    }

    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"✅ data.json נוצר — {len(messages)} מייל + {len(wa_messages)} WA = {len(all_messages)} הודעות, {len(events)} אירועים")
    return data

if __name__ == "__main__":
    main()
