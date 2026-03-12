#!/usr/bin/env python3
"""
FamilyOS — push_server.py  (שלב 6C)
שרת Web Push מקומי — מקבל subscriptions ושולח notifications.
פועל על :19876 (משולב עם שרת ה-refresh הקיים).

שימוש:
  python3 push_server.py              # הפעלה
  python3 push_server.py --gen-keys   # יצירת VAPID keys
  python3 push_server.py --test-push  # שליחת push לבדיקה
"""

import json, os, sys, time, threading, subprocess
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

PORT         = 19876
DATA_JSON    = Path("/tmp/familyos/data.json")
KEYS_FILE    = Path("/tmp/familyos/.vapid_keys.json")
SUBS_FILE    = Path("/tmp/familyos/.push_subscriptions.json")

# ── VAPID Key Management ──────────────────────────────────────────────────────

def gen_vapid_keys():
    """מייצר VAPID keys בעזרת py_vapid / pywebpush"""
    try:
        import base64
        from py_vapid import Vapid
        from cryptography.hazmat.primitives.serialization import (
            Encoding, PublicFormat, PrivateFormat, NoEncryption)
        vapid = Vapid()
        vapid.generate_keys()
        pub_bytes  = vapid.public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
        priv_bytes = vapid.private_key.private_bytes(Encoding.PEM, PrivateFormat.TraditionalOpenSSL, NoEncryption())
        pub  = base64.urlsafe_b64encode(pub_bytes).rstrip(b'=').decode()
        priv = base64.urlsafe_b64encode(priv_bytes).rstrip(b'=').decode()
        keys = {"public": pub, "private": priv}
        KEYS_FILE.write_text(json.dumps(keys, indent=2))
        print(f"✅ VAPID keys generated")
        print(f"  Public:  {pub}")
        print(f"  Private: {priv[:20]}...")
        print(f"\n📋 הוסף את המפתח הציבורי ל-index.html:")
        print(f"  const VAPID_PUBLIC_KEY = '{pub}';")
        return keys
    except ImportError:
        print("❌ pywebpush לא מותקן. הרץ: pip install pywebpush")
        return None


def load_vapid_keys():
    if KEYS_FILE.exists():
        return json.loads(KEYS_FILE.read_text())
    return None


def load_subscriptions() -> list:
    if SUBS_FILE.exists():
        try:
            return json.loads(SUBS_FILE.read_text())
        except:
            pass
    return []


def save_subscription(sub: dict):
    subs = load_subscriptions()
    # הימנע מכפילויות (לפי endpoint)
    endpoint = sub.get("endpoint","")
    subs = [s for s in subs if s.get("endpoint") != endpoint]
    subs.append(sub)
    SUBS_FILE.write_text(json.dumps(subs, indent=2))
    print(f"  💾 Subscription saved (total: {len(subs)})")


# ── Push Sender ───────────────────────────────────────────────────────────────

def send_push(sub: dict, payload: dict, keys: dict) -> bool:
    """שולח push notification ל-subscription אחת"""
    try:
        from pywebpush import webpush, WebPushException
        webpush(
            subscription_info=sub,
            data=json.dumps(payload, ensure_ascii=False),
            vapid_private_key=keys["private"],
            vapid_claims={"sub": "mailto:noammeir@gmail.com"},
        )
        return True
    except ImportError:
        print("  ❌ pywebpush לא מותקן")
        return False
    except Exception as e:
        print(f"  ⚠️ Push failed: {e}")
        return False


def broadcast_push(payload: dict):
    """שולח push לכל הsubscriptions"""
    keys = load_vapid_keys()
    if not keys:
        print("  ⚠️ אין VAPID keys")
        return 0
    subs = load_subscriptions()
    if not subs:
        print("  ⚠️ אין subscriptions")
        return 0
    ok = 0
    for sub in subs:
        if send_push(sub, payload, keys):
            ok += 1
    print(f"  📲 שלחתי {ok}/{len(subs)} pushes")
    return ok


# ── Event Reminder Scheduler ──────────────────────────────────────────────────

def check_upcoming_events():
    """בודק כל 5 דקות — שולח push 1 שעה לפני אירוע"""
    sent_key = 'familyos_push_sent'
    sent = set()

    while True:
        try:
            if DATA_JSON.exists():
                data = json.loads(DATA_JSON.read_text())
                events = data.get("events", [])
                now = datetime.now(timezone(timedelta(hours=2)))

                for ev in events:
                    d = ev.get("date","")
                    if "T" not in d: continue
                    try:
                        dt = datetime.fromisoformat(d.replace("Z","+00:00"))
                        diff_min = (dt - now).total_seconds() / 60
                        ev_key = f"{ev.get('id',0)}-{d}"

                        # שלח 60 דקות לפני (חלון של 5 דקות)
                        if 55 <= diff_min <= 65 and ev_key not in sent:
                            child_names = {"ran":"רן","itai":"איתי","noga":"נוגה","alon":"אלון","all":"ילדים"}
                            child = child_names.get(ev.get("child","all"), "")
                            title_clean = ev.get("title","").replace("["+child+"]","").strip().lstrip("📚").strip()
                            broadcast_push({
                                "title": f"⏰ עוד שעה — {child}",
                                "body":  title_clean[:80],
                                "tag":   ev_key,
                                "url":   "./?tab=calendar",
                            })
                            sent.add(ev_key)
                            print(f"  🔔 Reminder sent: {title_clean[:40]}")
                    except:
                        pass
        except Exception as e:
            print(f"  ⚠️ Scheduler error: {e}")

        time.sleep(300)  # כל 5 דקות


# ── HTTP Server ───────────────────────────────────────────────────────────────

class FamilyOSHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # suppress default logs

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        body   = self.rfile.read(length) if length else b''

        if self.path == '/subscribe':
            try:
                sub = json.loads(body)
                save_subscription(sub)
                self._json({"ok": True})
            except Exception as e:
                self._json({"error": str(e)}, 400)

        elif self.path == '/push':
            try:
                payload = json.loads(body)
                n = broadcast_push(payload)
                self._json({"sent": n})
            except Exception as e:
                self._json({"error": str(e)}, 400)

        elif self.path == '/refresh':
            # trigger push.sh (existing behaviour)
            try:
                subprocess.Popen(
                    ["bash", "/tmp/familyos/push.sh"],
                    stdout=open('/tmp/familyos/push.log','a'),
                    stderr=subprocess.STDOUT
                )
                self._json({"ok": True})
            except Exception as e:
                self._json({"error": str(e)}, 500)

        else:
            self._json({"error": "not found"}, 404)

    def do_GET(self):
        if self.path == '/health':
            self._json({"ok": True, "subscriptions": len(load_subscriptions())})
        elif self.path == '/vapid-public-key':
            keys = load_vapid_keys()
            if keys:
                self._json({"publicKey": keys["public"]})
            else:
                self._json({"error": "no keys"}, 404)
        else:
            self._json({"error": "not found"}, 404)

    def _json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self._cors()
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)

    def _cors(self):
        self.send_header('Access-Control-Allow-Origin',  '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')


def main():
    if '--gen-keys' in sys.argv:
        gen_vapid_keys()
        return

    if '--test-push' in sys.argv:
        broadcast_push({
            "title": "🧪 FamilyOS Test",
            "body":  "Push notifications עובד! 🎉",
            "tag":   "test",
        })
        return

    # Start event reminder thread
    t = threading.Thread(target=check_upcoming_events, daemon=True)
    t.start()

    server = HTTPServer(('0.0.0.0', PORT), FamilyOSHandler)
    print(f"🚀 FamilyOS Push Server on :{PORT}")
    print(f"  /subscribe  — register push subscription")
    print(f"  /push       — broadcast notification")
    print(f"  /refresh    — trigger push.sh")
    print(f"  /health     — status")
    keys = load_vapid_keys()
    if keys:
        print(f"  VAPID public: {keys['public'][:30]}...")
    else:
        print(f"  ⚠️ No VAPID keys — run with --gen-keys first")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 Server stopped")


if __name__ == "__main__":
    main()
