#!/bin/bash
# FamilyOS — push.sh
# מעדכן data.json (WhatsApp + Gmail + Calendar) ומפרסם ל-GitHub Pages

set -e
REPO_DIR="/tmp/familyos"
cd "$REPO_DIR"

echo "📱 Fetching WhatsApp messages..."
python3 fetch_messages.py

echo "📧 Fetching Gmail + Calendar..."
python3 generate_data.py 2>/dev/null || echo "⚠️  generate_data.py נכשל — נמשיך עם WhatsApp בלבד"

echo "📦 Pushing to GitHub Pages..."
git add data.json
git diff --cached --quiet && echo "Nothing to commit" && exit 0

git commit -m "data: auto-update $(date '+%Y-%m-%d %H:%M')"
git push origin main

echo "✅ FamilyOS deployed → https://noamm-opencalw.github.io/familyos/"
