# FamilyOS — Roadmap & Action Plan
_Branch: `ui-redesign` | Updated: 2026-03-11_

---

## עקרונות ביצוע
- **Frontend-first**: כל פיצ'ר מתחיל בממשק, ורק אז מחבר ל-backend
- **Data contract**: כל שינוי ב-`data.json` מתועד לפני קידוד
- **Progressive**: כל שלב עובד עצמאית — אפשר לעצור ולשחרר בכל נקודה
- **No regressions**: כל שלב נבדק מול ה-main לפני merge

---

## שלב 0 — תשתית (מקדים הכל) ✅ חלקי
> _מה שיש: ענף `ui-redesign`, quick-add overlay, FAB_

- [ ] **0.1** תיקון באגים קיימים ב-overlay (focus-trap, scroll-lock)
- [ ] **0.2** הגדרת `data.json` schema מלא עם שדות חדשים:
  ```json
  { "category": "school|sport|payment|medical|other",
    "categoryIcon": "🎒",
    "summary_points": ["..."],
    "drive_link": "...",
    "conflict": false }
  ```
- [ ] **0.3** Service Worker בסיסי (cache-first לנכסים סטטיים) + `manifest.json` → PWA
- [ ] **0.4** Merge קטן ל-main לאחר אישור

---

## שלב 1 — Smart Expandable Cards (פיצ'ר 1)
> _השפעה גבוהה, סיכון נמוך — pure frontend_

**מה עושים:**
- CSS: `line-clamp: 3` על `.msg-text` + transition חלקה ל-expand
- JS: toggle class `expanded` על לחיצת "קרא עוד" — אין fetch, אין state חיצוני
- כפתור: טקסט דינמי "קרא עוד ▾" / "סגור ▴" + אנימציית גובה

**שינויים ב-data.json:** אין

**תנאי סיום:** כרטיסייה עם טקסט >3 שורות מציגה clamp + expand מלא

---

## שלב 2 — AI Categorization (פיצ'ר 2)
> _שינוי ב-backend (push script) + ממשק קל_

**Backend (`fetch_messages.py` / `push.sh`):**
- הוספת פונקציה `classify_message(text) → category` עם LLM קצר (prompt פשוט)
- מיפוי: `school🎒`, `sport⚽`, `payment💳`, `medical🩺`, `trip🚌`, `other📌`
- כתיבת `category` + `categoryIcon` לכל הודעה ב-`data.json`

**Frontend:**
- Badge צבעוני על כל כרטיסייה (פינה שמאלית עליונה)
- הוספת filter chips של קטגוריות (לצד פילטר הילדים)

**שינויים ב-data.json:** `messages[].category`, `messages[].categoryIcon`

**תנאי סיום:** הודעה חדשה מ-WhatsApp מקבלת category אוטומטית ומוצגת עם badge

---

## שלב 3 — Drive Integration & Doc Extraction (פיצ'ר 3)
> _אינטגרציה עם Google Drive + LLM summarization_

**Backend:**
- זיהוי הודעות עם קבצים מצורפים (WhatsApp media)
- העלאה ל-Drive דרך `gog drive upload` + שמירת link
- OCR / text extraction → LLM → 2-3 bullet points
- שמירה: `messages[].drive_link`, `messages[].summary_points[]`

**Frontend:**
- כרטיסיית "מסמך" ייחודית: bullets summary + כפתור "📄 פתח מקור"
- skeleton loader בזמן עיבוד

**שינויים ב-data.json:** `messages[].drive_link`, `messages[].summary_points`

**תנאי סיום:** מסמך PDF שנשלח בקבוצה מופיע בפיד עם bullets + קישור Drive

---

## שלב 4 — Smart Family Timeline (פיצ'ר 4)
> _שדרוג לוח השנה הקיים + Google Calendar sync_

**Frontend (Timeline view):**
- החלפת grid חודשי ב-Agenda view אנכי (כמו Google Calendar mobile)
- צבעי ילדים: רן=Indigo, איתי=Emerald, נוגה=Purple, אלון=Amber
- כרטיסיית אירוע: שם + שעה + ילד + מקור (WhatsApp/ידני)

**Backend:**
- פונקציית `extract_events(text) → [{title, date, time, child}]` עם LLM
- Google Calendar API (דרך `gog`) → push event אוטומטי
- sync דו-כיווני: אירועים שנוספו ב-quick-add → Calendar

**שינויים ב-data.json:** `events[].source`, `events[].gcal_id`, `events[].color`

**תנאי סיום:** הודעה "מחר חוג בשעה 16:00" → אירוע מופיע ב-Timeline וב-Google Calendar

---

## שלב 5 — AI Daily Digest (פיצ'ר 5)
> _Cron + LLM + טאב חדש בממשק_

**Backend (Cron — כל ערב 20:00):**
- איסוף כל אירועים + הודעות ל-24 שעות הקרובות
- LLM prompt → 4-5 משימות קריטיות בעברית
- כתיבה ל-`data.json`: `digest: { date, items: [{text, child, done: false}] }`

**Frontend:**
- טאב חדש "מחר" עם Bento Box layout
- כל משימה: checkbox + טקסט + dot צבע ילד
- `done` נשמר ב-localStorage (לא צריך server round-trip)

**שינויים ב-data.json:** `digest: { date, items[] }`

**תנאי סיום:** ב-20:00 מתעדכן הטאב "מחר" עם משימות מסוכמות

---

## שלב 6 — PWA + Push Notifications + Conflict Detection (פיצ'ר 6)
> _הכי מורכב — מחייב HTTPS + backend push server_

**6A — PWA (prerequisite):**
- `manifest.json` עם icons, theme_color, display: standalone
- Service Worker: cache strategy + background sync
- "הוסף למסך הבית" prompt

**6B — Conflict Detection:**
- לוגיקה: לכל אירוע חדש → scan events±1h → אם overlap → `conflict: true`
- Frontend: badge אדום + modal "⚠️ חפיפה: נוגה וגם אלון ב-16:00 — מי הולך?"
- פתרון: assign parent (dropdown) → נשמר ב-data

**6C — Web Push:**
- backend: `web-push` Node.js library + שמירת subscription ב-JSON
- התראה: 1 שעה לפני אירוע + digest בוקר 07:30
- Frontend: בקשת הרשאה חלקה (לאחר אינטראקציה ראשונה)

**שינויים ב-data.json:** `events[].conflict`, `events[].assignedParent`, `push_subscriptions[]`

**תנאי סיום:** פתיחת האפליקציה מ-homescreen → התראה 1h לפני חוג

---

## סדר ביצוע מומלץ

```
0 (תשתית) → 1 (cards) → 4 (timeline) → 2 (categories) → 5 (digest) → 3 (drive) → 6 (PWA+push)
```

**הסבר הסדר:**
- 0+1: ערך מיידי, אפס סיכון
- 4 לפני 2: Timeline הוא backbone — categories תלויות בו
- 5 לפני 3: Digest קל יחסית ומסיים את ה"ליבה"
- 3 ו-6 אחרונים: הכי מורכבים, תלויים בכל השאר

---

## מה מוכן לבניה עכשיו
- [ ] שלב 0.1 — תיקון overlay bugs
- [ ] שלב 0.2 — schema definition
- [ ] שלב 0.3 — PWA manifest + basic SW
- [ ] שלב 1 — Expandable Cards (pure CSS/JS, ~1 שעה)
