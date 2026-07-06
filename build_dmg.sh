#!/bin/zsh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

./build_macos.sh

APP_PATH="$ROOT_DIR/dist/TelegramVideoDownloader.app"
DMG_NAME="TelegramVideoDownloader.dmg"
TMP_DIR="$(mktemp -d /tmp/telegram_downloader_dmg.XXXXXX)"

if [ ! -d "$APP_PATH" ]; then
  echo "Missing app bundle at $APP_PATH"
  exit 1
fi

cp -R "$APP_PATH" "$TMP_DIR/"

hdiutil create \
  -volname "TelegramVideoDownloader" \
  -srcfolder "$TMP_DIR" \
  -ov -format UDZO \
  "$ROOT_DIR/$DMG_NAME"

rm -rf "$TMP_DIR"

echo "Built: $DMG_NAME"
