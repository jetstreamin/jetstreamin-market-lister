#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
pkg update -y
pkg install -y python termux-api
chmod +x app.py jet
mkdir -p data/photos data/exports
echo
echo "Installed. The separate Termux:API Android app is required for camera access."
echo "Start with: ./jet"
