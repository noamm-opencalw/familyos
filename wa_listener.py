#!/usr/bin/env python3
"""
wa_listener.py — FamilyOS WhatsApp message collector
מופעל ע"י OpenClaw webhook או ידנית לצורך בדיקה.
כותב ל-wa_messages.json בתיקיית הריפו.

שימוש:
  python3 wa_listener.py --add '{"group":"...","from":"...","text":"...","child":"..."}'
  python3 wa_listener.py --test   # מוסיף הודעות דוגמה
"""

import json, sys, os, argparse
from datetime import datetime, timezone

GROUPS = {
    "120363307180171348@g.us": {"child": "ran",  "name": "הורי כיתה יא׳7"},
    "120363151256867420@g.us": {"child": "itai", "name": "הורי כיתה ט׳3"},
    "120363166861908196@g.us": {"child": "itai", "name": "הורי ט׳3"},
    "972528618633-1597665940@g.us": {"child": "noga", "name": "כיתה ו׳2"},
    "120363297963911587@g.us": {"child": "alon", "name": "שכבה ב׳ לביא"},
    "120363280306116883@g.us": {"child": "alon", "name": "כיתה ב׳ תשפ״ו"},
}

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT   = os.path.join(REPO_DIR, "wa_messages.json")
MAX_MSGS = 100  # keep last N messages

def load():
    try:
        with open(OUTPUT) as f:
            return json.load(f)
    except:
        return []

def save(msgs):
    with open(OUTPUT, "w") as f:
        json.dump(msgs[-MAX_MSGS:], f, ensure_ascii=False, indent=2)

def add_message(msg: dict):
    msgs = load()
    # deduplicate by id
    existing_ids = {m.get("id") for m in msgs}
    if msg.get("id") in existing_ids:
        return
    msgs.append(msg)
    save(msgs)
    print(f"✅ Added: [{msg.get('child')}] {msg.get('from','')}: {msg.get('text','')[:60]}")

def make_msg(group_id, sender, text, timestamp=None, msg_id=None):
    g = GROUPS.get(group_id, {})
    ts = timestamp or datetime.now(timezone.utc).isoformat()
    uid = msg_id or f"wa_{group_id}_{int(datetime.now().timestamp()*1000)}"
    return {
        "id": uid,
        "source": "whatsapp",
        "child": g.get("child", "all"),
        "group": g.get("name", group_id),
        "from": sender,
        "text": text,
        "body": text,
        "time": ts,
        "pinned": False,
        "read": False,
        "priority": detect_priority(text),
    }

def detect_priority(text):
    urgent = ["דחוף", "מחר", "היום", "אישור נדרש", "URGENT", "חשוב מאוד"]
    high   = ["אישור", "חשוב", "בבקשה להגיב", "נא לאשר", "תשלום"]
    t = text.lower()
    if any(k in text for k in urgent): return "urgent"
    if any(k in text for k in high):   return "high"
    return "normal"

def test_messages():
    """Add sample messages for testing"""
    samples = [
        ("120363307180171348@g.us", "מחנכת יא7", "שלום הורים, בשבוע הבא יתקיים מפגש הורים ומורים ביום שלישי בשעה 19:00. נא לאשר הגעה."),
        ("120363280306116883@g.us", "מחנכת ב׳", "חוזר דחוף: מחר יש יום ספורט לכיתה ב׳. יש להביא בגדי ספורט ונעליים מתאימות."),
        ("972528618633-1597665940@g.us", "ועד הורים ו2", "ילדים יקרים, השבוע נלמד על פורים. נשמח אם כל ילד יביא תחפושת ביום חמישי."),
        ("120363151256867420@g.us", "מזכירות בית הספר", "תזכורת: הגשת טופס אישור הורים לטיול ט׳3 עד יום ראשון."),
    ]
    for gid, sender, text in samples:
        add_message(make_msg(gid, sender, text))
    print(f"✅ Added {len(samples)} test messages to {OUTPUT}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--add", help="JSON string of message to add")
    parser.add_argument("--test", action="store_true", help="Add test messages")
    parser.add_argument("--list", action="store_true", help="List current messages")
    args = parser.parse_args()

    if args.test:
        test_messages()
    elif args.add:
        msg = json.loads(args.add)
        add_message(msg)
    elif args.list:
        msgs = load()
        print(f"Total: {len(msgs)} messages")
        for m in msgs:
            print(f"  [{m.get('child')}] {m.get('from','')}: {m.get('text','')[:60]}")
    else:
        parser.print_help()
