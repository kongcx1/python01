#!/usr/bin/env bash
set -euo pipefail

SERVER_ROOT="${SERVER_ROOT:-/opt/telegram_downloader}"
DOWNLOAD_ROOT="${DOWNLOAD_ROOT:-/data/telegram_downloads}"

echo "==> Installing system packages"
sudo apt update
sudo apt install -y python3-venv python3-pip

echo "==> Preparing directories"
sudo mkdir -p "$SERVER_ROOT" "$DOWNLOAD_ROOT"
sudo chown -R "$USER:$USER" "$SERVER_ROOT" "$DOWNLOAD_ROOT"

echo "==> Creating venv and installing dependencies"
cd "$SERVER_ROOT"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-server.txt

CONFIG_PATH="$SERVER_ROOT/server_config.json"
if [[ ! -f "$CONFIG_PATH" ]]; then
  echo "==> Writing server_config.json"
  TELEGRAM_API_ID="${TELEGRAM_API_ID:-}"
  TELEGRAM_API_HASH="${TELEGRAM_API_HASH:-}"
  UPLOAD_BASE_URL="${UPLOAD_BASE_URL:-https://webim.ldp001.cfd}"
  UPLOAD_ACCOUNT="${UPLOAD_ACCOUNT:-}"
  UPLOAD_PASSWORD="${UPLOAD_PASSWORD:-}"
  AUTO_UPLOAD_DEFAULT="${AUTO_UPLOAD_DEFAULT:-true}"
  UPLOAD_META="${UPLOAD_META:-true}"
  cat > "$CONFIG_PATH" <<EOF
{
  "download_root": "$DOWNLOAD_ROOT",
  "telegram_api_id": "$TELEGRAM_API_ID",
  "telegram_api_hash": "$TELEGRAM_API_HASH",
  "upload_base_url": "$UPLOAD_BASE_URL",
  "upload_account": "$UPLOAD_ACCOUNT",
  "upload_password": "$UPLOAD_PASSWORD",
  "upload_meta": $UPLOAD_META,
  "auto_upload_default": $AUTO_UPLOAD_DEFAULT
}
EOF
  echo "==> Config written to $CONFIG_PATH"
fi

echo "==> Setup done"
echo "Next: run 'python server_login.py' once to create Telegram session."
