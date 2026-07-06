# Telegram Channel Video Downloader (User Login)

This tool downloads up to 50 videos per run from a public channel and saves
each video's caption and tags (hashtags) alongside the video file.

Important limitations:
- You must log in with your own Telegram account on first run.
- This tool does **not** bypass Telegram rate limits or rules.

## Setup

1. Create a Telegram API app to get `api_id` and `api_hash`:
   - https://my.telegram.org/apps
2. Make sure your account can view the channel `@sosocw`.

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## OKX Spot Auto Trader (CLI)

本仓库包含一个最小可用的 OKX 现货自动交易脚本，支持买入/卖出阈值与基础风控。默认 `dry_run=true`，不会真实下单。

### 1) 配置

复制示例配置并填入 API 信息：

```bash
cp okx_config.example.json okx_config.json
```

配置文件说明：
- `trade.inst_id`: 交易对（如 `BTC-USDT`）
- `strategy.buy_below`: 低于该价格买入
- `strategy.sell_above`: 高于该价格卖出
- `risk.stop_loss_pct`: 止损比例（如 0.05 = 5%）
- `risk.take_profit_pct`: 止盈比例
- `trade.dry_run`: 是否只模拟不下单

### 2) 运行

单次执行（便于测试）：

```bash
python okx_bot.py --config okx_config.json --once
```

循环执行（后台长期运行）：

```bash
python okx_bot.py --config okx_config.json
```

## OKX UI（中文）

启动桌面 UI：

```bash
python okx_ui.py
```

说明：
- 支持加载/保存配置、单次运行与循环执行
- 日志面板会显示运行输出（不会显示 API 密钥）
- 运行前请确认 `dry_run` 是否关闭

## 策略框架与风控

支持的策略类型（`strategy.type`）：
- `threshold`：价格阈值（`buy_below`/`sell_above`）
- `ma_cross`：均线交叉（`ma_short_window`/`ma_long_window`）
- `rsi_reversion`：RSI 反转（`rsi_period`/`rsi_buy`/`rsi_sell`）
- `breakout`：突破（`breakout_window`）

风控配置（`risk`）：
- `max_daily_loss_pct`：日内最大亏损比例
- `max_drawdown_pct`：最大回撤比例
- `max_trades_per_day`：日内最大交易次数
- 仍保留：止损/止盈/仓位上限/冷却时间

### 3) 说明

- 仅支持现货 `cash` 模式与市价单。
- 风控基于本地 `okx_state.json`，假设不会有外部交易影响持仓。
- 如需更复杂策略（RSI/MACD/多币种），可以在 `okx_bot.py` 中扩展。

## Run (CLI)

```bash
export TELEGRAM_API_ID="123456"
export TELEGRAM_API_HASH="your_api_hash"

python downloader.py
```

## Output

Files are saved to:

```
~/Desktop/telegram_videos_sosocw
```

For each downloaded video:
- The video file (original filename if available).
- A `.json` file containing metadata (caption, tags, etc.).
- `manifest.csv` with one row per video.

On first run, you will be prompted to enter your phone number and login code.
If you don't set env vars, it will ask for `api_id` and `api_hash` and save
them to `config.json` in the output folder.

## Resume / Checkpoint

The script supports resume:
- It keeps `manifest.csv` and skips already-downloaded message IDs.
- If a video file already exists with the correct size, it records metadata
  without re-downloading.

## Build macOS App (Apple Silicon)

This creates a double-clickable `.app` and a zip package.

```bash
chmod +x build_macos.sh
./build_macos.sh
```

Output:
- `dist/TelegramVideoDownloader.app`
- `TelegramVideoDownloader-macos.zip`

Run the app by double-clicking it. A UI window will open.

## UI App

The UI lets you input API credentials, channel, output folder, and batch size.
It saves API credentials to `config.json` inside the output folder.

Features:
- Progress bar with current/total and download speed.
- Pause/Resume/Stop (pause and stop take effect after current file).
- Date range filter (YYYY-MM-DD).
- History list from `manifest.csv`.
- One-click open output folder.
- Click video name to preview on Telegram web.
- Merge selected videos into one file (requires ffmpeg).
- Auto-merge short segments by duration threshold (requires ffmpeg).

### Auto Update Check

Set an update URL that returns JSON:

```
{"version":"1.2.1","url":"https://example.com/download"}
```

Then launch the app with:

```bash
export TELEGRAM_DOWNLOADER_UPDATE_URL="https://example.com/version.json"
```

## Build DMG

```bash
chmod +x build_dmg.sh
./build_dmg.sh
```

Output:
- `TelegramVideoDownloader.dmg`

## macOS Version Compatibility

If you see an error like:

```
macOS 26 or later required, have instead 16
```

it means the build used a Python that targets a higher macOS version.
Install Python from python.org (e.g. 3.11) and rebuild:

```bash
export PYTHON_BIN="/Library/Frameworks/Python.framework/Versions/3.11/bin/python3"
./build_macos.sh
```

## Server-side Downloader (Ubuntu)

Use the macOS client only for filtering and task dispatch. The Ubuntu server runs
the actual download + auto-upload to S3.

### 1) Install dependencies on the server

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-server.txt
```

### 2) Configure `server_config.json`

Copy the example and fill in your values:

```bash
cp server_config.example.json server_config.json
```

Fields:
- `download_root`: where video files are saved on the server
- `telegram_api_id` / `telegram_api_hash`: Telegram API credentials
- `upload_base_url` / `upload_account` / `upload_password`: your upload API
- `upload_meta`: whether to upload JSON metadata + thumbnails
- `auto_upload_default`: default auto upload for tasks

### 3) Login Telegram once (creates session)

```bash
python server_login.py
```

### 4) Start the task server

```bash
uvicorn server_app:app --host 0.0.0.0 --port 8787
```

### 5) Submit a download task (from macOS)

```bash
curl -X POST "http://<SERVER_IP>:8787/tasks" \
  -H "Content-Type: application/json" \
  -d '{
    "channel": "sosocw",
    "message_ids": [13639, 13640],
    "auto_upload": true,
    "upload_meta": true
  }'
```

Check task status:

```bash
curl "http://<SERVER_IP>:8787/tasks/1"
```

Cancel a running task:

```bash
curl -X POST "http://<SERVER_IP>:8787/tasks/1/cancel"
```

### One-command setup (automated)

On the server, after uploading this repo to `/opt/telegram_downloader`, run:

```bash
cd /opt/telegram_downloader
chmod +x server_tools/setup_server.sh
TELEGRAM_API_ID="your_id" \
TELEGRAM_API_HASH="your_hash" \
UPLOAD_ACCOUNT="testacc" \
UPLOAD_PASSWORD="123456" \
./server_tools/setup_server.sh
```

Then login once:

```bash
source /opt/telegram_downloader/.venv/bin/activate
python /opt/telegram_downloader/server_login.py
```

Install auto-start service:

```bash
chmod +x server_tools/install_service.sh
sudo ./server_tools/install_service.sh
```

Service management:

```bash
chmod +x server_tools/manage.sh
./server_tools/manage.sh status
./server_tools/manage.sh log
```

### One-click (macOS) deploy

Run this on your Mac:

```bash
chmod +x server_tools/one_click_deploy.sh
PEM_PATH=~/Downloads/telegramDownload.pem \
SERVER_IP=54.46.103.244 \
TELEGRAM_API_ID="30535444" \
TELEGRAM_API_HASH="cf0a2bc9e25e62ddf892e934ce62e4ae" \
UPLOAD_ACCOUNT="testacc" \
UPLOAD_PASSWORD="123456" \
./server_tools/one_click_deploy.sh
```

It will upload code, install dependencies, create config, login if needed,
and restart the service.

To make it fully automatic without manual login, pass the Telegram session
file from your Mac:

```bash
PEM_PATH=~/Downloads/telegramDownload.pem \
SERVER_IP=54.46.103.244 \
TELEGRAM_API_ID="30535444" \
TELEGRAM_API_HASH="cf0a2bc9e25e62ddf892e934ce62e4ae" \
UPLOAD_ACCOUNT="testacc" \
UPLOAD_PASSWORD="123456" \
SESSION_PATH="/Users/huangjin/Desktop/telegram_videos_sosocw/user_session.session" \
./server_tools/one_click_deploy.sh
```

### One-click (macOS) submit task

```bash
chmod +x server_tools/one_click_submit.sh
SERVER_URL="http://54.46.103.244:8787" \
CHANNEL="@sosocw" \
AUTO_UPLOAD=true \
UPLOAD_META=true \
IDS_CSV="13991,13993" \
./server_tools/one_click_submit.sh
```

If `IDS_CSV` is empty, the script will prompt you.
