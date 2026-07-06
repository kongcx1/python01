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
  --name "OKXSpotTrader" \
  --windowed \
  --onefile \
  --clean \
  --collect-all tkinter \
  okx_ui.py

BIN_PATH="$ROOT_DIR/dist/OKXSpotTrader"
APP_PATH="$ROOT_DIR/dist/OKXSpotTrader.app"

if [ ! -d "$APP_PATH" ] && [ -f "$BIN_PATH" ]; then
  TMP_SCRIPT="$(mktemp /tmp/okx_spot_trader_applescript.XXXXXX)"
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
  zip -r "OKXSpotTrader-macos.zip" "dist/OKXSpotTrader.app"
else
  zip -r "OKXSpotTrader-macos.zip" "dist/OKXSpotTrader"
fi

echo "Built: dist/OKXSpotTrader (binary)"
echo "Built: dist/OKXSpotTrader.app (if available)"
echo "Zip:   OKXSpotTrader-macos.zip"
