#!/usr/bin/env python3
"""
wa_collector.py — FamilyOS WhatsApp importance filter
מסנן הודעות WA ומסווג לקטגוריות: מבחן / מטלה / אירוע / טיול / תשלום / יוה"ל / ביטול / הנחיות / לוח שעות

שימוש:
  python3 wa_collector.py --group GID --from-name NAME --text TEXT [--time ISO] [--id MSGID]
  exit 0 = נשמר  |  exit 2 = דולג (לא חשוב)
"""
import json, sys, os, re
from datetime import datetime, timezone

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT   = os.path.join(REPO_DIR, "wa_messages.json")
MAX_MSGS = 200

GROUPS = {
    "120363307180171348@g.us": {"child": "ran",  "name": "הורי כיתה יא׳7"},
    "120363151256867420@g.us": {"child": "itai", "name": "הורי כיתה ט׳3"},
    "120363166861908196@g.us": {"child": "itai", "name": "הורי ט׳3 ב"},
    "972528618633-1597665940@g.us": {"child": "noga", "name": "כיתה ו׳2"},
    "120363297963911587@g.us": {"child": "alon", "name": "שכבה ב׳ לביא"},
    "120363280306116883@g.us": {"child": "alon", "name": "כיתה ב׳ תשפ״ו"},
}

CATEGORIES = {
    "exam":         {"label": "מבחן",           "emoji": "📝", "priority": "urgent", "keywords": ["מבחן","בחינה","בגרות","הכתבה","בוחן","מבדק","בחינות","ציון","ציונים","השלמה","הגשה","מחצית","קיץ"]},
    "task":         {"label": "מטלה",           "emoji": "✅", "priority": "high",   "keywords": ["לאשר","אישור","טופס","להגיש","הגשה","נא למלא","נא להביא","יש להביא","חובה","נדרש","בבקשה להגיב","נא לאשר","לחתום","חתימה"]},
    "event":        {"label": "אירוע",          "emoji": "📅", "priority": "high",   "keywords": ["אירוע","מפגש","אסיפה","ישיבה","כנס","הופעה","מסיבה","חגיגה","טקס","פגישה","ביקור","פעילות","יום כיף","יום ספורט","יום שדה","יציאה"]},
    "trip":         {"label": "טיול",           "emoji": "🚌", "priority": "high",   "keywords": ["טיול","עלייה לרגל","סיור","אוטובוס","יציאה לטיול","לינת שדה","מסע","מחנה"]},
    "payment":      {"label": "תשלום",          "emoji": "💳", "priority": "high",   "keywords": ["תשלום","לשלם","חיוב","חשבון","קופה","גבייה","payschool","אגרה","דמי","להעביר כסף","העברה","יתרת חוב","יתרת זכות"]},
    "birthday":     {"label": "יום הולדת",     "emoji": "🎂", "priority": "normal", "keywords": ["יום הולדת","יומולדת","מזל טוב","בר מצווה","בת מצווה","יובל"]},
    "cancellation": {"label": "ביטול / שינוי", "emoji": "🚫", "priority": "urgent", "keywords": ["ביטול","מבוטל","לא מתקיים","נדחה","שינוי","הקפאה","אין לימודים","חופש","יום חופשי","בוטל"]},
    "schedule":     {"label": "לוח שעות",      "emoji": "🕐", "priority": "normal", "keywords": ["שינוי שעות","לוח שעות","שיעור פרטי","שיעור חופשי","קיצור יום","יום קצר","יוצאים מוקדם","שעות לימוד"]},
    "notice":       {"label": "הנחיות",         "emoji": "📢", "priority": "normal", "keywords": ["חוזר","הנחיות","עדכון","הודעה חשובה","לידיעתכם","לתשומת לב","נא לשים לב","שימו לב","הורים יקרים","תזכורת","זכרו"]},
}

SKIP_PATTERNS = [
    r"^[\U0001F300-\U0001FAFF\s!.,❤️👍🙏😊✅👏🎉💪🌟😍🥰😘🤗👌🙌♥️🫶💕💞]+$",
    r"^(תודה|תודה רבה|בסדר|אוקיי|אוקי|כן|לא|בטח|ממש|נהדר|מעולה|יפה|חמוד|נחמד|מסכים|ברור|ודאי|אמן|שיהיה|יהיה טוב|בהצלחה|תצליחו|רב תודות|טוב|סבבה)[\s!.]*$",
    r"^[!?.\s]+$",
    r"^\s*$",
]
SKIP_SENDERS = {"", "status@broadcast", "system"}
MIN_WORDS = 5

def classify(text):
    t = text.strip()
    if not t or len(t.split()) < MIN_WORDS:
        return None, "too_short"
    for pat in SKIP_PATTERNS:
        if re.match(pat, t, re.UNICODE):
            return None, "ack_or_emoji"
    for cat_key, cat in CATEGORIES.items():
        for kw in cat["keywords"]:
            if kw.lower() in t.lower():
                return cat_key, kw
    # הודעה ארוכה ללא קטגוריה → הנחיות כללי
    clean = re.sub(r'[\U0001F300-\U0001FAFF]+', '', t).strip()
    if len(clean.split()) >= 15:
        return "notice", "long_message"
    return None, "no_category"

def load():
    try:
        with open(OUTPUT) as f: return json.load(f)
    except: return []

def save(msgs):
    with open(OUTPUT, "w") as f:
        json.dump(msgs[-MAX_MSGS:], f, ensure_ascii=False, indent=2)

def process(group_id, sender, text, timestamp=None, msg_id=None):
    if sender.strip().lower() in SKIP_SENDERS:
        print(f"⏭️  SKIP [skip_sender]: {sender}"); return False
    cat_key, reason = classify(text)
    if cat_key is None:
        print(f"⏭️  SKIP [{reason}]: {sender}: {text[:60]}"); return False
    cat = CATEGORIES[cat_key]
    g   = GROUPS.get(group_id, {})
    ts  = timestamp or datetime.now(timezone.utc).isoformat()
    uid = msg_id or f"wa_{group_id}_{ts}"
    msg = {
        "id": uid, "source": "whatsapp",
        "child": g.get("child","all"), "group": g.get("name", group_id),
        "from": sender, "text": text, "body": text, "time": ts,
        "pinned": cat["priority"] == "urgent", "read": False,
        "priority": cat["priority"],
        "category": cat_key, "category_label": cat["label"], "category_emoji": cat["emoji"],
        "wa_reason": reason,
    }
    msgs = load()
    if uid in {m.get("id") for m in msgs}:
        print(f"⏭️  DUP: {uid}"); return False
    msgs.append(msg); save(msgs)
    print(f"✅ SAVED [{cat['emoji']} {cat['label']}|{cat['priority']}] [{g.get('child')}] {sender}: {text[:60]}")
    return True

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--group",     required=True)
    parser.add_argument("--from-name", required=True, dest="sender")
    parser.add_argument("--text",      required=True)
    parser.add_argument("--time",      default=None)
    parser.add_argument("--id",        default=None)
    parser.add_argument("--test",      action="store_true")
    args = parser.parse_args()

    if args.test:
        cases = [
            ("120363307180171348@g.us","מחנכת","👍",False),
            ("120363307180171348@g.us","מחנכת","תזכורת: מחר יש מבחן בחשבון לכל הכיתה. נא להכין חומר עזר",True),
            ("120363280306116883@g.us","ועד הורים","ביטול: הטיול לגן חיות ביום חמישי מבוטל עקב מזג האוויר",True),
            ("120363151256867420@g.us","מזכירות","אישור הורים לטיול ט׳3 נדרש עד יום ראשון בשעה 20:00",True),
            ("972528618633-1597665940@g.us","מחנכת","יום הולדת שמח לנוגה! 🎂🎉",True),
            ("120363297963911587@g.us","הורה","כן",False),
        ]
        ok = True
        for gid, sender, text, expected in cases:
            cat, reason = classify(text)
            got = cat is not None
            mark = "✅" if got == expected else "❌"
            label = CATEGORIES[cat]["label"] if cat else f"SKIP:{reason}"
            print(f"{mark} [{label}] {text[:55]}")
            if got != expected: ok = False
        print(f"\n{'✅ All passed' if ok else '❌ Some failed'}")
        sys.exit(0 if ok else 1)

    saved = process(args.group, args.sender, args.text, args.time, args.id)
    sys.exit(0 if saved else 2)
