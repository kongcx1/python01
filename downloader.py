from pathlib import Path
from downloader_core import run_download


CHANNEL_USERNAME = "@sosocw"
MAX_VIDEOS_PER_BATCH = 50
OUTPUT_DIR = Path.home() / "Desktop" / "telegram_videos_sosocw"


def main() -> None:
    run_download(
        channel=CHANNEL_USERNAME,
        max_videos=MAX_VIDEOS_PER_BATCH,
        output_dir=OUTPUT_DIR,
        allow_prompt=True,
    )


if __name__ == "__main__":
    main()
