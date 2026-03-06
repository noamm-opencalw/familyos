#!/usr/bin/env python3
"""
FamilyOS calendar_api.py — Local proxy server for Google Calendar add/remove
Runs on localhost:8787 — use when developing locally (GitHub Pages = use deeplinks instead)

Usage:
  python3 calendar_api.py          # starts on port 8787
  python3 calendar_api.py --port 9999

CORS-enabled so the static index.html can call it from localhost or file://.

Endpoints:
  GET  /status                     → health check
  POST /event/create               → create event on primary calendar
  POST /event/delete               → delete event by ID
  GET  /events?from=YYYY-MM-DD&to=YYYY-MM-DD  → list events

All responses are JSON.
"""

import json
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timedelta

ACCOUNT = "noammeir@gmail.com"
PORT = 8787


def run_gog(args):
    """Run a gog command and return parsed JSON output."""
    cmd = ["gog"] + args + ["--account", ACCOUNT, "--json"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "gog command failed")
    return json.loads(result.stdout)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        print(f"  [{self.client_address[0]}] {format % args}")

    def send_cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_cors()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        if path == "/status":
            self.json_response({"ok": True, "service": "FamilyOS Calendar API", "account": ACCOUNT})

        elif path == "/events":
            frm = qs.get("from", [datetime.now().strftime("%Y-%m-%d")])[0]
            to  = qs.get("to",   [(datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")])[0]
            try:
                data = run_gog(["calendar", "events", "primary", "--from", frm, "--to", to, "--max", "60"])
                self.json_response(data)
            except Exception as e:
                self.json_error(str(e), 500)

        elif path == "/regenerate":
            try:
                result = subprocess.run(
                    ["python3", "generate_data.py"],
                    capture_output=True, text=True, timeout=120, cwd="."
                )
                self.json_response({
                    "ok": result.returncode == 0,
                    "stdout": result.stdout,
                    "stderr": result.stderr
                })
            except Exception as e:
                self.json_error(str(e), 500)

        else:
            self.json_error("Not found", 404)

    def do_POST(self):
        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len)
        try:
            payload = json.loads(body) if body else {}
        except:
            payload = {}

        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/event/create":
            # Required: summary, start, end
            # Optional: description, location, colorId
            summary = payload.get("summary", "")
            start   = payload.get("start", "")
            end     = payload.get("end", start)
            desc    = payload.get("description", "")
            loc     = payload.get("location", "")

            if not summary or not start:
                self.json_error("summary and start are required", 400)
                return

            args = ["calendar", "events", "create", "primary",
                    "--summary", summary, "--start", start, "--end", end]
            if desc:    args += ["--description", desc]
            if loc:     args += ["--location", loc]

            try:
                data = run_gog(args)
                self.json_response({"ok": True, "event": data})
            except Exception as e:
                self.json_error(str(e), 500)

        elif path == "/event/delete":
            event_id = payload.get("id", "")
            if not event_id:
                self.json_error("id is required", 400)
                return
            try:
                run_gog(["calendar", "events", "delete", "primary", event_id])
                self.json_response({"ok": True, "deleted": event_id})
            except Exception as e:
                self.json_error(str(e), 500)

        else:
            self.json_error("Not found", 404)

    def json_response(self, data, code=200):
        payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_cors()
        self.end_headers()
        self.wfile.write(payload)

    def json_error(self, msg, code=400):
        self.json_response({"error": msg, "ok": False}, code)


def main():
    port = PORT
    if "--port" in sys.argv:
        idx = sys.argv.index("--port")
        port = int(sys.argv[idx + 1])

    server = HTTPServer(("localhost", port), Handler)
    print(f"🚀 FamilyOS Calendar API → http://localhost:{port}")
    print(f"   Account: {ACCOUNT}")
    print(f"   Endpoints: GET /status, /events  POST /event/create, /event/delete")
    print(f"   Press Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n⛔ Server stopped")


if __name__ == "__main__":
    main()
