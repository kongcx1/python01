import json
import os
from pathlib import Path

from downloader_core import run_login


CONFIG_PATH = Path(os.getenv("SERVER_CONFIG", "server_config.json"))


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def main() -> None:
    config = load_config()
    api_id = config.get("telegram_api_id")
    api_hash = config.get("telegram_api_hash")
    if not api_id or not api_hash:
        raise SystemExit("缺少 telegram_api_id/telegram_api_hash，请先配置 server_config.json")
    output_dir = Path(config.get("download_root", "downloads")).expanduser().resolve()
    print("开始登录 Telegram，按提示输入手机号/验证码/二步密码...")
    run_login(output_dir=output_dir, api_id=api_id, api_hash=api_hash, allow_prompt=True)
    print("登录完成，session 已保存。")


if __name__ == "__main__":
    main()
