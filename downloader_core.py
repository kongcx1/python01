import asyncio
import csv
import json
import os
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable, Iterable, Optional

from telethon import TelegramClient
from telethon.errors import RPCError, SessionPasswordNeededError
from telethon.tl.types import DocumentAttributeVideo


TAG_PATTERN = re.compile(r"#([^\s#]+)")
AD_TEXT_STRIP_PATTERN = re.compile(r"[\s*_|\-—·,，.。:：;；!！?？【】\[\]()（）]+")
MANIFEST_NAME = "manifest.csv"
CONFIG_NAME = "config.json"
def _get_part_size_kb() -> int:
    try:
        part_kb = max(1, int(os.getenv("TELEGRAM_DOWNLOAD_PART_KB", "512")))
        return min(512, part_kb)
    except (TypeError, ValueError):
        return 512


def _get_concurrency() -> int:
    try:
        return max(1, int(os.getenv("TELEGRAM_DOWNLOAD_CONCURRENCY", "1")))
    except (TypeError, ValueError):
        return 1
DEFAULT_DOWNLOAD_TIMEOUT_SEC = int(
    os.getenv("TELEGRAM_DOWNLOAD_TIMEOUT_SEC", "60")
)
_preview_media_tasks: set[asyncio.Task] = set()


def _track_preview_media_task(task: asyncio.Task) -> asyncio.Task:
    _preview_media_tasks.add(task)

    def _consume_result(done_task: asyncio.Task) -> None:
        _preview_media_tasks.discard(done_task)
        if done_task.cancelled():
            return
        try:
            done_task.exception()
        except BaseException:
            pass

    task.add_done_callback(_consume_result)
    return task


async def drain_preview_media_tasks(timeout: float = 4.0) -> None:
    tasks = [task for task in list(_preview_media_tasks) if not task.done()]
    if not tasks:
        return
    try:
        await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True),
            timeout=timeout,
        )
        return
    except asyncio.TimeoutError:
        pass
    except BaseException:
        return
    for task in tasks:
        if not task.done():
            task.cancel()
    try:
        await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True),
            timeout=1,
        )
    except BaseException:
        pass


def _is_telethon_internal_task(task: asyncio.Task) -> bool:
    if task.done() or task is asyncio.current_task():
        return False
    coro = task.get_coro()
    code = getattr(coro, "cr_code", None)
    filename = str(getattr(code, "co_filename", "")).replace("\\", "/").lower()
    name = str(getattr(code, "co_name", ""))
    if "telethon/" not in filename:
        return False
    return name in {
        "_send_loop",
        "_recv_loop",
        "_keepalive_loop",
        "_reconnect",
    }


async def _cancel_pending_telethon_tasks() -> None:
    tasks = [task for task in asyncio.all_tasks() if _is_telethon_internal_task(task)]
    if not tasks:
        return
    for task in tasks:
        task.cancel()
    try:
        await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True), timeout=2
        )
    except BaseException:
        pass
    await asyncio.sleep(0)


async def _wait_client_telethon_tasks(client: TelegramClient, timeout: float = 2.0) -> None:
    tasks: set[asyncio.Task] = set()
    objects = [
        client,
        getattr(client, "_sender", None),
        getattr(getattr(client, "_sender", None), "_connection", None),
    ]
    for obj in objects:
        if obj is None:
            continue
        for value in getattr(obj, "__dict__", {}).values():
            if isinstance(value, asyncio.Task) and _is_telethon_internal_task(value):
                tasks.add(value)
    if not tasks:
        return
    try:
        await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=timeout)
    except asyncio.TimeoutError:
        for task in tasks:
            if not task.done():
                task.cancel()
        try:
            await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=1)
        except BaseException:
            pass


async def _disconnect_telethon_object(obj: object, timeout: float = 2.0) -> None:
    async def _maybe_await(result: object) -> None:
        if hasattr(result, "__await__"):
            await asyncio.wait_for(result, timeout=timeout)  # type: ignore[arg-type]

    for method_name in ("disconnect", "close"):
        method = getattr(obj, method_name, None)
        if not callable(method):
            continue
        try:
            await _maybe_await(method())
        except BaseException:
            pass


async def close_client(client: TelegramClient) -> None:
    async def _maybe_await(result: object) -> None:
        if hasattr(result, "__await__"):
            await asyncio.wait_for(result, timeout=3)  # type: ignore[arg-type]

    sender = getattr(client, "_sender", None)
    connection = getattr(sender, "_connection", None) if sender is not None else None
    await drain_preview_media_tasks(timeout=4)
    try:
        await _maybe_await(client.disconnect())
    except BaseException:
        pass
    await _disconnect_telethon_object(sender)
    await _disconnect_telethon_object(connection)
    await _wait_client_telethon_tasks(client, timeout=4)
    await _cancel_pending_telethon_tasks()
    await asyncio.sleep(0.5)
    await _wait_client_telethon_tasks(client, timeout=2)
    try:
        client.session.close()
    except BaseException:
        pass
    await _cancel_pending_telethon_tasks()


async def shield_close_client(client: TelegramClient) -> None:
    close_task = asyncio.create_task(close_client(client))
    try:
        await asyncio.shield(close_task)
    except asyncio.CancelledError:
        try:
            await asyncio.wait_for(asyncio.shield(close_task), timeout=6)
        except BaseException:
            pass
        raise


@dataclass
class VideoMeta:
    message_id: int
    channel: str
    date_utc: str
    caption: str
    tags: list[str]
    title: str
    description: str
    file_name: str
    file_size: Optional[int]
    mime_type: Optional[str]
    duration: Optional[int]
    local_path: str
    cover_files: list[str]
    extra_images: list[str] = field(default_factory=list)


@dataclass
class VideoPreview:
    message_id: int
    channel: str
    date_utc: str
    caption: str
    tags: list[str]
    file_name: str
    file_size: Optional[int]
    mime_type: Optional[str]
    duration: Optional[int]
    grouped_id: Optional[int]
    preview_image: Optional[str] = None
    cover_image: Optional[str] = None
    video_path: Optional[str] = None
    extra_images: list[str] = field(default_factory=list)


def extract_tags(text: str) -> list[str]:
    if not text:
        return []
    return TAG_PATTERN.findall(text)


def _normalize_filter_text(text: str) -> str:
    return AD_TEXT_STRIP_PATTERN.sub("", (text or "").lower())


def message_caption(message) -> str:
    for attr in ("text", "message", "raw_text"):
        value = getattr(message, attr, None)
        if value:
            return str(value)
    return ""


def _detect_image_extension(path: Path) -> str:
    try:
        data = path.read_bytes()[:16]
    except OSError:
        return ""
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return ".gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return ".webp"
    return ""


def _is_valid_image_file(path: Path) -> bool:
    try:
        return path.exists() and path.stat().st_size > 0 and bool(_detect_image_extension(path))
    except OSError:
        return False


def _rename_image_to_detected_extension(path: Path) -> Path:
    suffix = _detect_image_extension(path)
    if not suffix:
        return path
    if path.suffix.lower() == suffix:
        return path
    target = path.with_suffix(suffix)
    try:
        if target.exists():
            target.unlink()
        path.rename(target)
        return target
    except OSError:
        return path


def is_filtered_caption(text: str) -> bool:
    normalized = _normalize_filter_text(text)
    if not normalized:
        return False
    strong_keywords = (
        "2028体育",
        "tg全网最大信誉台",
        "全网最大信誉台",
        "南宫娱乐千万押金首选品牌",
    )
    if any(keyword in normalized for keyword in strong_keywords):
        return True
    keyword_groups = (
        ("玩家首选", "千万秒出"),
        ("绿茵盛宴", "资金流动速度"),
        ("信誉台", "千万秒出"),
        ("u投首选综合平台", "东南亚盘总首选权威"),
    )
    return any(all(keyword in normalized for keyword in group) for group in keyword_groups)


def safe_filename(name: str) -> str:
    sanitized = re.sub(r"[^\w\-. ]+", "_", name).strip()
    return sanitized or "video"


def _channel_slug(channel: str) -> str:
    raw = (channel or "").strip()
    if raw.startswith("http://") or raw.startswith("https://"):
        parts = [part for part in raw.split("/") if part]
        raw = parts[-1] if parts else raw
    if raw.startswith("@"):
        raw = raw[1:]
    raw = raw.replace("/", "_")
    slug = safe_filename(raw).replace(" ", "_")
    return (slug or "channel")[:50]


def pick_file_name(message, channel: str) -> str:
    timestamp = message.date.strftime("%Y%m%d_%H%M%S")
    slug = _channel_slug(channel)
    if message.file and message.file.name:
        original = Path(message.file.name)
        base = safe_filename(original.stem)[:60] or "video"
        ext = original.suffix or ".mp4"
    else:
        base = "video"
        ext = ".mp4"
    return f"{slug}_{message.id}_{timestamp}_{base}{ext}"


def ensure_output_dir(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)


def load_config(output_dir: Path) -> dict:
    config_path = output_dir / CONFIG_NAME
    if not config_path.exists():
        return {}
    return json.loads(config_path.read_text(encoding="utf-8"))


def save_config(output_dir: Path, config: dict) -> None:
    config_path = output_dir / CONFIG_NAME
    config_path.write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def get_api_credentials(output_dir: Path, allow_prompt: bool = True) -> tuple[str, str]:
    api_id = os.getenv("TELEGRAM_API_ID")
    api_hash = os.getenv("TELEGRAM_API_HASH")
    if api_id and api_hash:
        return api_id, api_hash

    config = load_config(output_dir)
    api_id = api_id or config.get("api_id")
    api_hash = api_hash or config.get("api_hash")

    if not allow_prompt or not sys.stdin.isatty():
        raise ValueError("缺少 API ID 或 API Hash，请在界面中填写。")

    if not api_id:
        try:
            api_id = input("Enter TELEGRAM_API_ID: ").strip()
        except EOFError as exc:
            raise ValueError("无法从终端读取 API ID，请在界面中填写。") from exc
    if not api_hash:
        try:
            api_hash = input("Enter TELEGRAM_API_HASH: ").strip()
        except EOFError as exc:
            raise ValueError("无法从终端读取 API Hash，请在界面中填写。") from exc

    if not api_id or not api_hash:
        raise SystemExit("Missing TELEGRAM_API_ID or TELEGRAM_API_HASH.")

    config["api_id"] = api_id
    config["api_hash"] = api_hash
    save_config(output_dir, config)
    return api_id, api_hash


def load_manifest_ids(output_dir: Path) -> set[int]:
    manifest_path = output_dir / MANIFEST_NAME
    if not manifest_path.exists():
        return set()
    ids: set[int] = set()
    stale_ids: list[int] = []
    with manifest_path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            message_id = row.get("message_id")
            if not (message_id and message_id.isdigit()):
                continue
            message_int = int(message_id)
            file_size = row.get("file_size")
            try:
                expected_size = int(file_size) if file_size else 0
            except ValueError:
                expected_size = 0
            local_path = row.get("local_path") or ""
            file_name = row.get("file_name") or ""
            file_path: Optional[Path] = None
            if local_path:
                file_path = Path(local_path)
                if not file_path.is_absolute():
                    file_path = output_dir / file_path
            elif file_name:
                file_path = output_dir / file_name
            if file_path and file_path.exists():
                actual_size = file_path.stat().st_size
                if not expected_size or actual_size >= expected_size * 0.98:
                    ids.add(message_int)
                    continue
            stale_ids.append(message_int)
    if stale_ids:
        for message_id in stale_ids:
            remove_manifest_entry(output_dir, message_id)
    return ids


def append_manifest(output_dir: Path, rows: Iterable[VideoMeta]) -> None:
    manifest_path = output_dir / MANIFEST_NAME
    file_exists = manifest_path.exists()
    with manifest_path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        if not file_exists:
            writer.writerow(
                [
                    "message_id",
                    "channel",
                    "date_utc",
                    "caption",
                    "tags",
                    "file_name",
                    "file_size",
                    "mime_type",
                    "local_path",
                ]
            )
        for meta in rows:
            writer.writerow(
                [
                    meta.message_id,
                    meta.channel,
                    meta.date_utc,
                    meta.caption,
                    "|".join(meta.tags),
                    meta.file_name,
                    meta.file_size,
                    meta.mime_type,
                    meta.local_path,
                ]
            )


def remove_manifest_entry(output_dir: Path, message_id: int) -> None:
    manifest_path = output_dir / MANIFEST_NAME
    if not manifest_path.exists():
        return
    with manifest_path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = [row for row in reader if row.get("message_id") != str(message_id)]
        fieldnames = reader.fieldnames or []
    with manifest_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if fieldnames:
            writer.writeheader()
        writer.writerows(rows)
def read_manifest(output_dir: Path) -> list[dict[str, str]]:
    manifest_path = output_dir / MANIFEST_NAME
    if not manifest_path.exists():
        return []
    with manifest_path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return list(reader)


def _extract_duration(message) -> Optional[int]:
    if message.video and getattr(message.video, "duration", None) is not None:
        return message.video.duration
    if message.document:
        for attr in message.document.attributes or []:
            if isinstance(attr, DocumentAttributeVideo):
                return attr.duration
    return None


def build_meta(
    message,
    target_path: Path,
    caption: str,
    tags: list[str],
    covers: list[str],
    extra_images: Optional[list[str]] = None,
) -> VideoMeta:
    file_name = target_path.name
    title = message.file.name if message.file and message.file.name else file_name
    duration = _extract_duration(message)
    return VideoMeta(
        message_id=message.id,
        channel="",
        date_utc=message.date.astimezone(timezone.utc).replace(tzinfo=None).isoformat()
        + "Z",
        caption=caption,
        tags=tags,
        title=title,
        description=caption,
        file_name=file_name,
        file_size=message.file.size if message.file else None,
        mime_type=message.file.mime_type if message.file else None,
        duration=duration,
        local_path=str(target_path),
        cover_files=covers,
        extra_images=extra_images or [],
    )


def write_meta(output_dir: Path, meta: VideoMeta, target_path: Path) -> None:
    meta_path = output_dir / f"{target_path.stem}.json"
    meta_path.write_text(
        json.dumps(meta.__dict__, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


async def download_thumbnails(message, output_dir: Path, stem: str) -> list[str]:
    document = getattr(getattr(message, "media", None), "document", None)
    thumbs = getattr(document, "thumbs", None) or []
    if not thumbs:
        return []
    covers: list[str] = []
    for idx, thumb in enumerate(thumbs, start=1):
        target = output_dir / f"{stem}_thumb_{idx}.jpg"
        try:
            await message.download_media(file=target, thumb=thumb)
        except Exception:
            continue
        if target.exists():
            covers.append(target.name)
    return covers


async def download_with_iter(
    client: TelegramClient,
    message,
    target_path: Path,
    progress_cb: Optional[Callable[[int, Optional[int]], None]] = None,
    status_cb: Optional[Callable[[str], None]] = None,
    expected_size: Optional[int] = None,
    request_size: int = 1024 * 128,
    timeout_sec: int = DEFAULT_DOWNLOAD_TIMEOUT_SEC,
    pause_cb: Optional[Callable[[], bool]] = None,
) -> None:
    media = getattr(message, "media", None) or getattr(message, "document", None)
    if not media:
        raise RuntimeError("媒体为空")
    downloaded = 0
    offset = 0
    if target_path.exists():
        downloaded = target_path.stat().st_size
        if expected_size and downloaded >= expected_size * 0.98:
            if progress_cb:
                progress_cb(downloaded, expected_size)
            return
        if expected_size and downloaded > expected_size * 1.02:
            target_path.unlink()
            downloaded = 0
        else:
            offset = downloaded
    last_log = time.monotonic()
    log_interval = 30.0
    if progress_cb and downloaded:
        progress_cb(downloaded, expected_size)
    mode = "ab" if offset else "wb"
    with target_path.open(mode) as handle:
        aiter = client.iter_download(
            media, request_size=request_size, offset=offset
        ).__aiter__()
        while True:
            if pause_cb and pause_cb():
                raise RuntimeError("paused")
            try:
                chunk = await asyncio.wait_for(
                    aiter.__anext__(), timeout=timeout_sec
                )
            except StopAsyncIteration:
                break
            except asyncio.TimeoutError:
                if status_cb:
                    status_cb(f"分片下载无进度：{target_path.name}")
                raise
            if not chunk:
                continue
            handle.write(chunk)
            downloaded += len(chunk)
            if progress_cb:
                progress_cb(downloaded, expected_size)
            if status_cb and time.monotonic() - last_log >= log_interval:
                mb = downloaded / 1024 / 1024
                status_cb(f"分片下载中：{target_path.name} 已下载 {mb:.2f}MB")
                last_log = time.monotonic()
    if expected_size and downloaded < expected_size * 0.98:
        raise RuntimeError(f"文件不完整 {downloaded}/{int(expected_size)}")
    if downloaded == 0:
        raise RuntimeError("文件大小为 0，可能文件不可用或权限受限")


def _is_incomplete_or_empty_error(exc: BaseException) -> bool:
    msg = str(exc)
    return any(
        k in msg for k in ("文件不完整", "文件大小为 0", "download incomplete", "download empty")
    )


async def download_with_retry(
    message,
    target_path: Path,
    attempts: int = 3,
    progress_cb: Optional[Callable[[int, Optional[int]], None]] = None,
    status_cb: Optional[Callable[[str], None]] = None,
    file_label: str = "",
    timeout_sec: int = DEFAULT_DOWNLOAD_TIMEOUT_SEC,
    expected_size: Optional[int] = None,
    refresh_cb: Optional[Callable[[], Awaitable[Optional[object]]]] = None,
    stream_fallback: Optional[Callable[[], Awaitable[None]]] = None,
    pause_cb: Optional[Callable[[], bool]] = None,
) -> None:
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            if pause_cb and pause_cb():
                raise RuntimeError("paused")
            if refresh_cb:
                try:
                    refreshed = await refresh_cb()
                    if refreshed is not None:
                        message = refreshed
                except Exception:
                    pass
            last_progress = time.monotonic()
            use_part_size = True
            last_bytes = 0
            last_total: Optional[int] = None
            last_report = time.monotonic()
            last_log = time.monotonic()
            report_interval = 5.0
            log_interval = 30.0

            def _wrapped_progress(current: int, total_bytes: Optional[int]) -> None:
                nonlocal last_progress, last_bytes, last_total
                if current > last_bytes:
                    last_bytes = current
                    last_progress = time.monotonic()
                if total_bytes is not None:
                    last_total = total_bytes
                if progress_cb:
                    progress_cb(current, total_bytes)

            def _start_task() -> asyncio.Task:
                if use_part_size:
                    return asyncio.create_task(
                        message.download_media(
                            file=target_path,
                            progress_callback=_wrapped_progress,
                            part_size_kb=_get_part_size_kb(),
                        )
                    )
                return asyncio.create_task(
                    message.download_media(
                        file=target_path,
                        progress_callback=_wrapped_progress,
                    )
                )

            download_task = _start_task()

            while True:
                if pause_cb and pause_cb():
                    download_task.cancel()
                    try:
                        await download_task
                    except asyncio.CancelledError:
                        pass
                    except Exception:
                        pass
                    raise RuntimeError("paused")
                try:
                    await asyncio.wait_for(download_task, timeout=1.0)
                    break
                except asyncio.CancelledError as exc:
                    last_error = exc
                    break
                except TypeError:
                    if use_part_size:
                        use_part_size = False
                        try:
                            download_task.cancel()
                            await download_task
                        except asyncio.CancelledError:
                            pass
                        except Exception:
                            pass
                        download_task = _start_task()
                        last_progress = time.monotonic()
                        continue
                    raise
                except asyncio.TimeoutError:
                    now = time.monotonic()
                    if (
                        progress_cb
                        and now - last_report >= report_interval
                        and last_bytes >= 0
                    ):
                        progress_cb(last_bytes, last_total)
                        last_report = now
                    if (
                        status_cb
                        and file_label
                        and now - last_progress >= log_interval
                        and now - last_log >= log_interval
                    ):
                        status_cb(f"下载无进度：{file_label}")
                        last_log = now
                    if time.monotonic() - last_progress > timeout_sec:
                        download_task.cancel()
                        try:
                            await download_task
                        except asyncio.CancelledError:
                            pass
                        except Exception:
                            pass
                        raise asyncio.TimeoutError()
                except RPCError as exc:
                    last_error = exc
                    if status_cb and file_label:
                        status_cb(f"下载失败：{file_label} Telegram错误: {exc}")
                    raise
            final_expected = expected_size or last_total
            if final_expected and target_path.exists():
                actual_size = target_path.stat().st_size
                if actual_size < final_expected * 0.98:
                    if actual_size == 0:
                        try:
                            target_path.unlink()
                        except Exception:
                            pass
                    raise RuntimeError(
                        f"文件不完整 {actual_size}/{int(final_expected)}"
                    )
            if target_path.exists() and target_path.stat().st_size == 0:
                try:
                    target_path.unlink()
                except Exception:
                    pass
                raise RuntimeError("文件大小为 0，可能文件不可用或权限受限")
            return
        except asyncio.TimeoutError as exc:
            last_error = exc
            if status_cb and file_label:
                status_cb(f"下载超时：{file_label}，重试中({attempt}/{attempts})")
            if attempt < attempts:
                await asyncio.sleep(2 * attempt)
                continue
            break
        except asyncio.CancelledError as exc:
            last_error = exc
            break
        except RuntimeError as exc:
            last_error = exc
            if str(exc) == "paused":
                raise
            if stream_fallback and _is_incomplete_or_empty_error(exc):
                if status_cb and file_label:
                    status_cb(f"下载不完整，改用分片下载：{file_label}")
                try:
                    await stream_fallback()
                    return
                except asyncio.TimeoutError as fallback_err:
                    last_error = fallback_err
                    if status_cb and file_label:
                        status_cb(
                            f"分片下载超时：{file_label}，重试中({attempt}/{attempts})"
                        )
                    if attempt < attempts:
                        await asyncio.sleep(2 * attempt)
                        continue
                    raise last_error
                except Exception as fallback_err:
                    last_error = fallback_err
                    if status_cb and file_label:
                        status_cb(f"分片下载失败：{file_label} {fallback_err}")
                    raise last_error
            if status_cb and file_label:
                status_cb(f"下载失败：{file_label} {exc}，重试中({attempt}/{attempts})")
            await asyncio.sleep(2 * attempt)
            continue
        except RPCError as exc:
            last_error = exc
            await asyncio.sleep(2 * attempt)
    if last_error:
        if isinstance(last_error, asyncio.CancelledError):
            raise RuntimeError("download cancelled")
        raise last_error


def _default_input(prompt: str) -> str:
    if not sys.stdin.isatty():
        raise ValueError("无法从终端读取输入，请在界面中完成登录。")
    try:
        return input(prompt).strip()
    except EOFError as exc:
        raise ValueError("无法从终端读取输入，请在界面中完成登录。") from exc


async def ensure_authorized(
    client: TelegramClient,
    get_phone_cb: Optional[Callable[[], str]] = None,
    get_code_cb: Optional[Callable[[], str]] = None,
    get_password_cb: Optional[Callable[[], str]] = None,
    status_cb: Optional[Callable[[str], None]] = None,
) -> None:
    if await client.is_user_authorized():
        if status_cb:
            status_cb("已登录")
        return

    get_phone = get_phone_cb or (lambda: _default_input("Enter phone number: "))
    get_code = get_code_cb or (lambda: _default_input("Enter login code: "))
    get_password = get_password_cb or (lambda: _default_input("Enter 2FA password: "))

    if status_cb:
        status_cb("等待输入手机号...")
    phone = get_phone()
    if not phone:
        raise ValueError("未输入手机号。")

    if status_cb:
        status_cb("正在发送验证码...")
    await client.send_code_request(phone)

    if status_cb:
        status_cb("等待输入验证码...")
    code = get_code()
    if not code:
        raise ValueError("未输入验证码。")

    try:
        await client.sign_in(phone=phone, code=code)
    except SessionPasswordNeededError:
        if status_cb:
            status_cb("等待输入两步验证密码...")
        password = get_password()
        if not password:
            raise ValueError("未输入两步验证密码。")
        await client.sign_in(password=password)
    if status_cb:
        status_cb("已登录")


def build_client(
    api_id: str,
    api_hash: str,
    output_dir: Path,
    loop: Optional[asyncio.AbstractEventLoop] = None,
    session_path: Optional[Path] = None,
) -> TelegramClient:
    if loop is None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            else:
                if loop.is_closed():
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
    session_base = str(session_path or (output_dir / "user_session"))
    return TelegramClient(
        session_base,
        int(api_id),
        api_hash,
        loop=loop,
        connection_retries=5,
        retry_delay=2,
        timeout=20,
        auto_reconnect=True,
    )


async def download_videos(
    channel: str,
    max_videos: int,
    output_dir: Path,
    api_id: str,
    api_hash: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    allowed_ids: Optional[set[int]] = None,
    skip_cb: Optional[Callable[[int], bool]] = None,
    pause_cb: Optional[Callable[[int], bool]] = None,
    status_cb: Optional[Callable[[str], None]] = None,
    progress_cb: Optional[Callable[[dict], None]] = None,
    pause_event: Optional[threading.Event] = None,
    stop_event: Optional[threading.Event] = None,
    get_phone_cb: Optional[Callable[[], str]] = None,
    get_code_cb: Optional[Callable[[], str]] = None,
    get_password_cb: Optional[Callable[[], str]] = None,
) -> int:
    ensure_output_dir(output_dir)
    downloaded_ids = load_manifest_ids(output_dir)
    count = 0
    remaining_ids = set(allowed_ids) if allowed_ids else None
    if remaining_ids and remaining_ids.issubset(downloaded_ids):
        if status_cb:
            for msg_id in sorted(remaining_ids):
                status_cb(f"已存在，跳过：{msg_id}")
        return count
    if status_cb:
        status_cb("连接中...")

    def should_stop() -> bool:
        return stop_event.is_set() if stop_event else False

    async def wait_if_paused() -> None:
        if not pause_event:
            return
        while pause_event.is_set():
            await asyncio.sleep(0.3)

    paused_logged: set[int] = set()

    async def wait_if_paused_message(message_id: int, label: str) -> None:
        if not pause_cb:
            return
        if pause_cb(message_id):
            if message_id not in paused_logged and status_cb:
                status_cb(f"已暂停：{label}")
            paused_logged.add(message_id)
            while pause_cb(message_id):
                await asyncio.sleep(1.0)
            if message_id in paused_logged and status_cb:
                status_cb(f"继续下载：{label}")
            paused_logged.discard(message_id)

    def in_date_range(message_date: datetime) -> bool:
        local_date = message_date.astimezone().date()
        if start_date and local_date < start_date:
            return False
        if end_date and local_date > end_date:
            return False
        return True

    def is_image_message(msg) -> bool:
        if msg.photo:
            return True
        if msg.document and getattr(msg.document, "mime_type", ""):
            return msg.document.mime_type.startswith("image/")
        return False

    def _image_ext(msg) -> str:
        mime = ""
        if msg.document:
            mime = getattr(msg.document, "mime_type", "") or ""
        if "png" in mime:
            return "png"
        if "webp" in mime:
            return "webp"
        if "jpeg" in mime or "jpg" in mime:
            return "jpg"
        return "jpg"

    async def download_group_images(
        group_messages, stem: str
    ) -> list[str]:
        images: list[str] = []
        if not group_messages:
            return images
        for msg in group_messages:
            if not is_image_message(msg):
                continue
            ext = _image_ext(msg)
            target = output_dir / f"{stem}_img_{msg.id}.{ext}"
            if not target.exists():
                try:
                    await msg.download_media(file=str(target))
                except Exception:
                    continue
            if target.exists():
                images.append(target.name)
        return images

    client = build_client(api_id, api_hash, output_dir)
    await client.connect()
    try:
        await ensure_authorized(
            client,
            get_phone_cb=get_phone_cb,
            get_code_cb=get_code_cb,
            get_password_cb=get_password_cb,
            status_cb=status_cb,
        )
        if status_cb:
            status_cb("正在获取频道消息...")
        messages = client.iter_messages(channel, limit=None)
        to_download = []
        async for message in messages:
            if len(to_download) >= max_videos:
                break

            if not message.video and not (
                message.document
                and message.document.mime_type
                and message.document.mime_type.startswith("video/")
            ):
                continue

            if not in_date_range(message.date):
                continue

            if skip_cb and skip_cb(message.id):
                if status_cb:
                    status_cb(f"跳过已移除：{message.id}")
                continue

            if remaining_ids is not None and message.id not in remaining_ids:
                continue
            if remaining_ids is not None and message.id in remaining_ids:
                remaining_ids.discard(message.id)

            if message.id in downloaded_ids:
                if status_cb:
                    status_cb(f"已存在，跳过：{message.id}")
                continue

            to_download.append(message)
            if remaining_ids is not None and not remaining_ids:
                break

        total = len(to_download)
        if status_cb:
            status_cb(f"待下载视频：{total}")

        async def handle_message(index: int, message) -> None:
            nonlocal count
            if should_stop():
                return
            if skip_cb and skip_cb(message.id):
                if status_cb:
                    status_cb(f"跳过已移除：{message.id}")
                return
            if allowed_ids is not None and message.id not in allowed_ids:
                if status_cb:
                    status_cb(f"跳过已移除：{message.id}")
                return

            await wait_if_paused()

            try:
                refreshed = await client.get_messages(channel, ids=message.id)
                if refreshed:
                    message = refreshed
            except Exception:
                pass
            caption = message_caption(message)
            group_messages = None
            if message.grouped_id is not None:
                group_messages = []
                scan_min = max(1, message.id - 200)
                scan_max = message.id + 200
                ids = list(range(scan_min, scan_max + 1))
                fetched = []
                chunk_size = 100
                for i in range(0, len(ids), chunk_size):
                    chunk = ids[i : i + chunk_size]
                    try:
                        batch = await client.get_messages(channel, ids=chunk)
                    except Exception:
                        batch = []
                    fetched.extend(batch)
                for msg in fetched:
                    if msg is None:
                        continue
                    if msg.grouped_id == message.grouped_id:
                        group_messages.append(msg)
                if not group_messages:
                    # Fallback: scan nearby messages in time order
                    async for msg in client.iter_messages(
                        channel, offset_id=message.id + 1, limit=200
                    ):
                        if msg.grouped_id == message.grouped_id:
                            group_messages.append(msg)
                        elif group_messages:
                            break
            elif message.reply_to and getattr(message.reply_to, "reply_to_msg_id", None):
                try:
                    parent = await client.get_messages(
                        channel, ids=message.reply_to.reply_to_msg_id
                    )
                except Exception:
                    parent = None
                if parent and parent.grouped_id is not None:
                    group_messages = []
                    async for msg in client.iter_messages(
                        channel, offset_id=parent.id + 1, limit=200
                    ):
                        if msg.grouped_id == parent.grouped_id:
                            group_messages.append(msg)
                        elif group_messages:
                            break
                if not caption:
                    for msg in group_messages:
                        msg_caption = message_caption(msg)
                        if msg_caption:
                            caption = msg_caption
                            break
            tags = extract_tags(caption)
            if is_filtered_caption(caption):
                if status_cb:
                    status_cb(f"简介命中过滤规则，跳过：{message.id}")
                return
            file_name = pick_file_name(message, channel)
            target_path = output_dir / file_name
            temp_path = target_path.with_suffix(target_path.suffix + ".part")

            expected_size = message.file.size if message.file else None

            if status_cb:
                document = getattr(message, "document", None) or getattr(
                    getattr(message, "media", None), "document", None
                )
                if document:
                    status_cb(
                        "媒体信息: id=%s size=%s dc=%s mime=%s"
                        % (
                            getattr(document, "id", None),
                            getattr(document, "size", None),
                            getattr(document, "dc_id", None),
                            getattr(document, "mime_type", None),
                        )
                    )
                else:
                    status_cb("媒体信息: 为空")

            if target_path.exists():
                if expected_size and target_path.stat().st_size == expected_size:
                    covers = await download_thumbnails(
                        message, output_dir, target_path.stem
                    )
                    extra_images = await download_group_images(
                        group_messages, target_path.stem
                    )
                    meta = build_meta(
                        message, target_path, caption, tags, covers, extra_images
                    )
                    meta.channel = channel
                    async with write_lock:
                        write_meta(output_dir, meta, target_path)
                        append_manifest(output_dir, [meta])
                        downloaded_ids.add(message.id)
                    if progress_cb:
                        progress_cb(
                            {
                                "current_index": index,
                                "total": total,
                                "file_name": target_path.name,
                                "message_id": message.id,
                                "bytes_downloaded": target_path.stat().st_size,
                                "bytes_total": target_path.stat().st_size,
                                "speed_bps": None,
                            }
                        )
                    if status_cb:
                        status_cb(f"已记录现有文件：{target_path.name}")
                    return
                target_path.unlink()

            if temp_path.exists() and temp_path.stat().st_size == 0:
                temp_path.unlink()

            if status_cb:
                status_cb(f"下载中：{target_path.name}")

            last_time = time.monotonic()
            last_bytes = 0

            def _progress(current: int, total_bytes: Optional[int]) -> None:
                nonlocal last_time, last_bytes
                now = time.monotonic()
                elapsed = now - last_time
                speed = None
                if elapsed > 0:
                    speed = (current - last_bytes) / elapsed
                last_time = now
                last_bytes = current
                if progress_cb:
                    progress_cb(
                        {
                            "current_index": index,
                            "total": total,
                            "file_name": target_path.name,
                            "message_id": message.id,
                            "bytes_downloaded": current,
                            "bytes_total": total_bytes,
                            "speed_bps": speed,
                        }
                    )

            async def _stream_fallback() -> None:
                if status_cb:
                    status_cb(f"分片下载中：{target_path.name}")
                refreshed = await client.get_messages(channel, ids=message.id)
                if isinstance(refreshed, (list, tuple)):
                    msg = refreshed[0] if refreshed else message
                else:
                    msg = refreshed or message
                await download_with_iter(
                    client,
                    msg,
                    temp_path,
                    progress_cb=_progress,
                    status_cb=status_cb,
                    expected_size=expected_size,
                    timeout_sec=DEFAULT_DOWNLOAD_TIMEOUT_SEC,
                    pause_cb=(
                        (lambda: pause_cb(message.id)) if pause_cb else None
                    ),
                )

            while True:
                if should_stop():
                    return
                await wait_if_paused_message(message.id, target_path.name)
                try:
                    if temp_path.exists() and temp_path.stat().st_size > 0:
                        if status_cb:
                            status_cb(f"断点续传中：{target_path.name}")
                        await download_with_iter(
                            client,
                            message,
                            temp_path,
                            progress_cb=_progress,
                            status_cb=status_cb,
                            expected_size=expected_size,
                            timeout_sec=DEFAULT_DOWNLOAD_TIMEOUT_SEC,
                            pause_cb=(
                                (lambda: pause_cb(message.id)) if pause_cb else None
                            ),
                        )
                    else:
                        await download_with_retry(
                            message,
                            temp_path,
                            progress_cb=_progress,
                            status_cb=status_cb,
                            file_label=target_path.name,
                            expected_size=expected_size,
                            refresh_cb=lambda: client.get_messages(
                                channel, ids=message.id
                            ),
                            stream_fallback=_stream_fallback,
                            pause_cb=(
                                (lambda: pause_cb(message.id)) if pause_cb else None
                            ),
                        )
                    temp_path.replace(target_path)
                    break
                except Exception as exc:
                    if str(exc) == "paused":
                        await wait_if_paused_message(message.id, target_path.name)
                        continue
                    reason = (
                        "超时" if isinstance(exc, asyncio.TimeoutError) else str(exc)
                    )
                    if status_cb:
                        status_cb(f"下载失败：{message.id} {reason}")
                    if temp_path.exists():
                        try:
                            temp_path.unlink()
                        except Exception:
                            pass
                    return

            covers = await download_thumbnails(message, output_dir, target_path.stem)
            extra_images = await download_group_images(
                group_messages, target_path.stem
            )
            meta = build_meta(message, target_path, caption, tags, covers, extra_images)
            meta.channel = channel
            async with write_lock:
                write_meta(output_dir, meta, target_path)
                append_manifest(output_dir, [meta])
                downloaded_ids.add(message.id)
                count += 1

            if progress_cb:
                final_size = target_path.stat().st_size
                progress_cb(
                    {
                        "current_index": index,
                        "total": total,
                        "file_name": target_path.name,
                        "message_id": message.id,
                        "bytes_downloaded": final_size,
                        "bytes_total": final_size,
                        "speed_bps": None,
                    }
                )

            if status_cb:
                status_cb(f"完成：{target_path.name}")

            await asyncio.sleep(1)

        write_lock = asyncio.Lock()
        concurrency = _get_concurrency()
        if concurrency <= 1:
            for index, message in enumerate(to_download, start=1):
                if should_stop():
                    if status_cb:
                        status_cb("已停止")
                    break
                await handle_message(index, message)
        else:
            semaphore = asyncio.Semaphore(concurrency)

            async def runner(index: int, message) -> None:
                async with semaphore:
                    await handle_message(index, message)

            await asyncio.gather(
                *(runner(index, msg) for index, msg in enumerate(to_download, start=1))
            )
    finally:
        await shield_close_client(client)

    return count


async def list_videos(
    channel: str,
    output_dir: Path,
    api_id: str,
    api_hash: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    status_cb: Optional[Callable[[str], None]] = None,
    pause_event: Optional[threading.Event] = None,
    stop_event: Optional[threading.Event] = None,
    limit: Optional[int] = None,
    offset: int = 0,
    offset_id: Optional[int] = None,
    max_scan_messages: Optional[int] = None,
    return_scan_limited: bool = False,
    deadline_monotonic: Optional[float] = None,
    preview_media_timeout: float = 8,
    nearby_lookup_timeout: float = 5,
    max_extra_images: int = 3,
    max_thumb_attempts: int = 4,
    preview_thumb_total_timeout: float = 3,
    allow_nearby_extra_images: bool = True,
    get_phone_cb: Optional[Callable[[], str]] = None,
    get_code_cb: Optional[Callable[[], str]] = None,
    get_password_cb: Optional[Callable[[], str]] = None,
    client: Optional[TelegramClient] = None,
) -> tuple[list[VideoPreview], Optional[int]] | tuple[list[VideoPreview], Optional[int], bool]:
    ensure_output_dir(output_dir)
    previews: list[VideoPreview] = []
    preview_dir = output_dir / "preview_cache"
    ensure_output_dir(preview_dir)
    if status_cb:
        status_cb("连接中...")

    def should_stop() -> bool:
        return stop_event.is_set() if stop_event else False

    def remaining_timeout(default_timeout: float) -> Optional[float]:
        if deadline_monotonic is None:
            return default_timeout
        remaining = deadline_monotonic - time.monotonic()
        if remaining <= 0:
            return 0
        return max(0.1, min(default_timeout, remaining))

    def deadline_expired() -> bool:
        return deadline_monotonic is not None and time.monotonic() >= deadline_monotonic

    async def wait_if_paused() -> None:
        if not pause_event:
            return
        while pause_event.is_set():
            await asyncio.sleep(0.3)

    def in_date_range(message_date: datetime) -> bool:
        local_date = message_date.astimezone().date()
        if start_date and local_date < start_date:
            return False
        if end_date and local_date > end_date:
            return False
        return True

    async def download_thumb(message, filename: str, thumb_index: int) -> Optional[Path]:
        target = preview_dir / filename
        if target.exists():
            renamed = _rename_image_to_detected_extension(target)
            if _is_valid_image_file(renamed):
                return renamed
            try:
                renamed.unlink()
            except OSError:
                pass
        timeout = remaining_timeout(preview_media_timeout)
        if timeout is not None and timeout <= 0:
            return None
        download_task = _track_preview_media_task(asyncio.create_task(
            client.download_media(
                message,
                file=str(target),
                thumb=thumb_index,
            )
        ))
        try:
            result = await asyncio.wait_for(
                asyncio.shield(download_task),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            return None
        except Exception:
            return None
        if not result:
            return None
        result_path = _rename_image_to_detected_extension(Path(result))
        if not _is_valid_image_file(result_path):
            try:
                result_path.unlink()
            except OSError:
                pass
            return None
        return result_path

    async def download_image(message, filename: str) -> Optional[Path]:
        target = preview_dir / filename
        if target.exists():
            renamed = _rename_image_to_detected_extension(target)
            if _is_valid_image_file(renamed):
                return renamed
            try:
                renamed.unlink()
            except OSError:
                pass
        timeout = remaining_timeout(preview_media_timeout)
        if timeout is not None and timeout <= 0:
            return None
        download_task = _track_preview_media_task(
            asyncio.create_task(client.download_media(message, file=str(target)))
        )
        try:
            result = await asyncio.wait_for(
                asyncio.shield(download_task),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            return None
        except Exception:
            return None
        if not result:
            return None
        result_path = _rename_image_to_detected_extension(Path(result))
        if not _is_valid_image_file(result_path):
            try:
                result_path.unlink()
            except OSError:
                pass
            return None
        return result_path

    def is_image_message(msg) -> bool:
        if msg.photo:
            return True
        if msg.document and getattr(msg.document, "mime_type", ""):
            return msg.document.mime_type.startswith("image/")
        return False

    owns_client = client is None
    if client is None:
        client = build_client(api_id, api_hash, output_dir)
    if not client.is_connected():
        await client.connect()
    try:
        await ensure_authorized(
            client,
            get_phone_cb=get_phone_cb,
            get_code_cb=get_code_cb,
            get_password_cb=get_password_cb,
            status_cb=status_cb,
        )
        if status_cb:
            status_cb("正在扫描频道视频...")
        if offset_id:
            messages = client.iter_messages(channel, limit=None, offset_id=offset_id)
        else:
            messages = client.iter_messages(channel, limit=None)
        skipped = 0
        scanned = 0
        scan_limited = False
        last_seen_id: Optional[int] = None
        aiter = messages.__aiter__()
        while True:
            timeout = remaining_timeout(4)
            if timeout is not None and timeout <= 0:
                scan_limited = True
                break
            try:
                message = await asyncio.wait_for(aiter.__anext__(), timeout=timeout)
            except StopAsyncIteration:
                break
            except asyncio.TimeoutError:
                scan_limited = True
                break
            last_seen_id = message.id
            scanned += 1
            if deadline_expired():
                scan_limited = True
                break
            if should_stop():
                if status_cb:
                    status_cb("已停止")
                break
            await wait_if_paused()

            if limit and len(previews) >= limit:
                break
            if max_scan_messages and scanned > max_scan_messages:
                scan_limited = True
                break

            if not message.video and not (
                message.document
                and message.document.mime_type
                and message.document.mime_type.startswith("video/")
            ):
                continue

            if not in_date_range(message.date):
                continue

            caption = message_caption(message)
            group_messages = None
            if message.grouped_id:
                group_messages = []
                try:
                    async for msg in client.iter_messages(
                        channel,
                        min_id=max(0, message.id - 30),
                        max_id=message.id + 30,
                    ):
                        if msg.grouped_id == message.grouped_id:
                            group_messages.append(msg)
                except Exception:
                    group_messages = []
                if not caption:
                    for msg in group_messages:
                        msg_caption = message_caption(msg)
                        if msg_caption:
                            caption = msg_caption
                            break
            if not caption and not deadline_expired():
                nearby_ids = list(range(max(1, message.id - 3), message.id + 4))
                timeout = remaining_timeout(0.8)
                try:
                    nearby_messages = await asyncio.wait_for(
                        client.get_messages(channel, ids=nearby_ids),
                        timeout=timeout,
                    )
                except Exception:
                    nearby_messages = []
                for msg in nearby_messages:
                    if not msg or msg.id == message.id:
                        continue
                    msg_caption = message_caption(msg)
                    if msg_caption and not is_filtered_caption(msg_caption):
                        caption = msg_caption
                        break
            tags = extract_tags(caption)
            if is_filtered_caption(caption):
                continue
            file_name = pick_file_name(message, channel)
            duration = None
            if message.video and getattr(message.video, "duration", None) is not None:
                duration = message.video.duration
            elif message.document:
                for attr in message.document.attributes or []:
                    if isinstance(attr, DocumentAttributeVideo):
                        duration = attr.duration
                        break
            if offset and skipped < offset:
                skipped += 1
                continue

            preview_path = None
            thumb_deadline = time.monotonic() + max(0.1, preview_thumb_total_timeout)
            thumb_indexes = (-1, 0, 1, 2)[: max(1, min(4, max_thumb_attempts))]
            for thumb_index in thumb_indexes:
                if time.monotonic() >= thumb_deadline:
                    break
                preview_path = await download_thumb(
                    message, f"{message.id}_preview_{thumb_index}.jpg", thumb_index
                )
                if preview_path:
                    break
            if deadline_expired():
                scan_limited = True
            extra_images: list[str] = []
            if max_extra_images <= 0:
                pass
            elif group_messages is not None:
                group_messages.sort(key=lambda m: m.id)
                for msg in group_messages:
                    if deadline_expired():
                        scan_limited = True
                        break
                    if not is_image_message(msg):
                        continue
                    img_path = await download_image(
                        msg, f"{message.id}_img_{msg.id}.jpg"
                    )
                    if not img_path:
                        continue
                    rel_img = img_path.relative_to(output_dir).as_posix()
                    if rel_img not in extra_images:
                        extra_images.append(rel_img)
                    if len(extra_images) >= max_extra_images:
                        break
            elif not deadline_expired() and is_image_message(message):
                img_path = await download_image(message, f"{message.id}_img.jpg")
                if img_path:
                    extra_images.append(img_path.relative_to(output_dir).as_posix())
            if allow_nearby_extra_images and not extra_images and not deadline_expired():
                # Fallback: scan nearby messages by time window
                nearby_ids = list(range(max(1, message.id - 10), message.id + 11))
                timeout = remaining_timeout(nearby_lookup_timeout)
                try:
                    nearby = await asyncio.wait_for(
                        client.get_messages(channel, ids=nearby_ids),
                        timeout=timeout,
                    )
                except Exception:
                    nearby = []
                for msg in nearby:
                    if deadline_expired():
                        scan_limited = True
                        break
                    if not msg or not is_image_message(msg):
                        continue
                    if abs((msg.date - message.date).total_seconds()) > 300:
                        continue
                    img_path = await download_image(
                        msg, f"{message.id}_img_{msg.id}.jpg"
                    )
                    if not img_path:
                        continue
                    rel_img = img_path.relative_to(output_dir).as_posix()
                    if rel_img not in extra_images:
                        extra_images.append(rel_img)
                    if len(extra_images) >= max_extra_images:
                        break
            local_video_path = output_dir / file_name
            video_path = (
                local_video_path.relative_to(output_dir).as_posix()
                if local_video_path.exists()
                else None
            )

            previews.append(
                VideoPreview(
                    message_id=message.id,
                    channel=channel,
                    date_utc=message.date.astimezone(timezone.utc)
                    .replace(tzinfo=None)
                    .isoformat()
                    + "Z",
                    caption=caption,
                    tags=tags,
                    file_name=file_name,
                    file_size=message.file.size if message.file else None,
                    mime_type=message.file.mime_type if message.file else None,
                    duration=duration,
                    grouped_id=message.grouped_id,
                    preview_image=preview_path.relative_to(output_dir).as_posix()
                    if preview_path
                    else None,
                    video_path=video_path,
                    extra_images=extra_images,
                )
            )
            if status_cb:
                status_cb(f"发现视频：{file_name}")
    finally:
        if owns_client:
            await shield_close_client(client)

    if return_scan_limited:
        return previews, last_seen_id, scan_limited
    return previews, last_seen_id


def run_download(
    channel: str,
    max_videos: int,
    output_dir: Path,
    api_id: Optional[str] = None,
    api_hash: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    allowed_ids: Optional[set[int]] = None,
    skip_cb: Optional[Callable[[int], bool]] = None,
    pause_cb: Optional[Callable[[int], bool]] = None,
    status_cb: Optional[Callable[[str], None]] = None,
    progress_cb: Optional[Callable[[dict], None]] = None,
    pause_event: Optional[threading.Event] = None,
    stop_event: Optional[threading.Event] = None,
    get_phone_cb: Optional[Callable[[], str]] = None,
    get_code_cb: Optional[Callable[[], str]] = None,
    get_password_cb: Optional[Callable[[], str]] = None,
    allow_prompt: bool = False,
) -> int:
    ensure_output_dir(output_dir)
    if not api_id or not api_hash:
        api_id, api_hash = get_api_credentials(output_dir, allow_prompt=allow_prompt)
    return asyncio.run(
        download_videos(
            channel=channel,
            max_videos=max_videos,
            output_dir=output_dir,
            api_id=api_id,
            api_hash=api_hash,
            start_date=start_date,
            end_date=end_date,
            allowed_ids=allowed_ids,
            skip_cb=skip_cb,
            pause_cb=pause_cb,
            status_cb=status_cb,
            progress_cb=progress_cb,
            pause_event=pause_event,
            stop_event=stop_event,
            get_phone_cb=get_phone_cb,
            get_code_cb=get_code_cb,
            get_password_cb=get_password_cb,
        )
    )


def run_list(
    channel: str,
    output_dir: Path,
    api_id: Optional[str] = None,
    api_hash: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    status_cb: Optional[Callable[[str], None]] = None,
    pause_event: Optional[threading.Event] = None,
    stop_event: Optional[threading.Event] = None,
    limit: Optional[int] = None,
    get_phone_cb: Optional[Callable[[], str]] = None,
    get_code_cb: Optional[Callable[[], str]] = None,
    get_password_cb: Optional[Callable[[], str]] = None,
    allow_prompt: bool = False,
) -> list[VideoPreview]:
    ensure_output_dir(output_dir)
    if not api_id or not api_hash:
        api_id, api_hash = get_api_credentials(output_dir, allow_prompt=allow_prompt)
    items, _ = asyncio.run(
        list_videos(
            channel=channel,
            output_dir=output_dir,
            api_id=api_id,
            api_hash=api_hash,
            start_date=start_date,
            end_date=end_date,
            status_cb=status_cb,
            pause_event=pause_event,
            stop_event=stop_event,
            limit=limit,
            get_phone_cb=get_phone_cb,
            get_code_cb=get_code_cb,
            get_password_cb=get_password_cb,
        )
    )
    return items


async def login_only(
    output_dir: Path,
    api_id: str,
    api_hash: str,
    status_cb: Optional[Callable[[str], None]] = None,
    get_phone_cb: Optional[Callable[[], str]] = None,
    get_code_cb: Optional[Callable[[], str]] = None,
    get_password_cb: Optional[Callable[[], str]] = None,
) -> None:
    ensure_output_dir(output_dir)
    if status_cb:
        status_cb("连接中...")
    client = build_client(api_id, api_hash, output_dir)
    await client.connect()
    try:
        await ensure_authorized(
            client,
            get_phone_cb=get_phone_cb,
            get_code_cb=get_code_cb,
            get_password_cb=get_password_cb,
            status_cb=status_cb,
        )
    finally:
        await shield_close_client(client)


def run_login(
    output_dir: Path,
    api_id: Optional[str] = None,
    api_hash: Optional[str] = None,
    status_cb: Optional[Callable[[str], None]] = None,
    get_phone_cb: Optional[Callable[[], str]] = None,
    get_code_cb: Optional[Callable[[], str]] = None,
    get_password_cb: Optional[Callable[[], str]] = None,
    allow_prompt: bool = False,
) -> None:
    ensure_output_dir(output_dir)
    if not api_id or not api_hash:
        api_id, api_hash = get_api_credentials(output_dir, allow_prompt=allow_prompt)
    asyncio.run(
        login_only(
            output_dir=output_dir,
            api_id=api_id,
            api_hash=api_hash,
            status_cb=status_cb,
            get_phone_cb=get_phone_cb,
            get_code_cb=get_code_cb,
            get_password_cb=get_password_cb,
        )
    )
