#!/usr/bin/env bash
set -euo pipefail

case "${1:-}" in
  start)
    sudo systemctl start telegram_downloader.service
    ;;
  stop)
    sudo systemctl stop telegram_downloader.service
    ;;
  restart)
    sudo systemctl restart telegram_downloader.service
    ;;
  status)
    sudo systemctl status telegram_downloader.service --no-pager
    ;;
  log)
    sudo journalctl -u telegram_downloader.service -n 200 --no-pager
    ;;
  *)
    echo "Usage: $0 {start|stop|restart|status|log}"
    exit 1
    ;;
esac
