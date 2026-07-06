#!/bin/zsh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

if [ -x "/Library/Frameworks/Python.framework/Versions/3.11/bin/python3" ]; then
  PYTHON_BIN="${PYTHON_BIN:-/Library/Frameworks/Python.framework/Versions/3.11/bin/python3}"
else
  PYTHON_BIN="${PYTHON_BIN:-$(command -v python3)}"
fi

export MACOSX_DEPLOYMENT_TARGET="${MACOSX_DEPLOYMENT_TARGET:-16.0}"

"$PYTHON_BIN" -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
pip install -r requirements-build.txt

pyinstaller \
  --name "TelegramVideoDownloader" \
  --windowed \
  --onefile \
  --clean \
  --collect-all tkinter \
  ui_app.py

BIN_PATH="$ROOT_DIR/dist/TelegramVideoDownloader"
APP_PATH="$ROOT_DIR/dist/TelegramVideoDownloader.app"

if [ ! -d "$APP_PATH" ] && [ -f "$BIN_PATH" ]; then
  TMP_SCRIPT="$(mktemp /tmp/telegram_downloader_applescript.XXXXXX)"
  cat > "$TMP_SCRIPT" <<EOF
set binPath to quoted form of "${BIN_PATH}"
tell application "Terminal"
  activate
  do script binPath
end tell
EOF
  rm -rf "$APP_PATH"
  osacompile -o "$APP_PATH" "$TMP_SCRIPT"
  rm -f "$TMP_SCRIPT"
fi

if [ -d "$APP_PATH" ]; then
  zip -r "TelegramVideoDownloader-macos.zip" "dist/TelegramVideoDownloader.app"
else
  zip -r "TelegramVideoDownloader-macos.zip" "dist/TelegramVideoDownloader"
fi

echo "Built: dist/TelegramVideoDownloader (binary)"
echo "Built: dist/TelegramVideoDownloader.app (if available)"
echo "Zip:   TelegramVideoDownloader-macos.zip"
