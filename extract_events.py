#!/usr/bin/env python3
"""
FamilyOS — extract_events.py  (שלב 4)
מחלץ אירועים מהודעות WhatsApp + מסנכרן ל-Google Calendar.
מריץ אחרי fetch_messages.py.
"""

import json, os, re, subprocess, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

DATA_JSON   = Path("/tmp/familyos/data.json")
GCAL_ACCOUNT= "noammeir@gmail.com"

# ── צבעי Google Calendar לפי ילד (Google Calendar colorId 1-11) ──────────────
CHILD_GCAL_COLOR = {
    "ran":  "9",   # Blueberry ≈ Indigo
    "itai": "2",   # Sage ≈ Emerald
    "noga": "5",   # Banana ≈ Amber
    "alon": "11",  # Tomato ≈ Rose
    "all":  "8",   # Graphite
}

CHILD_LABEL = {"alon": "אלון", "noga": "נוגה", "ran": "רן", "itai": "איתי"}

# ── Patterns לזיהוי תאריכים/שעות בהודעות ────────────────────────────────────
DATE_PATTERNS = [
    # תאריך מפורש: 15/3, 15.3, 15/03/26
    re.compile(r'\b(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?\b'),
    # יום בשבוע + שעה: "יום שני בשעה 16:00"
    re.compile(r'יום\s+(ראשון|שני|שלישי|רביעי|חמישי|שישי|שבת)'),
    # "מחר", "היום" + שעה
    re.compile(r'\b(מחר|היום|מחרתיים)\b'),
]
TIME_PATTERN  = re.compile(r'\b(\d{1,2}):(\d{2})\b')
DATE_REL_MAP  = {'היום': 0, 'מחר': 1, 'מחרתיים': 2}
DOW_MAP = {
    'ראשון': 0, 'שני': 1, 'שלישי': 2,
    'רביעי': 3, 'חמישי': 4, 'שישי': 5, 'שבת': 6,
}

# ── מילות מפתח שמעידות על אירוע ─────────────────────────────────────────────
EVENT_KEYWORDS = [
    "מבחן", "בחינה", "הגשה", "טיול", "יום ספורט", "חוג", "אירוע",
    "מסיבה", "מפגש", "הרצאה", "כנס", "ביקור", "חלוקה", "אסיפה",
    "הורים", "קבלת פנים", "סיום", "פורים", "חנוכה", "יום עצמאות",
    "אופן", "תחרות", "הופעה", "הצגה", "נסיעה", "זום", "meet", "שיעור",
    "ביה\"ס", "בית ספר", "להביא", "לחזור", "לאסוף", "לקחת",
]


def contains_event(text: str) -> bool:
    if not text:
        return False
    t = text.lower()
    return any(kw in t for kw in EVENT_KEYWORDS)


def next_weekday(ref: datetime, dow: int) -> datetime:
    """מחזיר את יום dow הקרוב (0=ראשון עברי=Sunday=6 גרגורי? — נשמור ל-ISO)"""
    # ISO: Monday=0 … Sunday=6. אבל בעברית ראשון = Sunday = 6
    # ממפה: ראשון→6, שני→0, שלישי→1, רביעי→2, חמישי→3, שישי→4, שבת→5
    HE_TO_ISO = [6, 0, 1, 2, 3, 4, 5]
    iso_dow = HE_TO_ISO[dow]
    days_ahead = (iso_dow - ref.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7  # הבא — לא היום
    return ref + timedelta(days=days_ahead)


def extract_date_time(text: str, msg_dt: datetime):
    """
    מנסה לחלץ תאריך ושעה מהטקסט.
    מחזיר (datetime | None, is_all_day: bool)
    """
    now = msg_dt or datetime.now(timezone.utc)

    # שעה — חפש קודם
    time_m = TIME_PATTERN.search(text)
    hour = int(time_m.group(1)) if time_m else None
    minute = int(time_m.group(2)) if time_m else 0

    # תאריך מפורש: DD/MM[/YY]
    date_m = re.search(r'\b(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?\b', text)
    if date_m:
        d_val = int(date_m.group(1))
        m_val = int(date_m.group(2))
        y_val = int(date_m.group(3) or now.year)
        if y_val < 100:
            y_val += 2000
        try:
            if hour is not None:
                dt = datetime(y_val, m_val, d_val, hour, minute, tzinfo=timezone(timedelta(hours=2)))
                return dt, False
            else:
                dt = datetime(y_val, m_val, d_val, 0, 0, tzinfo=timezone(timedelta(hours=2)))
                return dt, True
        except:
            pass

    # "מחר" / "היום"
    rel_m = re.search(r'\b(מחר|היום|מחרתיים)\b', text)
    if rel_m:
        delta = DATE_REL_MAP[rel_m.group(1)]
        base = now + timedelta(days=delta)
        if hour is not None:
            dt = datetime(base.year, base.month, base.day, hour, minute, tzinfo=timezone(timedelta(hours=2)))
            return dt, False
        else:
            dt = datetime(base.year, base.month, base.day, tzinfo=timezone(timedelta(hours=2)))
            return dt, True

    # "יום שני/שלישי..."
    dow_m = re.search(r'יום\s+(ראשון|שני|שלישי|רביעי|חמישי|שישי|שבת)', text)
    if dow_m:
        dow_idx = DOW_MAP[dow_m.group(1)]
        base = next_weekday(now, dow_idx)
        if hour is not None:
            dt = datetime(base.year, base.month, base.day, hour, minute, tzinfo=timezone(timedelta(hours=2)))
            return dt, False
        else:
            dt = datetime(base.year, base.month, base.day, tzinfo=timezone(timedelta(hours=2)))
            return dt, True

    return None, True


def extract_title(text: str, child: str) -> str:
    """מחלץ כותרת אירוע קצרה מהטקסט"""
    child_lbl = CHILD_LABEL.get(child, child)
    # חפש מילת מפתח ראשונה + הקשר
    for kw in EVENT_KEYWORDS:
        if kw in text:
            # חלץ משפט שמכיל את המילה
            sentences = re.split(r'[.!?\n]', text)
            for s in sentences:
                if kw in s:
                    s = s.strip()[:60].strip()
                    if len(s) > 4:
                        return f"[{child_lbl}] {s}"
    # fallback
    first_line = text.strip().split('\n')[0][:50].strip()
    return f"[{child_lbl}] {first_line}"


def push_to_gcal(ev: dict) -> str | None:
    """
    מוסיף אירוע ל-Google Calendar דרך gog.
    מחזיר gcal_id אם הצליח, None אחרת.
    """
    title = ev.get("title", "אירוע")
    date_str = ev.get("date", "")
    if not date_str:
        return None

    try:
        dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
    except:
        return None

    is_all_day = 'T' not in date_str

    # בנה פקודת gog calendar event create
    cmd = ["gog", "calendar", "event", "create",
           "--account", GCAL_ACCOUNT,
           "--title", title,
           "--json"]

    if is_all_day:
        cmd += ["--date", dt.strftime("%Y-%m-%d")]
    else:
        end_dt = dt + timedelta(hours=1)
        cmd += [
            "--start", dt.isoformat(),
            "--end", end_dt.isoformat(),
        ]

    if ev.get("location"):
        cmd += ["--location", ev["location"]]
    if ev.get("description"):
        cmd += ["--description", ev["description"]]

    color_id = CHILD_GCAL_COLOR.get(ev.get("child", "all"), "8")
    cmd += ["--color-id", color_id]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.returncode == 0:
            try:
                out = json.loads(result.stdout)
                return out.get("id") or out.get("eventId") or "pushed"
            except:
                return "pushed"
        else:
            print(f"    ⚠️ gog calendar error: {result.stderr[:100]}")
            return None
    except Exception as e:
        print(f"    ⚠️ gcal push failed: {e}")
        return None


def process_messages(data: dict) -> int:
    """
    עובר על הודעות חדשות, מחלץ אירועים, מוסיף ל-data.events.
    מחזיר מספר אירועים שנוספו.
    """
    messages = data.get("messages", [])
    existing_events = data.get("events", [])
    # IDs קיימות כדי לא לשכפל
    existing_ids = {e.get("id") for e in existing_events}
    # טקסטים שכבר עובדו (hash גס)
    processed_texts = {e.get("_src_text", "") for e in existing_events}

    new_events = []
    max_id = max((e.get("id", 0) for e in existing_events), default=1000)

    for msg in messages:
        text = msg.get("text") or msg.get("summary") or ""
        if not text or len(text) < 8:
            continue
        if not contains_event(text):
            continue
        # hash גס כדי לא לשכפל
        text_key = text[:80]
        if text_key in processed_texts:
            continue

        try:
            msg_dt = datetime.fromisoformat(msg.get("time","").replace("Z","+00:00"))
        except:
            msg_dt = datetime.now(timezone.utc)

        dt, is_all_day = extract_date_time(text, msg_dt)
        if dt is None:
            continue

        # לא להוסיף אירועים בעבר הרחוק
        if dt < datetime.now(timezone.utc) - timedelta(days=1):
            continue

        child = msg.get("child", "all")
        title = extract_title(text, child)
        max_id += 1

        ev = {
            "id": max_id,
            "child": child,
            "title": title,
            "date": dt.date().isoformat() if is_all_day else dt.isoformat(),
            "group": msg.get("group", ""),
            "source": "whatsapp",
            "color": _child_color(child),
            "gcal_id": None,
            "_src_text": text_key,
            "_from": msg.get("from", ""),
        }

        new_events.append(ev)
        processed_texts.add(text_key)
        print(f"  📌 אירוע חדש: {title} | {ev['date']}")

    return new_events


def _child_color(child: str) -> str:
    colors = {"ran": "#6366f1", "itai": "#10b981", "noga": "#f59e0b", "alon": "#f43f5e"}
    return colors.get(child, "#6B7280")


def sync_to_gcal(data: dict, new_events: list, dry_run: bool = False) -> int:
    """
    מסנכרן אירועים חדשים (ללא gcal_id) ל-Google Calendar.
    מחזיר מספר אירועים שסונכרנו.
    """
    synced = 0
    for ev in new_events:
        if ev.get("gcal_id"):
            continue
        print(f"  📅 מסנכרן: {ev['title']} ({ev['date']})")
        if dry_run:
            ev["gcal_id"] = "dry-run"
            synced += 1
            continue
        gcal_id = push_to_gcal(ev)
        if gcal_id:
            ev["gcal_id"] = gcal_id
            synced += 1
            print(f"    ✅ נוסף ל-Calendar: {gcal_id[:20]}")
        else:
            print(f"    ❌ לא הצליח לסנכרן")
    return synced


def main():
    dry_run = "--dry-run" in sys.argv
    if dry_run:
        print("🔍 DRY RUN — לא יסנכרן ל-Calendar")

    if not DATA_JSON.exists():
        print(f"❌ לא נמצא {DATA_JSON}")
        sys.exit(1)

    with open(DATA_JSON, encoding='utf-8') as f:
        data = json.load(f)

    print("📅 FamilyOS — חילוץ אירועים + Google Calendar sync")

    # שלב 1: חלץ אירועים מהודעות
    new_events = process_messages(data)
    print(f"  🔎 נמצאו {len(new_events)} אירועים חדשים")

    # שלב 2: סנכרן ל-Google Calendar
    if new_events:
        synced = sync_to_gcal(data, new_events, dry_run=dry_run)
        print(f"  ✅ סונכרנו {synced}/{len(new_events)} ל-Calendar")

        # שלב 3: הוסף ל-data.json
        data["events"] = new_events + data.get("events", [])
        data["updated_at"] = datetime.now(timezone.utc).isoformat()

        with open(DATA_JSON, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"✅ data.json עודכן עם {len(new_events)} אירועים חדשים")
    else:
        print("  ⚪ אין אירועים חדשים לסנכרן")


if __name__ == "__main__":
    main()
