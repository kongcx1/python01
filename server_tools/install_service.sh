#!/usr/bin/env bash
set -euo pipefail

SERVICE_PATH="/etc/systemd/system/telegram_downloader.service"
SOURCE_PATH="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/telegram_downloader.service"

echo "==> Installing systemd service"
sudo cp "$SOURCE_PATH" "$SERVICE_PATH"
sudo systemctl daemon-reload
sudo systemctl enable telegram_downloader.service
sudo systemctl restart telegram_downloader.service

echo "==> Service status"
sudo systemctl status telegram_downloader.service --no-pager
