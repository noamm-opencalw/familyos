#!/usr/bin/env python3
"""
FamilyOS — digest_generator.py  (שלב 5)
מייצר AI Daily Digest — סיכום יומי ל-24 שעות הקרובות.
מריץ ב-Cron כל ערב 20:00.

שימוש:
  python3 digest_generator.py              # מייצר digest רגיל
  python3 digest_generator.py --dry-run    # מדפיס ולא כותב לקובץ
  python3 digest_generator.py --notify     # שולח גם ל-Telegram
"""

import json, os, subprocess, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

DATA_JSON     = Path("/tmp/familyos/data.json")
PUSH_SH       = Path("/tmp/familyos/push.sh")
TELEGRAM_CHAT = "671957209"   # נועם

CHILD_LABEL = {"alon": "אלון", "noga": "נוגה", "ran": "רן", "itai": "איתי", "all": "כל הילדים"}
CHILD_EMOJI = {"alon": "🌹", "noga": "🌟", "ran": "💜", "itai": "💚", "all": "👨‍👧‍👦"}

HE_MONTHS = ["ינואר","פברואר","מרץ","אפריל","מאי","יוני",
              "יולי","אוגוסט","ספטמבר","אוקטובר","נובמבר","דצמבר"]
HE_DAYS   = ["ראשון","שני","שלישי","רביעי","חמישי","שישי","שבת"]


def fmt_date(dt: datetime) -> str:
    return f"{dt.day} ב{HE_MONTHS[dt.month-1]}"


def load_data() -> dict:
    if not DATA_JSON.exists():
        return {}
    with open(DATA_JSON, encoding='utf-8') as f:
        return json.load(f)


def save_data(data: dict):
    with open(DATA_JSON, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_tomorrow_window() -> tuple[datetime, datetime]:
    """מחזיר (start, end) של מחר 00:00-23:59 Asia/Hebron"""
    tz = timezone(timedelta(hours=2))
    now = datetime.now(tz)
    tmr = now + timedelta(days=1)
    start = datetime(tmr.year, tmr.month, tmr.day, 0, 0, tzinfo=tz)
    end   = datetime(tmr.year, tmr.month, tmr.day, 23, 59, tzinfo=tz)
    return start, end


def collect_context(data: dict, start: datetime, end: datetime) -> dict:
    """אוסף events + messages רלוונטיים ל-24 שעות הקרובות"""
    events   = data.get("events", [])
    messages = data.get("messages", [])

    tomorrow_events = []
    for ev in events:
        try:
            dt = datetime.fromisoformat(ev.get("date","").replace("Z","+00:00"))
            if start <= dt <= end:
                tomorrow_events.append(ev)
        except:
            pass

    # גם אירועי "כל היום" ביום מחר (date without T)
    for ev in events:
        d = ev.get("date","")
        if "T" not in d:
            try:
                parts = d.split("-")
                if (int(parts[0])==start.year and int(parts[1])==start.month
                        and int(parts[2])==start.day):
                    if ev not in tomorrow_events:
                        tomorrow_events.append(ev)
            except:
                pass

    # הודעות דחופות/חשובות שלא טופלו
    urgent_msgs = [m for m in messages
                   if m.get("priority") in ("urgent","high") and not m.get("read",False)]

    # אקדמיות — מבחנים/הגשות קרובות (actions)
    actions = data.get("actions", [])
    due_soon = []
    for a in actions:
        if a.get("done"): continue
        due = a.get("dueDate","")
        if not due: continue
        try:
            dt = datetime.fromisoformat(due.replace("Z","+00:00"))
            if dt <= end + timedelta(days=1):  # תוך 48 שעות
                due_soon.append(a)
        except:
            pass

    return {
        "tomorrow_events": tomorrow_events,
        "urgent_msgs":     urgent_msgs[:5],
        "due_soon":        due_soon[:5],
    }


def build_items_with_llm(ctx: dict, tomorrow: datetime) -> list[dict]:
    """
    מנסה לייצר items עם LLM (claude) — fallback ל-rule-based אם נכשל.
    """
    items = []

    # נסה LLM
    try:
        items = _llm_digest(ctx, tomorrow)
        if items:
            return items
    except Exception as e:
        print(f"  ⚠️ LLM failed: {e}, using rule-based fallback")

    # Fallback — rule-based
    return _rule_based_digest(ctx)


def _llm_digest(ctx: dict, tomorrow: datetime) -> list[dict]:
    """
    מייצר משימות עם Claude דרך CLI.
    """
    events_txt = "\n".join(
        f"- [{CHILD_LABEL.get(e.get('child','all'),'?')}] {e.get('title','')} @ {e.get('date','')}"
        for e in ctx["tomorrow_events"]
    ) or "אין אירועים"

    msgs_txt = "\n".join(
        f"- [{CHILD_LABEL.get(m.get('child','all'),'?')}] {(m.get('summary') or m.get('text',''))[:80]}"
        for m in ctx["urgent_msgs"]
    ) or "אין הודעות דחופות"

    actions_txt = "\n".join(
        f"- [{CHILD_LABEL.get(a.get('child','all'),'?')}] {a.get('title','')} (עד {a.get('dueDate','')})"
        for a in ctx["due_soon"]
    ) or "אין"

    tmr_label = f"יום {HE_DAYS[tomorrow.weekday()]} {fmt_date(tomorrow)}"

    prompt = f"""אתה מנהל משפחה דיגיטלי חכם. 
סכם את מה שצריך להכין למחר ({tmr_label}) ב-4-6 משימות קצרות ובעברית.
כל משימה: טקסט קצר עד 60 תווים, ילד רלוונטי (ran/itai/noga/alon/all), שעה אם ידועה.

== אירועים מחר ==
{events_txt}

== הודעות דחופות ==
{msgs_txt}

== מטלות קרובות ==
{actions_txt}

החזר JSON בלבד (ללא markdown), מערך:
[{{"text":"...","child":"ran|itai|noga|alon|all","time":"HH:MM or empty"}}]
"""

    # שימוש ב-claude CLI אם זמין
    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--output-format", "text"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            raw = result.stdout.strip()
            # חלץ JSON array
            import re
            m = re.search(r'\[[\s\S]+\]', raw)
            if m:
                arr = json.loads(m.group())
                items = []
                for i, it in enumerate(arr[:6]):
                    items.append({
                        "id": f"llm-{i}",
                        "text": str(it.get("text",""))[:80],
                        "child": it.get("child","all"),
                        "time": it.get("time",""),
                        "source": "AI",
                        "done": False,
                    })
                return items
    except FileNotFoundError:
        pass  # claude CLI לא מותקן

    # נסה openai אם זמין
    try:
        import openai
        client = openai.OpenAI()
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role":"user","content":prompt}],
            max_tokens=500,
            temperature=0.3,
        )
        raw = resp.choices[0].message.content.strip()
        import re
        m = re.search(r'\[[\s\S]+\]', raw)
        if m:
            arr = json.loads(m.group())
            return [{"id":f"llm-{i}","text":str(it.get("text",""))[:80],
                     "child":it.get("child","all"),"time":it.get("time",""),
                     "source":"AI","done":False} for i,it in enumerate(arr[:6])]
    except:
        pass

    return []


def _rule_based_digest(ctx: dict) -> list[dict]:
    """Rule-based fallback — מייצר items ישירות מהנתונים"""
    items = []
    i = 0

    for ev in ctx["tomorrow_events"]:
        child = ev.get("child","all")
        title = ev.get("title","").replace(f"[{CHILD_LABEL.get(child,'')}]","").strip()
        title = title.lstrip("📚 ").strip()
        time_str = ""
        d = ev.get("date","")
        if "T" in d:
            try:
                dt = datetime.fromisoformat(d.replace("Z","+00:00"))
                time_str = f"{dt.hour:02d}:{dt.minute:02d}"
            except:
                pass
        items.append({
            "id": f"rb-ev-{i}",
            "text": title[:70] or "אירוע",
            "child": child,
            "time": time_str,
            "source": "לוח שנה",
            "done": False,
        })
        i += 1

    for msg in ctx["urgent_msgs"]:
        text = (msg.get("summary") or msg.get("text") or "")[:70].strip()
        if not text: continue
        items.append({
            "id": f"rb-msg-{i}",
            "text": text,
            "child": msg.get("child","all"),
            "time": "",
            "source": msg.get("group",""),
            "done": False,
        })
        i += 1

    for act in ctx["due_soon"]:
        title = act.get("title","")[:70].strip()
        if not title: continue
        items.append({
            "id": f"rb-act-{i}",
            "text": title,
            "child": act.get("child","all"),
            "time": "",
            "source": "משימות",
            "done": False,
        })
        i += 1

    return items[:6]


def send_telegram_summary(items: list[dict], tomorrow: datetime):
    """שולח Telegram digest ל-נועם"""
    tmr_label = f"יום {HE_DAYS[tomorrow.weekday()]} {fmt_date(tomorrow)}"
    lines = [f"📋 *Daily Digest — {tmr_label}*", ""]

    if not items:
        lines.append("✨ אין משימות מיוחדות מחר!")
    else:
        for it in items:
            emoji = CHILD_EMOJI.get(it.get("child","all"),"•")
            time_str = f" {it['time']}" if it.get("time") else ""
            lines.append(f"{emoji} {it['text']}{time_str}")

    lines += ["", "_FamilyOS · 20:00_"]
    msg = "\n".join(lines)

    try:
        subprocess.run(
            ["openclaw", "message", "send", "--channel", "telegram",
             "--to", TELEGRAM_CHAT, "--message", msg],
            capture_output=True, timeout=10
        )
        print("  📲 Telegram notification sent")
    except Exception as e:
        print(f"  ⚠️ Telegram send failed: {e}")


def main():
    dry_run = "--dry-run" in sys.argv
    notify  = "--notify" in sys.argv

    if dry_run:
        print("🔍 DRY RUN")

    data = load_data()
    if not data:
        print("❌ data.json לא נמצא")
        sys.exit(1)

    start, end = get_tomorrow_window()
    tomorrow = start
    tmr_label = f"יום {HE_DAYS[tomorrow.weekday()]} {fmt_date(tomorrow)}"

    print(f"📋 FamilyOS Daily Digest — {tmr_label}")

    ctx = collect_context(data, start, end)
    print(f"  📅 {len(ctx['tomorrow_events'])} אירועים | "
          f"⚡ {len(ctx['urgent_msgs'])} דחופות | "
          f"📝 {len(ctx['due_soon'])} מטלות")

    items = build_items_with_llm(ctx, tomorrow)
    print(f"  ✅ {len(items)} משימות נוצרו")

    for it in items:
        emoji = CHILD_EMOJI.get(it.get("child","all"),"•")
        print(f"    {emoji} {it['text']} {it.get('time','')}")

    if not dry_run:
        data["digest"] = {
            "date": datetime.now(timezone.utc).isoformat(),
            "tomorrow": tomorrow.date().isoformat(),
            "items": items,
        }
        save_data(data)
        print(f"✅ digest נשמר ל-data.json")

        # Push לGitHub Pages
        try:
            import os as _os
            result = subprocess.run(
                ["bash", "-c",
                 "cd /tmp/familyos && git add data.json && "
                 "git diff --cached --quiet || "
                 "(git commit -m 'data: digest update' && git push origin ui-redesign)"],
                capture_output=True, text=True, timeout=30,
                env={**_os.environ}
            )
            if result.returncode == 0:
                print("  📦 Pushed to GitHub Pages")
        except Exception as e:
            print(f"  ⚠️ Push failed: {e}")

    if notify:
        send_telegram_summary(items, tomorrow)


if __name__ == "__main__":
    main()
