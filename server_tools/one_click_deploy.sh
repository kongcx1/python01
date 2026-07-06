#!/usr/bin/env bash
set -euo pipefail

LOCAL_DIR="${LOCAL_DIR:-/Users/huangjin/python01}"
REMOTE_USER="${REMOTE_USER:-ubuntu}"
REMOTE_DIR="${REMOTE_DIR:-/opt/telegram_downloader}"
DOWNLOAD_ROOT="${DOWNLOAD_ROOT:-/data/telegram_downloads}"

if [[ -z "${PEM_PATH:-}" ]]; then
  read -r -p "PEM path (e.g. ~/Downloads/telegramDownload.pem): " PEM_PATH
fi
if [[ -z "${SERVER_IP:-}" ]]; then
  read -r -p "Server IP: " SERVER_IP
fi
if [[ -z "${TELEGRAM_API_ID:-}" ]]; then
  read -r -p "Telegram API ID: " TELEGRAM_API_ID
fi
if [[ -z "${TELEGRAM_API_HASH:-}" ]]; then
  read -r -p "Telegram API HASH: " TELEGRAM_API_HASH
fi
if [[ -z "${UPLOAD_ACCOUNT:-}" ]]; then
  read -r -p "Upload account: " UPLOAD_ACCOUNT
fi
if [[ -z "${UPLOAD_PASSWORD:-}" ]]; then
  read -r -p "Upload password: " UPLOAD_PASSWORD
fi
if [[ -z "${SESSION_PATH:-}" ]]; then
  read -r -p "Session path (optional, Enter to skip): " SESSION_PATH
fi

PEM_PATH="${PEM_PATH/#\~/$HOME}"
SESSION_PATH="${SESSION_PATH/#\~/$HOME}"

echo "==> Uploading code to server"
scp -i "$PEM_PATH" -r "$LOCAL_DIR"/* "${REMOTE_USER}@${SERVER_IP}:${REMOTE_DIR}"

echo "==> Running server setup"
ssh -i "$PEM_PATH" "${REMOTE_USER}@${SERVER_IP}" bash -lc " \
  cd ${REMOTE_DIR} && \
  chmod +x server_tools/setup_server.sh server_tools/install_service.sh server_tools/manage.sh && \
  TELEGRAM_API_ID='${TELEGRAM_API_ID}' \
  TELEGRAM_API_HASH='${TELEGRAM_API_HASH}' \
  UPLOAD_ACCOUNT='${UPLOAD_ACCOUNT}' \
  UPLOAD_PASSWORD='${UPLOAD_PASSWORD}' \
  DOWNLOAD_ROOT='${DOWNLOAD_ROOT}' \
  ./server_tools/setup_server.sh \
"

if [[ -n "${SESSION_PATH}" ]]; then
  echo "==> Uploading Telegram session"
  scp -i "$PEM_PATH" "$SESSION_PATH" "${REMOTE_USER}@${SERVER_IP}:${DOWNLOAD_ROOT}/user_session.session"
fi

echo "==> Telegram login (only if no session)"
ssh -i "$PEM_PATH" "${REMOTE_USER}@${SERVER_IP}" bash -lc " \
  cd ${REMOTE_DIR} && \
  source .venv/bin/activate && \
  if [[ ! -f ${DOWNLOAD_ROOT}/user_session.session ]]; then \
    python server_login.py; \
  else \
    echo 'Session already exists, skip login.'; \
  fi \
"

echo "==> Installing/Restarting service"
ssh -i "$PEM_PATH" "${REMOTE_USER}@${SERVER_IP}" bash -lc " \
  cd ${REMOTE_DIR} && \
  sudo ./server_tools/install_service.sh \
"

echo "==> Done"
echo "Test: curl http://${SERVER_IP}:8787/tasks"
