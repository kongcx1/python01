import json
import hashlib
import os
import queue
import re
import requests
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urlparse

import anyio
import asyncio
import sqlite3
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from telethon import TelegramClient, utils
from telethon.errors import FloodWaitError, RPCError, SessionPasswordNeededError, PhoneNumberInvalidError
from telethon.tl.functions.contacts import ResolveUsernameRequest
from pydantic import BaseModel, Field

from downloader_core import build_client, drain_preview_media_tasks, extract_tags, is_filtered_caption, list_videos, message_caption, pick_file_name, read_manifest, remove_manifest_entry, run_download
from server_upload import UploadClient


if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


STATE_DIR = Path(os.getenv("SERVER_STATE_DIR", "server_state"))
STATE_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = STATE_DIR / "tasks.db"
CONFIG_PATH = Path(os.getenv("SERVER_CONFIG", "server_config.json"))
WEB_DIR = Path(__file__).resolve().parent / "web_app"
DEFAULT_UPLOAD_BASE_URL = "https://userapi.sfthyf.cn"
DEFAULT_VIDEO_META_URL = "https://userapi.sfthyf.cn/api/short/create"
DEFAULT_MOVIE_CREATE_URL = "https://userapi.sfthyf.cn/api/movie/create"
DEFAULT_VIDEO_TYPE_THRESHOLD_SECONDS = 600
MIN_VIDEO_DURATION_SECONDS = int(os.getenv("MIN_VIDEO_DURATION_SECONDS", "10"))
DEFAULT_MAX_RUNNING_TASKS = 1
EXTERNAL_JSON_TASK_CONCURRENCY = 10
PREVIEW_SOFT_TIMEOUT_SECONDS = 18
PREVIEW_HARD_TIMEOUT_SECONDS = 24
AUTH_STATUS_TIMEOUT_SECONDS = 8
SPARK_MD5_HELPER = Path(__file__).resolve().parent / "tools" / "spark_md5_file.js"
SERVER_CODE_VERSION = "2026-07-23-cancel-status-final-v40"
_server_version_cache: Optional[str] = None
_db_init_lock = threading.Lock()
_db_initialized = False
_db_write_lock = threading.Lock()
DB_BUSY_TIMEOUT_MS = int(os.getenv("SERVER_DB_BUSY_TIMEOUT_MS", "60000"))
DB_WRITE_RETRIES = int(os.getenv("SERVER_DB_WRITE_RETRIES", "8"))
LOGIN_CODE_TTL_SECONDS = int(os.getenv("LOGIN_CODE_TTL_SECONDS", "900"))


def _server_version_text() -> str:
    global _server_version_cache
    env_version = str(
        os.getenv("SERVER_APP_VERSION") or os.getenv("APP_VERSION") or ""
    ).strip()
    if env_version:
        return f"version={env_version}"
    if _server_version_cache:
        return _server_version_cache
    repo_dir = Path(__file__).resolve().parent
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
            timeout=2,
            check=True,
        ).stdout.strip()
        branch = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
            timeout=2,
            check=True,
        ).stdout.strip() or "detached"
        _server_version_cache = (
            f"version={SERVER_CODE_VERSION} branch={branch} commit={commit}"
        )
    except Exception:
        _server_version_cache = f"version={SERVER_CODE_VERSION}"
    return _server_version_cache


def _write_task_version_log(task_id: int) -> None:
    _write_task_log(task_id, f"代码版本：{_server_version_text()}")


def _db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=max(1, DB_BUSY_TIMEOUT_MS // 1000))
    conn.execute(f"PRAGMA busy_timeout={DB_BUSY_TIMEOUT_MS}")
    global _db_initialized
    if not _db_initialized:
        with _db_init_lock:
            if not _db_initialized:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
                _db_initialized = True
    return conn


def _is_db_locked(exc: sqlite3.OperationalError) -> bool:
    text = str(exc).lower()
    return "database is locked" in text or "database table is locked" in text


def _db_write(action):
    last_exc: Optional[sqlite3.OperationalError] = None
    for attempt in range(DB_WRITE_RETRIES):
        try:
            with _db_write_lock:
                with _db_connect() as conn:
                    result = action(conn)
                    conn.commit()
                    return result
        except sqlite3.OperationalError as exc:
            if not _is_db_locked(exc):
                raise
            last_exc = exc
            time.sleep(min(2.0, 0.15 * (attempt + 1)))
    if last_exc:
        raise last_exc
    raise RuntimeError("database write failed")


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._lock = threading.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        with self._lock:
            self._connections.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        with self._lock:
            self._connections.discard(websocket)

    def has_connections(self) -> bool:
        with self._lock:
            return bool(self._connections)

    async def broadcast(self, message: dict) -> None:
        with self._lock:
            targets = list(self._connections)
        stale: list[WebSocket] = []
        for ws in targets:
            try:
                await ws.send_json(message)
            except Exception:
                stale.append(ws)
        if stale:
            with self._lock:
                for ws in stale:
                    self._connections.discard(ws)


ws_manager = ConnectionManager()

_login_codes: dict[str, str] = {}
_login_lock = threading.Lock()
_client_lock = threading.Lock()
_task_session_locks: dict[tuple[str, str, str], threading.Lock] = {}
_task_session_locks_lock = threading.Lock()
_external_upload_jobs: dict[str, dict] = {}
_external_upload_jobs_lock = threading.Lock()
_external_upload_cancel_events: dict[int, threading.Event] = {}
_external_upload_executor = ThreadPoolExecutor(
    max_workers=EXTERNAL_JSON_TASK_CONCURRENCY,
    thread_name_prefix="external-json-task",
)
_task_progress_write_lock = threading.RLock()
_json_md5_locks: dict[str, threading.Lock] = {}
_json_md5_locks_lock = threading.Lock()
_progress_throttle_lock = threading.Lock()
_last_progress_write: dict[int, float] = {}
_task_cache_lock = threading.Lock()
_task_cache: dict[int, dict] = {}
_active_telegram_clients: set[TelegramClient] = set()
_telegram_client_pool: dict[tuple[str, str, str], TelegramClient] = {}
_telegram_client_pool_sessions: dict[tuple[str, str, str], list[Path]] = {}
_telegram_client_pool_last_used: dict[tuple[str, str, str], float] = {}
TELEGRAM_POOL_IDLE_SECONDS = float(os.getenv("TELEGRAM_POOL_IDLE_SECONDS", "20"))


def _cache_task(task: dict) -> None:
    task_id = int(task.get("id") or 0)
    if not task_id:
        return
    with _task_cache_lock:
        cached = _task_cache.get(task_id, {})
        cached.update(task)
        _task_cache[task_id] = cached


async def _acquire_client_lock_async() -> None:
    while True:
        if _client_lock.acquire(blocking=False):
            return
        await asyncio.sleep(0.05)


async def _with_client_lock_async(action):
    await _acquire_client_lock_async()
    try:
        return await action()
    finally:
        _client_lock.release()


def _with_client_lock_sync(action):
    with _client_lock:
        return action()


def _task_session_lock_key(
    api_id: str, api_hash: str, output_dir: Path
) -> tuple[str, str, str]:
    return (str(api_id), str(api_hash), str(output_dir.resolve()))


def _get_task_session_lock(
    api_id: str, api_hash: str, output_dir: Path
) -> threading.Lock:
    key = _task_session_lock_key(api_id, api_hash, output_dir)
    with _task_session_locks_lock:
        lock = _task_session_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _task_session_locks[key] = lock
        return lock


def _with_task_session_lock_sync(api_id: str, api_hash: str, output_dir: Path, action):
    with _get_task_session_lock(api_id, api_hash, output_dir):
        return action()


def _broadcast_event(event: dict) -> None:
    if not ws_manager.has_connections():
        return
    try:
        anyio.from_thread.run(ws_manager.broadcast, event)
    except RuntimeError:
        pass


def _utc_now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


_MOJIBAKE_MARKERS = ("Ã", "Â", "ä", "å", "æ", "è", "é", "ç", "ð", "œ", "Š", "€")


def _decode_mojibake_fragment(text: str) -> str:
    repaired = text
    for _ in range(4):
        if not any(marker in repaired for marker in _MOJIBAKE_MARKERS):
            break
        changed = False
        for encoding in ("cp1252", "latin1"):
            try:
                candidate = repaired.encode(encoding).decode("utf-8")
            except (UnicodeEncodeError, UnicodeDecodeError):
                continue
            if candidate and candidate != repaired:
                repaired = candidate
                changed = True
                break
        if not changed:
            break
    return repaired


def _is_mojibake_fragment_char(char: str) -> bool:
    try:
        char.encode("cp1252")
        return True
    except UnicodeEncodeError:
        pass
    try:
        char.encode("latin1")
        return True
    except UnicodeEncodeError:
        return False


def _repair_mojibake_text(value: object) -> str:
    text = str(value)
    if not any(marker in text for marker in _MOJIBAKE_MARKERS):
        return text

    repaired = _decode_mojibake_fragment(text)
    if repaired != text:
        return repaired

    parts: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if not _is_mojibake_fragment_char(char):
            parts.append(char)
            index += 1
            continue
        start = index
        while index < len(text) and _is_mojibake_fragment_char(text[index]):
            index += 1
        fragment = text[start:index]
        if any(marker in fragment for marker in _MOJIBAKE_MARKERS):
            parts.append(_decode_mojibake_fragment(fragment))
        else:
            parts.append(fragment)
    return "".join(parts)


def _repair_mojibake_value(value: object) -> object:
    if isinstance(value, str):
        return _repair_mojibake_text(value)
    if isinstance(value, list):
        return [_repair_mojibake_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_repair_mojibake_value(item) for item in value)
    if isinstance(value, dict):
        return {key: _repair_mojibake_value(item) for key, item in value.items()}
    return value


def _load_config() -> dict:
    if not CONFIG_PATH.exists():
        config = {}
    else:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    config.setdefault("upload_base_url", DEFAULT_UPLOAD_BASE_URL)
    config.setdefault("video_meta_url", DEFAULT_VIDEO_META_URL)
    config.setdefault("movie_create_url", DEFAULT_MOVIE_CREATE_URL)
    config.setdefault("video_type_threshold_seconds", DEFAULT_VIDEO_TYPE_THRESHOLD_SECONDS)
    config.setdefault("min_video_duration_seconds", MIN_VIDEO_DURATION_SECONDS)
    config.setdefault("max_running_tasks", DEFAULT_MAX_RUNNING_TASKS)
    return config


def _coerce_non_negative_int(value: object, default: int) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def _save_config(config: dict) -> None:
    CONFIG_PATH.write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _extract_video_frame(
    video_path: Path, output_path: Path, duration: Optional[float] = None
) -> bool:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False
    try:
        if output_path.exists():
            output_path.unlink()
    except Exception:
        pass
    seek_time = 1.0
    if isinstance(duration, (int, float)) and duration > 2:
        seek_time = max(1.0, duration / 2)
    cmd = [
        ffmpeg,
        "-y",
        "-ss",
        str(seek_time),
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        "-q:v",
        "2",
        str(output_path),
    ]
    try:
        subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return False
    return output_path.exists()


def _get_api_token() -> str:
    env_token = os.getenv("SERVER_API_TOKEN", "").strip()
    if env_token:
        return env_token
    return str(_load_config().get("api_token", "")).strip()


def _require_token(
    authorization: Optional[str] = Header(default=None),
    x_token: Optional[str] = Header(default=None),
    token: Optional[str] = Query(default=None),
) -> None:
    expected = _get_api_token()
    if not expected:
        return
    provided = ""
    if authorization and authorization.lower().startswith("bearer "):
        provided = authorization.split(" ", 1)[1].strip()
    elif x_token:
        provided = x_token.strip()
    elif token:
        provided = token.strip()
    if not provided or provided != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")


def _ensure_db() -> None:
    with _db_connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                status TEXT NOT NULL,
                channel TEXT NOT NULL,
                message_ids TEXT,
                start_date TEXT,
                end_date TEXT,
                output_dir TEXT,
                video_type_threshold_seconds INTEGER,
                min_video_duration_seconds INTEGER,
                auto_upload INTEGER,
                upload_meta INTEGER,
                created_at TEXT,
                updated_at TEXT,
                progress_json TEXT,
                error TEXT
            )
            """
        )
        try:
            conn.execute("ALTER TABLE tasks ADD COLUMN video_type_threshold_seconds INTEGER")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE tasks ADD COLUMN min_video_duration_seconds INTEGER")
        except sqlite3.OperationalError:
            pass
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS uploaded_videos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel TEXT NOT NULL,
                message_id INTEGER NOT NULL,
                file_name TEXT,
                file_size INTEGER,
                content_md5 TEXT,
                upload_id INTEGER,
                uploaded_at TEXT,
                UNIQUE(channel, message_id)
            )
            """
        )
        try:
            conn.execute("ALTER TABLE uploaded_videos ADD COLUMN content_md5 TEXT")
        except sqlite3.OperationalError:
            pass
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_uploaded_videos_channel_message ON uploaded_videos(channel, message_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_uploaded_videos_content_md5 ON uploaded_videos(content_md5)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS login_code_requests (
                login_key TEXT PRIMARY KEY,
                code_hash TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        rows = conn.execute(
            "SELECT channel, progress_json FROM tasks WHERE progress_json IS NOT NULL AND progress_json != ''"
        ).fetchall()
        for channel, raw_progress in rows:
            try:
                progress = json.loads(raw_progress)
            except Exception:
                continue
            files = progress.get("files") if isinstance(progress, dict) else {}
            if not isinstance(files, dict):
                continue
            for key, file_info in files.items():
                if not isinstance(file_info, dict):
                    continue
                upload_id = file_info.get("upload_id")
                if not upload_id:
                    continue
                message_id = file_info.get("message_id") or key
                if not str(message_id).isdigit():
                    continue
                conn.execute(
                    """
                    INSERT OR IGNORE INTO uploaded_videos (
                        channel, message_id, file_name, file_size, upload_id, uploaded_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        channel,
                        int(message_id),
                        str(file_info.get("file_name") or ""),
                        int(file_info.get("upload_total") or file_info.get("bytes_total") or 0) or None,
                        int(upload_id),
                        _utc_now(),
                    ),
                )
        conn.commit()


def _write_task_log(task_id: int, message: str) -> None:
    message = _repair_mojibake_text(message)
    log_path = STATE_DIR / f"task_{task_id}.log"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with log_path.open("a", encoding="utf-8", errors="ignore") as handle:
        handle.write(f"[{timestamp}] {message}\n")
    _broadcast_event({"type": "task_log", "task_id": task_id, "message": message})


def _update_task(task_id: int, **fields: object) -> None:
    fields = {key: _repair_mojibake_value(value) for key, value in fields.items()}
    fields["updated_at"] = _utc_now()
    keys = ", ".join(f"{k}=?" for k in fields.keys())
    values = list(fields.values()) + [task_id]
    _db_write(lambda conn: conn.execute(f"UPDATE tasks SET {keys} WHERE id=?", values))
    _cache_task({"id": task_id, **fields})
    _broadcast_event({"type": "task_update", "task_id": task_id, "patch": fields})


def _fetch_uploaded_video(channel: str, message_id: int) -> Optional[dict]:
    with _db_connect() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT channel, message_id, file_name, file_size, content_md5, upload_id, uploaded_at
            FROM uploaded_videos
            WHERE channel=? AND message_id=?
            """,
            (channel, int(message_id)),
        ).fetchone()
    return dict(row) if row else None


def _fetch_uploaded_video_by_md5(content_md5: Optional[str]) -> Optional[dict]:
    value = str(content_md5 or "").strip().lower()
    if not value:
        return None
    with _db_connect() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT channel, message_id, file_name, file_size, content_md5, upload_id, uploaded_at
            FROM uploaded_videos
            WHERE content_md5=?
            ORDER BY id DESC
            LIMIT 1
            """,
            (value,),
        ).fetchone()
    return dict(row) if row else None


def _delete_uploaded_videos(channel: str, message_ids: list[int]) -> int:
    ids = [int(item) for item in message_ids if isinstance(item, int) or str(item).isdigit()]
    if not ids:
        return 0
    placeholders = ",".join("?" for _ in ids)
    def _delete(conn):
        cur = conn.execute(
            f"DELETE FROM uploaded_videos WHERE channel=? AND message_id IN ({placeholders})",
            (channel, *ids),
        )
        return int(cur.rowcount or 0)

    return int(_db_write(_delete) or 0)


def _hash_file_with_hashlib(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(2 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_content_md5(path: Path) -> Optional[str]:
    if not path.exists() or not path.is_file():
        return None
    if SPARK_MD5_HELPER.exists():
        try:
            result = subprocess.run(
                ["node", str(SPARK_MD5_HELPER), str(path)],
                capture_output=True,
                text=True,
                timeout=600,
                check=True,
            )
            value = result.stdout.strip().splitlines()[-1].strip().lower()
            if re.fullmatch(r"[a-f0-9]{32}", value):
                return value
        except Exception:
            pass
    return _hash_file_with_hashlib(path)


def _record_uploaded_video(
    channel: str,
    message_id: int,
    file_name: str,
    file_size: Optional[int],
    upload_id: int,
    content_md5: Optional[str] = None,
) -> None:
    md5_value = str(content_md5 or "").strip().lower() or None
    _db_write(
        lambda conn: conn.execute(
            """
            INSERT INTO uploaded_videos (
                channel, message_id, file_name, file_size, content_md5, upload_id, uploaded_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(channel, message_id) DO UPDATE SET
                file_name=excluded.file_name,
                file_size=excluded.file_size,
                content_md5=excluded.content_md5,
                upload_id=excluded.upload_id,
                uploaded_at=excluded.uploaded_at
            """,
            (
                channel,
                int(message_id),
                file_name,
                int(file_size) if file_size is not None else None,
                md5_value,
                int(upload_id),
                _utc_now(),
            ),
        )
    )


def _merge_task_progress(task_id: int, patch: dict) -> None:
    # JSON uploads can complete on several worker threads at once. Keep the
    # read-modify-write operation atomic so one file update cannot erase another.
    with _task_progress_write_lock:
        _merge_task_progress_unlocked(task_id, patch)


def _merge_task_progress_unlocked(task_id: int, patch: dict) -> None:
    patch = _repair_mojibake_value(patch)  # type: ignore[assignment]
    now = time.monotonic()
    fast_keys = {"download", "upload", "upload_video"}
    important_keys = {"status", "stage", "download_count", "upload_count", "files"}
    if set(patch.keys()).issubset(fast_keys) and not (
        set(patch.keys()) & important_keys
    ):
        with _progress_throttle_lock:
            last = _last_progress_write.get(task_id, 0.0)
            if now - last < 2.0:
                return
            _last_progress_write[task_id] = now
    else:
        with _progress_throttle_lock:
            _last_progress_write[task_id] = now
    current = _fetch_task(task_id) or {}
    progress: dict = {}
    raw = current.get("progress_json")
    if isinstance(raw, str) and raw:
        try:
            progress = json.loads(raw)
        except json.JSONDecodeError:
            progress = {}
    elif isinstance(raw, dict):
        progress = raw
    progress.setdefault("download", {})
    progress.setdefault("upload", {})
    progress.setdefault("upload_video", {})
    progress.setdefault("files", {})
    progress.setdefault("download_count", {})
    progress.setdefault("upload_count", {})
    if "download" in patch and isinstance(patch["download"], dict):
        progress["download"].update(patch["download"])
    if "upload" in patch and isinstance(patch["upload"], dict):
        progress["upload"].update(patch["upload"])
    if "upload_video" in patch and isinstance(patch["upload_video"], dict):
        progress["upload_video"].update(patch["upload_video"])
    if "files" in patch and isinstance(patch["files"], dict):
        for file_key, file_patch in patch["files"].items():
            key = str(file_key)
            if isinstance(file_patch, dict):
                current_file = progress["files"].get(key, {})
                if isinstance(current_file, dict):
                    current_file.update(file_patch)
                    progress["files"][key] = current_file
                else:
                    progress["files"][key] = file_patch
            else:
                progress["files"][key] = file_patch
    if "download_count" in patch and isinstance(patch["download_count"], dict):
        progress["download_count"].update(patch["download_count"])
    if "upload_count" in patch and isinstance(patch["upload_count"], dict):
        progress["upload_count"].update(patch["upload_count"])
    for key in ("status", "stage"):
        if key in patch:
            progress[key] = patch[key]
    progress = _repair_mojibake_value(progress)  # type: ignore[assignment]
    _update_task(task_id, progress_json=json.dumps(progress, ensure_ascii=False))


def _fetch_task(task_id: int) -> Optional[dict]:
    with _db_connect() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    return dict(row) if row else None


def _fetch_next_pending() -> Optional[dict]:
    with _db_connect() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM tasks WHERE status='pending' ORDER BY id LIMIT 1"
        ).fetchone()
    return dict(row) if row else None


def _list_tasks(
    limit: int = 100,
    offset: int = 0,
    status: Optional[list[str]] = None,
    channel: Optional[str] = None,
    q: Optional[str] = None,
    created_from: Optional[str] = None,
    created_to: Optional[str] = None,
    updated_from: Optional[str] = None,
    updated_to: Optional[str] = None,
    sort_by: str = "id",
    sort_order: str = "desc",
) -> tuple[list[dict], int]:
    where: list[str] = []
    params: list[object] = []
    if status:
        placeholders = ",".join(["?"] * len(status))
        where.append(f"status IN ({placeholders})")
        params.extend(status)
    if channel:
        where.append("channel LIKE ?")
        params.append(f"%{channel}%")
    if q:
        where.append("(channel LIKE ? OR message_ids LIKE ? OR error LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])
    if created_from:
        where.append("created_at >= ?")
        params.append(created_from)
    if created_to:
        where.append("created_at <= ?")
        params.append(created_to)
    if updated_from:
        where.append("updated_at >= ?")
        params.append(updated_from)
    if updated_to:
        where.append("updated_at <= ?")
        params.append(updated_to)
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    allowed_sort = {"id", "created_at", "updated_at", "status", "channel"}
    sort_by = sort_by if sort_by in allowed_sort else "id"
    sort_order = "asc" if sort_order.lower() == "asc" else "desc"
    order_sql = f"ORDER BY {sort_by} {sort_order}"

    with _db_connect() as conn:
        conn.row_factory = sqlite3.Row
        total = conn.execute(
            f"SELECT COUNT(1) FROM tasks {where_sql}", params
        ).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM tasks {where_sql} {order_sql} LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()
    return [dict(row) for row in rows], int(total)


def _create_task(
    channel: str,
    message_ids: list[int],
    start_date: Optional[str],
    end_date: Optional[str],
    output_dir: Optional[str],
    video_type_threshold_seconds: Optional[int],
    min_video_duration_seconds: Optional[int],
    auto_upload: bool,
    upload_meta: bool,
) -> int:
    now = _utc_now()
    def _insert(conn):
        cur = conn.execute(
            """
            INSERT INTO tasks (
                status, channel, message_ids, start_date, end_date, output_dir,
                video_type_threshold_seconds, min_video_duration_seconds,
                auto_upload, upload_meta, created_at, updated_at, progress_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "pending",
                channel,
                json.dumps(message_ids, ensure_ascii=False),
                start_date,
                end_date,
                output_dir,
                video_type_threshold_seconds,
                min_video_duration_seconds,
                int(auto_upload),
                int(upload_meta),
                now,
                now,
                json.dumps({}),
            ),
        )
        return int(cur.lastrowid)

    task_id = int(_db_write(_insert))
    _cache_task(
        {
            "id": task_id,
            "status": "pending",
            "channel": channel,
            "message_ids": json.dumps(message_ids, ensure_ascii=False),
            "start_date": start_date,
            "end_date": end_date,
            "output_dir": output_dir,
            "video_type_threshold_seconds": video_type_threshold_seconds,
            "min_video_duration_seconds": min_video_duration_seconds,
            "auto_upload": int(auto_upload),
            "upload_meta": int(upload_meta),
            "created_at": now,
            "updated_at": now,
            "progress_json": json.dumps({}),
            "error": None,
        }
    )
    return task_id


def _external_upload_progress(
    total: int,
    payload: Optional[object] = None,
    category: Optional[str] = None,
    limit: Optional[int] = None,
    md5_by_url: Optional[dict] = None,
) -> dict:
    progress = {
        "stage": "upload",
        "status": "JSON视频上传等待执行中",
        "download_count": {"done": 0, "total": total},
        "upload_count": {"done": 0, "total": total},
        "files": {},
    }
    if payload is not None:
        progress["external_upload"] = {
            "payload": payload,
            "category": category,
            "limit": limit,
            "md5_by_url": md5_by_url or {},
        }
    return progress


def _create_external_upload_task(
    total: int,
    payload: Optional[object] = None,
    category: Optional[str] = None,
    limit: Optional[int] = None,
) -> int:
    config = _load_config()
    now = _utc_now()
    output_dir = str(config.get("download_root") or "downloads")
    progress = _external_upload_progress(total, payload, category, limit)

    def _insert(conn):
        cur = conn.execute(
            """
            INSERT INTO tasks (
                status, channel, message_ids, start_date, end_date, output_dir,
                video_type_threshold_seconds, min_video_duration_seconds,
                auto_upload, upload_meta, created_at, updated_at, progress_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "pending",
                "JSON视频上传",
                json.dumps([], ensure_ascii=False),
                None,
                None,
                output_dir,
                config.get("video_type_threshold_seconds"),
                config.get("min_video_duration_seconds"),
                1,
                1,
                now,
                now,
                json.dumps(progress, ensure_ascii=False),
            ),
        )
        return int(cur.lastrowid)

    task_id = int(_db_write(_insert))
    _cache_task(
        {
            "id": task_id,
            "status": "pending",
            "channel": "JSON视频上传",
            "message_ids": json.dumps([], ensure_ascii=False),
            "start_date": None,
            "end_date": None,
            "output_dir": output_dir,
            "video_type_threshold_seconds": config.get("video_type_threshold_seconds"),
            "min_video_duration_seconds": config.get("min_video_duration_seconds"),
            "auto_upload": 1,
            "upload_meta": 1,
            "created_at": now,
            "updated_at": now,
            "progress_json": json.dumps(progress, ensure_ascii=False),
            "error": None,
        }
    )
    _broadcast_event({"type": "task_created", "task_id": task_id, "status": "running"})
    return task_id


def _delete_task(task_id: int) -> None:
    _db_write(lambda conn: conn.execute("DELETE FROM tasks WHERE id=?", (task_id,)))
    log_path = STATE_DIR / f"task_{task_id}.log"
    if log_path.exists():
        try:
            log_path.unlink()
        except OSError:
            pass


def _read_task_log(
    task_id: int, limit: int = 200, offset: int = 0, search: Optional[str] = None
) -> dict:
    log_path = STATE_DIR / f"task_{task_id}.log"
    if not log_path.exists():
        return {"items": [], "total": 0, "limit": limit, "offset": offset}
    lines = [
        _repair_mojibake_text(line)
        for line in log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    ]
    if search:
        lines = [line for line in lines if search in line]
    total = len(lines)
    start = max(0, offset)
    end = start + max(1, limit)
    items = [{"message": line} for line in lines[start:end]]
    return {"items": items, "total": total, "limit": limit, "offset": offset}


def _task_summary() -> dict:
    with _db_connect() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT status, COUNT(1) AS cnt FROM tasks GROUP BY status"
        ).fetchall()
    counts = {row["status"]: int(row["cnt"]) for row in rows}
    return {"total": sum(counts.values()), "by_status": counts}


def _is_stale(updated_at: str, stale_seconds: int) -> bool:
    if not updated_at:
        return False
    text = updated_at.replace("Z", "+00:00")
    try:
        updated = datetime.fromisoformat(text)
    except ValueError:
        return False
    now = datetime.utcnow().replace(microsecond=0)
    return (now - updated).total_seconds() >= stale_seconds


@dataclass
class RunningTask:
    task_id: int
    stop_event: threading.Event
    allowed_ids: Optional[set[int]] = None
    removed_ids: set[int] = field(default_factory=set)
    removed_lock: threading.Lock = field(default_factory=threading.Lock)
    paused_ids: set[int] = field(default_factory=set)
    paused_lock: threading.Lock = field(default_factory=threading.Lock)

    def is_removed(self, message_id: int) -> bool:
        with self.removed_lock:
            return message_id in self.removed_ids

    def is_paused(self, message_id: int) -> bool:
        with self.paused_lock:
            return message_id in self.paused_ids


class QueueReader:
    def __init__(self, chunks: "queue.Queue[object]") -> None:
        self._chunks = chunks
        self._buffer = bytearray()
        self._done = False

    def read(self, size: int = -1) -> bytes:
        if self._done:
            return b""
        while size < 0 or len(self._buffer) < size:
            item = self._chunks.get()
            if item is None:
                self._done = True
                break
            if isinstance(item, BaseException):
                self._done = True
                raise item
            self._buffer.extend(item)
            if size < 0:
                break
        if size < 0 or size > len(self._buffer):
            size = len(self._buffer)
        data = bytes(self._buffer[:size])
        del self._buffer[:size]
        return data


def _message_duration(message) -> Optional[int]:
    media = getattr(message, "video", None) or getattr(message, "document", None)
    duration = getattr(media, "duration", None)
    if duration is not None:
        return int(duration)
    for attr in getattr(media, "attributes", []) or []:
        value = getattr(attr, "duration", None)
        if value is not None:
            return int(value)
    return None


def _message_mime_type(message) -> str:
    file_info = getattr(message, "file", None)
    if file_info and getattr(file_info, "mime_type", None):
        return str(file_info.mime_type)
    media = getattr(message, "video", None) or getattr(message, "document", None)
    if media and getattr(media, "mime_type", None):
        return str(media.mime_type)
    return "video/mp4"


def _movie_title_from_content(content: str, fallback: str = "") -> str:
    text = str(content or "")
    if not text:
        text = str(fallback or "")
    return text or "未命名"


def _telegram_id_candidates(channel: str) -> set[int]:
    text = str(channel or "").strip()
    if not re.fullmatch(r"-?\d+", text):
        return set()
    value = int(text)
    candidates = {value, abs(value)}
    if value > 0:
        candidates.add(int(f"-100{value}"))
    if text.startswith("-100") and len(text) > 4:
        try:
            candidates.add(int(text[4:]))
        except ValueError:
            pass
    return candidates


def _normalize_telegram_channel(channel: str) -> str:
    text = str(channel or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        text = text[1:-1].strip()
    if text.startswith("http://") or text.startswith("https://"):
        clean = text.split("?", 1)[0].rstrip("/")
        parts = [part for part in clean.split("/") if part]
        host_index = next(
            (
                index
                for index, part in enumerate(parts)
                if part.lower() in {"t.me", "telegram.me", "www.t.me"}
            ),
            -1,
        )
        tail = parts[host_index + 1 :] if host_index >= 0 else parts
        if len(tail) >= 2 and tail[0].lower() == "c" and tail[1].isdigit():
            text = f"-100{tail[1]}"
        elif tail:
            text = tail[0]
    if text.startswith("@"):
        text = text[1:]
    return text.strip()


def _resolved_peer_id(peer) -> Optional[int]:
    for attr in ("channel_id", "chat_id", "user_id"):
        value = getattr(peer, attr, None)
        if isinstance(value, int):
            return value
    return None


async def _resolve_username_input_entity(client: TelegramClient, username: str):
    resolved = await client(ResolveUsernameRequest(username))
    peer_id = _resolved_peer_id(getattr(resolved, "peer", None))
    entities = list(getattr(resolved, "chats", None) or []) + list(
        getattr(resolved, "users", None) or []
    )
    for entity in entities:
        if peer_id is not None and getattr(entity, "id", None) != peer_id:
            continue
        try:
            return utils.get_input_peer(entity)
        except Exception:
            return await client.get_input_entity(entity)
    return None


async def _resolve_telegram_entity(client: TelegramClient, channel: str):
    text = _normalize_telegram_channel(channel)
    if not text:
        raise RuntimeError("Telegram 频道不能为空。")
    if not re.fullmatch(r"-?\d+", text):
        target_username = text.lower().lstrip("@")
        async for dialog in client.iter_dialogs():
            entity = getattr(dialog, "entity", None)
            input_entity = getattr(dialog, "input_entity", None)
            username = str(getattr(entity, "username", "") or "").lower()
            if username and username == target_username:
                try:
                    return utils.get_input_peer(entity)
                except Exception:
                    return input_entity or entity
        resolved_entity = await _resolve_username_input_entity(client, target_username)
        if resolved_entity is not None:
            return resolved_entity
        try:
            return await client.get_input_entity(f"@{target_username}")
        except Exception:
            return await client.get_input_entity(text)
    candidates = _telegram_id_candidates(text)
    async for dialog in client.iter_dialogs():
        entity = getattr(dialog, "entity", None)
        input_entity = getattr(dialog, "input_entity", None)
        entity_id = getattr(entity, "id", None)
        peer_id = None
        try:
            peer_id = utils.get_peer_id(entity)
        except Exception:
            pass
        if (
            (isinstance(entity_id, int) and entity_id in candidates)
            or (isinstance(peer_id, int) and peer_id in candidates)
        ):
            return input_entity or entity
    value = int(text)
    try:
        return await client.get_input_entity(value)
    except Exception:
        pass
    raise RuntimeError(
        f"找不到 Chat ID {text} 对应的 Telegram 实体。请确认当前登录账号已加入该频道/群，"
        "或改用 @用户名 / t.me 链接加载。"
    )


def _message_file_size(message) -> int:
    candidates = [
        getattr(getattr(getattr(message, "media", None), "document", None), "size", None),
        getattr(getattr(message, "document", None), "size", None),
        getattr(getattr(message, "video", None), "size", None),
        getattr(getattr(message, "file", None), "size", None),
    ]
    for value in candidates:
        try:
            size = int(value)
        except (TypeError, ValueError):
            continue
        if size > 0:
            return size
    return 0


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


def _image_media_type(path: Path) -> str:
    suffix = _detect_image_extension(path)
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }.get(suffix, "image/jpeg")


async def _resolve_message_caption(client: TelegramClient, channel: str, message) -> str:
    entity = await _resolve_telegram_entity(client, channel)
    caption = message_caption(message)
    if caption:
        return caption
    try:
        refreshed = await client.get_messages(entity, ids=message.id)
    except Exception:
        refreshed = None
    if refreshed:
        caption = message_caption(refreshed)
        if caption:
            return caption
        message = refreshed
    grouped_id = getattr(message, "grouped_id", None)
    if grouped_id is None:
        return ""
    try:
        async for msg in client.iter_messages(
            entity,
            min_id=max(0, int(message.id) - 200),
            max_id=int(message.id) + 200,
        ):
            if getattr(msg, "grouped_id", None) != grouped_id:
                continue
            caption = message_caption(msg)
            if caption:
                return caption
    except Exception:
        return ""
    return ""


async def _upload_message_thumbnail(
    message,
    task_id: int,
    uploader: UploadClient,
) -> int:
    document = getattr(getattr(message, "media", None), "document", None)
    thumbs = getattr(document, "thumbs", None) or []
    if not thumbs:
        return 0
    thumb_dir = STATE_DIR / "telegram_thumbs"
    thumb_dir.mkdir(parents=True, exist_ok=True)
    thumb_path = thumb_dir / f"task_{task_id}_{getattr(message, 'id', 'unknown')}_thumb.bin"
    upload_path = thumb_path
    try:
        try:
            if thumb_path.exists():
                thumb_path.unlink()
        except OSError:
            pass
        await message.download_media(file=thumb_path, thumb=-1)
        if not thumb_path.exists() or thumb_path.stat().st_size <= 0:
            return 0
        upload_path = _rename_image_to_detected_extension(thumb_path)
        return int(await asyncio.to_thread(uploader.upload_image_file, upload_path))
    except Exception as exc:
        _write_task_log(task_id, f"封面上传失败({getattr(message, 'id', '')}): {exc}")
        return 0
    finally:
        for path in {thumb_path, upload_path}:
            try:
                if path.exists():
                    path.unlink()
            except OSError:
                pass


def _task_min_video_duration_seconds(task: dict, config: Optional[dict] = None) -> int:
    value = task.get("min_video_duration_seconds")
    if value is None:
        config = config or _load_config()
        value = config.get("min_video_duration_seconds")
    return _coerce_non_negative_int(value, MIN_VIDEO_DURATION_SECONDS)


def _is_uploadable_message(
    message, min_video_duration_seconds: int = MIN_VIDEO_DURATION_SECONDS
) -> bool:
    if message is None:
        return False
    if is_filtered_caption(message_caption(message)):
        return False
    if _is_too_short_message(message, min_video_duration_seconds):
        return False
    if getattr(message, "video", None):
        return True
    document = getattr(message, "document", None)
    mime_type = getattr(document, "mime_type", "") if document else ""
    return bool(document and str(mime_type).startswith("video/"))


def _is_too_short_message(
    message, min_video_duration_seconds: int = MIN_VIDEO_DURATION_SECONDS
) -> bool:
    duration = _message_duration(message)
    return duration is not None and duration < min_video_duration_seconds


class TaskRunner:
    def __init__(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._running: dict[int, RunningTask] = {}
        self._running_lock = threading.Lock()
        self._stop_flag = threading.Event()

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop_flag.set()
        with self._running_lock:
            running_tasks = list(self._running.values())
        for running in running_tasks:
            running.stop_event.set()

    def cancel(self, task_id: int) -> bool:
        with self._running_lock:
            running = self._running.get(task_id)
        if not running:
            return False
        running.stop_event.set()
        _update_task(task_id, status="cancelled")
        _write_task_log(task_id, "已取消任务，正在等待当前网络操作结束。")
        return True

    def remove_ids(self, task_id: int, ids: list[int]) -> None:
        with self._running_lock:
            running = self._running.get(task_id)
        if not running or not running.allowed_ids:
            if not running:
                return
        for msg_id in ids:
            if running.allowed_ids is not None:
                running.allowed_ids.discard(msg_id)
            with running.removed_lock:
                running.removed_ids.add(msg_id)

    def set_pause(self, task_id: int, message_id: int, paused: bool) -> bool:
        with self._running_lock:
            running = self._running.get(task_id)
        if not running:
            return False
        with running.paused_lock:
            if paused:
                running.paused_ids.add(message_id)
            else:
                running.paused_ids.discard(message_id)
        return True

    def _max_running_tasks(self) -> int:
        # Telegram downloads share account sessions and local manifests.
        # Keep this queue strictly serial to avoid session/database contention.
        return DEFAULT_MAX_RUNNING_TASKS

    def _running_count(self) -> int:
        with self._running_lock:
            return len(self._running)

    def _loop(self) -> None:
        while not self._stop_flag.is_set():
            if self._running_count() >= self._max_running_tasks():
                time.sleep(0.5)
                continue
            task = _fetch_next_pending()
            if not task:
                time.sleep(1)
                continue
            task_id = int(task["id"])
            stop_event = threading.Event()
            _cache_task(task)
            running = RunningTask(task_id=task_id, stop_event=stop_event)
            with self._running_lock:
                if len(self._running) >= self._max_running_tasks():
                    continue
                self._running[task_id] = running
            _update_task(task_id, status="running")
            _write_task_version_log(task_id)
            _write_task_log(
                task_id,
                f"任务开始执行。并发运行 {self._running_count()}/{self._max_running_tasks()}",
            )
            threading.Thread(
                target=self._run_task_worker,
                args=(task, running),
                daemon=True,
                name=f"task-runner-{task_id}",
            ).start()

    def _run_task_worker(self, task: dict, running: RunningTask) -> None:
        task_id = int(task["id"])
        stop_event = running.stop_event
        try:
            self._run_task(task, running)
            if stop_event.is_set():
                _update_task(task_id, status="cancelled")
                _write_task_log(task_id, "任务已取消。")
            else:
                _update_task(task_id, status="done")
                _write_task_log(task_id, "任务完成。")
        except Exception as exc:
            if stop_event.is_set():
                _update_task(task_id, status="cancelled", error=None)
                _write_task_log(task_id, "任务已取消。")
            else:
                _update_task(task_id, status="failed", error=str(exc))
                _write_task_log(task_id, f"任务失败: {exc}")
        except BaseException as exc:
            if stop_event.is_set():
                _update_task(task_id, status="cancelled", error=None)
                _write_task_log(task_id, "任务已取消。")
            else:
                _update_task(task_id, status="failed", error=str(exc))
                _write_task_log(task_id, f"任务异常中止: {exc}")
        finally:
            with self._running_lock:
                self._running.pop(task_id, None)

    def _run_task(self, task: dict, running: RunningTask) -> None:
        config = _load_config()
        api_id = config.get("telegram_api_id")
        api_hash = config.get("telegram_api_hash")
        if not api_id or not api_hash:
            raise RuntimeError("ç¼ºå°‘ Telegram API ID/Hashï¼Œè¯·å…ˆé…ç½® server_config.json")
        concurrency = config.get("telegram_download_concurrency")
        part_kb = config.get("telegram_download_part_kb")
        if concurrency is not None:
            os.environ["TELEGRAM_DOWNLOAD_CONCURRENCY"] = str(concurrency)
        if part_kb is not None:
            os.environ["TELEGRAM_DOWNLOAD_PART_KB"] = str(part_kb)
        min_video_duration_seconds = _task_min_video_duration_seconds(task, config)

        channel = task["channel"]
        message_ids = json.loads(task["message_ids"] or "[]")
        if not message_ids and not (task.get("start_date") or task.get("end_date")):
            raise RuntimeError("ä»»åŠ¡éœ€è¦ message_ids æˆ–è€…æ—¥æœŸèŒƒå›´ã€‚")
        allowed_ids = set(message_ids) if message_ids else None
        running.allowed_ids = allowed_ids

        root_dir = Path(config.get("download_root", "downloads")).expanduser().resolve()
        output_dir = (
            Path(task["output_dir"])
            if task.get("output_dir")
            else root_dir / channel.replace("/", "_")
        )
        output_dir = output_dir.expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        output_session = output_dir / "user_session.session"
        if not output_session.exists():
            root_session = root_dir / "user_session.session"
            root_session_parts = list(root_dir.glob("user_session.session*"))
            if not root_session.exists():
                raise RuntimeError(
                    "未发现当前任务目录的 Telegram 登录会话，请先在登录页使用该输出目录登录账号。"
                )
            if not root_session_parts:
                root_session_parts = [root_session]
            for session_file in root_session_parts:
                target = output_dir / session_file.name
                try:
                    target.write_bytes(session_file.read_bytes())
                except Exception as exc:
                    raise RuntimeError(
                        f"无法复制登录会话到任务目录: {exc}"
                    ) from exc

        download_total = len(message_ids) if message_ids else None
        progress_state: dict = {
            "stage": "download",
            "status": "å‡†å¤‡ä¸‹è½½",
            "download": {},
            "upload": {},
            "files": {},
            "download_count": {"done": 0, "total": download_total},
            "upload_count": {"done": 0, "total": 0},
        }
        file_states: dict[str, dict] = {}
        skipped_ids: set[int] = set()
        failed_ids: set[int] = set()

        def update_progress(patch: dict) -> None:
            if "download" in patch and isinstance(patch["download"], dict):
                progress_state["download"].update(patch["download"])
            if "upload" in patch and isinstance(patch["upload"], dict):
                progress_state["upload"].update(patch["upload"])
            if "files" in patch and isinstance(patch["files"], dict):
                progress_state["files"].update(patch["files"])
            for key in ("status", "stage"):
                if key in patch:
                    progress_state[key] = patch[key]
            _update_task(int(task["id"]), progress_json=json.dumps(progress_state))

        def status_cb(msg: str) -> None:
            _write_task_log(int(task["id"]), msg)
            if msg.startswith("ä¸‹è½½å¤±è´¥ï¼š") and (
                "é‡è¯•ä¸­" in msg or "åˆ†ç‰‡ä¸‹è½½ä¸­" in msg
            ):
                update_progress({"status": "ä¸‹è½½ä¸­", "stage": "download"})
                return
            if (
                "Skipped (already in manifest):" in msg
                or "å·²å­˜åœ¨ï¼Œè·³è¿‡ï¼š" in msg
                or "è·³è¿‡å·²ç§»é™¤ï¼š" in msg
                or "å·²åˆ é™¤ï¼Œè·³è¿‡ï¼š" in msg
            ):
                try:
                    skipped_id = int(msg.split(":", 1)[1].strip())
                    skipped_ids.add(skipped_id)
                    done_count = sum(
                        1
                        for info in file_states.values()
                        if info.get("status") == "done"
                    )
                    started_count = len(file_states) + len(skipped_ids)
                    update_progress(
                        {
                            "status": msg,
                            "stage": "download",
                            "download_count": {
                                "done": max(done_count + len(skipped_ids), started_count),
                                "total": download_total,
                            },
                        }
                    )
                    return
                except Exception:
                    pass
            if "Failed (download error):" in msg or msg.startswith("ä¸‹è½½å¤±è´¥ï¼š"):
                try:
                    tail = msg.split(":", 1)[1].strip()
                    failed_id = int(tail.split()[0])
                    failed_ids.add(failed_id)
                    done_count = sum(
                        1
                        for info in file_states.values()
                        if info.get("status") == "done"
                    )
                    started_count = len(file_states) + len(skipped_ids) + len(failed_ids)
                    status_text = "å·²è¶…æ—¶" if "è¶…æ—¶" in msg or "timeout" in msg else msg
                    update_progress(
                        {
                            "status": status_text,
                            "stage": "download",
                            "download_count": {
                                "done": max(done_count + len(skipped_ids) + len(failed_ids), started_count),
                                "total": download_total,
                            },
                        }
                    )
                    return
                except Exception:
                    pass
            update_progress({"status": msg, "stage": "download"})

        def progress_cb(payload: dict) -> None:
            msg_id = payload.get("message_id")
            files_patch: dict[str, dict] = {}
            if msg_id is not None:
                key = str(msg_id)
                state = file_states.get(key, {})
                if not state:
                    state = {
                        "file_name": payload.get("file_name"),
                        "started_at": _utc_now(),
                        "status": "downloading",
                    }
                state["file_name"] = payload.get("file_name") or state.get("file_name")
                state["bytes_downloaded"] = payload.get("bytes_downloaded")
                state["bytes_total"] = payload.get("bytes_total")
                state["speed_bps"] = payload.get("speed_bps")
                if (
                    payload.get("bytes_total")
                    and payload.get("bytes_downloaded") is not None
                    and payload.get("bytes_downloaded") >= payload.get("bytes_total")
                ):
                    state["status"] = "done"
                    state["finished_at"] = _utc_now()
                file_states[key] = state
                files_patch = {key: state}
            total_bytes = 0
            downloaded_bytes = 0
            for info in file_states.values():
                bytes_total = info.get("bytes_total")
                bytes_downloaded = info.get("bytes_downloaded")
                if isinstance(bytes_total, (int, float)):
                    total_bytes += int(bytes_total)
                if isinstance(bytes_downloaded, (int, float)):
                    downloaded_bytes += int(bytes_downloaded)
            done_count = sum(
                1 for info in file_states.values() if info.get("status") == "done"
            )
            started_count = len(file_states) + len(skipped_ids)
            current_index = payload.get("current_index")
            if isinstance(current_index, (int, float)):
                started_count = max(started_count, int(current_index))
            update_progress(
                {
                    "download": {
                        **payload,
                        "task_bytes_downloaded": downloaded_bytes,
                        "task_bytes_total": total_bytes,
                    },
                    "stage": "download",
                    "files": files_patch,
                    "download_count": {
                        "done": max(done_count + len(skipped_ids), started_count),
                        "total": download_total,
                    },
                }
            )

        max_videos = len(message_ids) if message_ids else 1000000

        def _login_required() -> str:
            raise RuntimeError("æœåŠ¡å™¨æœªç™»å½• Telegramï¼Œè¯·å…ˆåœ¨æœåŠ¡å™¨æ‰§è¡Œ python server_login.py")

        def _do_download() -> None:
            run_download(
                channel=channel,
                max_videos=max_videos,
                output_dir=output_dir,
                api_id=api_id,
                api_hash=api_hash,
                start_date=_parse_date(task.get("start_date")),
                end_date=_parse_date(task.get("end_date")),
                status_cb=status_cb,
                progress_cb=progress_cb,
                stop_event=running.stop_event,
                allowed_ids=allowed_ids,
                skip_cb=running.is_removed,
                pause_cb=running.is_paused,
                min_video_duration_seconds=min_video_duration_seconds,
                get_phone_cb=_login_required,
                get_code_cb=_login_required,
                get_password_cb=_login_required,
                allow_prompt=False,
            )

        if bool(task.get("auto_upload")):
            def _do_direct_upload() -> None:
                asyncio.run(
                    self._run_direct_upload_async(
                        task=task,
                        running=running,
                        output_dir=output_dir,
                        channel=channel,
                        message_ids=message_ids,
                        api_id=api_id,
                        api_hash=api_hash,
                        download_total=download_total,
                        min_video_duration_seconds=min_video_duration_seconds,
                    )
                )

            _with_task_session_lock_sync(api_id, api_hash, output_dir, _do_direct_upload)
            return

        try:
            _with_task_session_lock_sync(api_id, api_hash, output_dir, _do_download)
        except Exception as exc:
            msg = str(exc)
            if "ç»ˆç«¯è¯»å–" in msg or "EOF" in msg or "è¾“å…¥" in msg:
                raise RuntimeError(
                    "æœåŠ¡å™¨æœªç™»å½• Telegramï¼Œè¯·å…ˆåŒæ­¥ session æˆ–æ‰§è¡Œ python server_login.py"
                ) from exc
            raise

        done_count = sum(
            1 for info in file_states.values() if info.get("status") == "done"
        )
        total_bytes = 0
        downloaded_bytes = 0
        for info in file_states.values():
            bytes_total = info.get("bytes_total")
            bytes_downloaded = info.get("bytes_downloaded")
            if isinstance(bytes_total, (int, float)):
                total_bytes += int(bytes_total)
            if isinstance(bytes_downloaded, (int, float)):
                downloaded_bytes += int(bytes_downloaded)
        done_total = done_count + len(skipped_ids) + len(failed_ids)
        if isinstance(download_total, int) and download_total > 0:
            done_total = max(done_total, download_total)
        if failed_ids and done_count == 0:
            update_progress(
                {
                    "status": "ä¸‹è½½å¤±è´¥",
                    "stage": "download",
                    "download": {
                        "task_bytes_downloaded": downloaded_bytes,
                        "task_bytes_total": total_bytes,
                    },
                    "download_count": {
                        "done": done_total,
                        "total": download_total,
                    },
                }
            )
            raise RuntimeError("ä¸‹è½½å¤±è´¥")
        update_progress(
            {
                "status": "ä¸‹è½½å®Œæˆ",
                "stage": "download",
                "download": {
                    "task_bytes_downloaded": downloaded_bytes,
                    "task_bytes_total": total_bytes,
                },
                "download_count": {
                    "done": done_total,
                    "total": download_total,
                },
            }
        )

        if running.stop_event.is_set():
            return

        auto_upload = bool(task.get("auto_upload"))
        if auto_upload:
            self._auto_upload(task, output_dir, message_ids, running.stop_event)

    async def _run_direct_upload_async(
        self,
        task: dict,
        running: RunningTask,
        output_dir: Path,
        channel: str,
        message_ids: list[int],
        api_id: str,
        api_hash: str,
        download_total: Optional[int],
        min_video_duration_seconds: int,
    ) -> None:
        config = _load_config()
        base_url = config.get("upload_base_url")
        account = config.get("upload_account") or ""
        password = config.get("upload_password") or ""
        upload_meta = bool(task.get("upload_meta"))
        min_video_duration_seconds = _task_min_video_duration_seconds(task, config)
        if not base_url:
            raise RuntimeError("æœªé…ç½®ä¸Šä¼ æœåŠ¡ï¼Œæ— æ³•ç›´æŽ¥ä¸Šä¼ ã€‚")

        target_message_ids: dict[str, str] = {}

        def upload_progress_cb(data: dict) -> None:
            file_name = str(data.get("file_name") or "")
            upload_key = target_message_ids.get(file_name)
            patch: dict = {
                "stage": "upload",
                "status": "ä¸Šä¼ ä¸­",
                "upload": data,
                "upload_video": data if data.get("is_video") else {},
            }
            if upload_key:
                sent = data.get("sent")
                total = data.get("total")
                patch["files"] = {
                    upload_key: {
                        "message_id": int(upload_key) if upload_key.isdigit() else upload_key,
                        "file_name": file_name,
                        "status": "uploading",
                        "bytes_downloaded": sent,
                        "bytes_total": total,
                        "upload_status": "uploading",
                        "upload_sent": sent,
                        "upload_total": total,
                        "upload_speed_bps": data.get("speed_bps"),
                    }
                }
            _merge_task_progress(int(task["id"]), patch)

        uploader = UploadClient(
            base_url=base_url,
            account=account,
            password=password,
            api_token=str(config.get("upload_api_token", "")).strip() or None,
            meta_url=config.get("video_meta_url"),
            movie_create_url=config.get("movie_create_url"),
            movie_category_default=config.get("movie_category_default"),
            debug=True,
            log_cb=lambda msg: _write_task_log(int(task["id"]), msg),
            progress_cb=upload_progress_cb,
        )

        async def _collect_messages(client: TelegramClient) -> list:
            entity = await _resolve_telegram_entity(client, channel)
            if message_ids:
                result = await client.get_messages(entity, ids=message_ids)
                if result is None:
                    return []
                if isinstance(result, (list, tuple)):
                    return [item for item in result if item is not None]
                return [result]

            start_date = _parse_date(task.get("start_date"))
            end_date = _parse_date(task.get("end_date"))
            collected = []
            async for message in client.iter_messages(entity, limit=100000):
                if message is None:
                    continue
                msg_date = message.date.date() if message.date else None
                if start_date and msg_date and msg_date < start_date:
                    break
                if end_date and msg_date and msg_date > end_date:
                    continue
                if _is_too_short_message(message, min_video_duration_seconds):
                    _write_task_log(
                        int(task["id"]),
                        f"视频时长小于 {min_video_duration_seconds} 秒，跳过：{getattr(message, 'id', '')} duration={_message_duration(message)}s",
                    )
                    continue
                if _is_uploadable_message(message, min_video_duration_seconds):
                    collected.append(message)
            return list(reversed(collected))

        client = _build_tracked_client(api_id, api_hash, output_dir, loop=asyncio.get_running_loop())
        await client.connect()
        try:
            authorized = await client.is_user_authorized()
            if not authorized:
                raise RuntimeError("æœåŠ¡å™¨æœªç™»å½• Telegramï¼Œè¯·å…ˆç™»å½•ã€‚")
            messages = []
            for msg in await _collect_messages(client):
                if _is_too_short_message(msg, min_video_duration_seconds):
                    _write_task_log(
                        int(task["id"]),
                        f"视频时长小于 {min_video_duration_seconds} 秒，跳过：{getattr(msg, 'id', '')} duration={_message_duration(msg)}s",
                    )
                    continue
                if _is_uploadable_message(msg, min_video_duration_seconds):
                    messages.append(msg)
            total_upload = len(messages)
            _merge_task_progress(
                int(task["id"]),
                {
                    "stage": "upload",
                    "status": "å‡†å¤‡ç›´æŽ¥ä¸Šä¼ ",
                    "download_count": {"done": 0, "total": download_total or total_upload},
                    "upload_count": {"done": 0, "total": total_upload},
                },
            )
            if not messages:
                raise RuntimeError("æœªæ‰¾åˆ°å¯ç›´æŽ¥ä¸Šä¼ çš„è§†é¢‘ã€‚")

            threshold_seconds = task.get("video_type_threshold_seconds")
            if threshold_seconds is None:
                threshold_seconds = config.get("video_type_threshold_seconds")
            try:
                threshold_seconds = int(threshold_seconds)
            except (TypeError, ValueError):
                threshold_seconds = DEFAULT_VIDEO_TYPE_THRESHOLD_SECONDS

            done_upload = 0
            for index, message in enumerate(messages, start=1):
                if running.stop_event.is_set():
                    return
                if running.is_removed(int(message.id)):
                    _write_task_log(int(task["id"]), f"跳过已移除：{message.id}")
                    continue
                while running.is_paused(int(message.id)):
                    await asyncio.sleep(1)

                file_name = pick_file_name(message, channel)
                total_bytes = _message_file_size(message)
                if total_bytes <= 0:
                    _write_task_log(int(task["id"]), f"文件大小未知，跳过直传：{message.id}")
                    continue
                content_type = _message_mime_type(message)
                caption_text = await _resolve_message_caption(client, channel, message)
                if is_filtered_caption(caption_text):
                    _write_task_log(int(task["id"]), f"简介命中过滤规则，跳过：{message.id}")
                    continue
                upload_key = str(message.id)
                target_message_ids[file_name] = upload_key
                uploaded = _fetch_uploaded_video(channel, int(message.id))
                if uploaded:
                    done_upload += 1
                    upload_id = int(uploaded.get("upload_id") or 0)
                    _write_task_log(
                        int(task["id"]),
                        f"视频已上传，跳过：{channel}#{message.id} upload_id={upload_id} md5={uploaded.get('content_md5') or '-'}",
                    )
                    _merge_task_progress(
                        int(task["id"]),
                        {
                            "stage": "upload",
                            "status": "ä¸Šä¼ å®Œæˆ" if done_upload >= total_upload else "ä¸Šä¼ ä¸­",
                            "download_count": {"done": done_upload, "total": download_total or total_upload},
                            "upload_count": {"done": done_upload, "total": total_upload},
                            "files": {
                                upload_key: {
                                    "message_id": int(message.id),
                                    "file_name": uploaded.get("file_name") or file_name,
                                    "status": "done",
                                    "bytes_downloaded": uploaded.get("file_size") or total_bytes,
                                    "bytes_total": uploaded.get("file_size") or total_bytes,
                                    "upload_status": "done",
                                    "upload_sent": uploaded.get("file_size") or total_bytes,
                                    "upload_total": uploaded.get("file_size") or total_bytes,
                                    "upload_speed_bps": None,
                                    "upload_id": upload_id,
                                    "deduped": True,
                                }
                            },
                        },
                    )
                    continue
                _merge_task_progress(
                    int(task["id"]),
                    {
                        "stage": "upload",
                        "status": f"ç›´æŽ¥ä¸Šä¼ ä¸­ ({index}/{total_upload}): {file_name}",
                        "files": {
                            upload_key: {
                                "message_id": int(message.id),
                                "file_name": file_name,
                                "status": "uploading",
                                "caption": caption_text,
                                "tags": extract_tags(caption_text),
                                "duration": _message_duration(message),
                                "bytes_downloaded": 0,
                                "bytes_total": total_bytes,
                                "upload_status": "uploading",
                                "upload_sent": 0,
                                "upload_total": total_bytes,
                            }
                        },
                    },
                )

                def _flood_wait_seconds(exc: BaseException) -> Optional[int]:
                    raw = getattr(exc, "seconds", None)
                    if raw is None:
                        raw = getattr(exc, "value", None)
                    try:
                        return max(1, int(raw))
                    except (TypeError, ValueError):
                        pass
                    text = " ".join(
                        str(part or "")
                        for part in (
                            getattr(exc, "message", None),
                            getattr(exc, "name", None),
                            str(exc),
                        )
                    ).upper()
                    match = re.search(r"FLOOD(?:_[A-Z]+)*_WAIT_(\d+)", text)
                    if match:
                        return max(1, int(match.group(1)))
                    if getattr(exc, "code", None) == 420 and "FLOOD" in text:
                        return 60
                    return None

                async def _sleep_for_flood_wait(exc: BaseException, sent_from_telegram: int) -> None:
                    seconds = _flood_wait_seconds(exc)
                    if seconds is None:
                        raise exc
                    wait_text = f"Telegram 限流，等待 {seconds} 秒后继续：{message.id}"
                    _write_task_log(int(task["id"]), wait_text)
                    _merge_task_progress(
                        int(task["id"]),
                        {
                            "stage": "upload",
                            "status": wait_text,
                            "files": {
                                upload_key: {
                                    "message_id": int(message.id),
                                    "file_name": file_name,
                                    "status": "waiting",
                                    "upload_status": "waiting",
                                    "bytes_downloaded": sent_from_telegram,
                                    "bytes_total": total_bytes,
                                    "upload_sent": sent_from_telegram,
                                    "upload_total": total_bytes,
                                }
                            },
                        },
                    )
                    await asyncio.sleep(seconds + 1)

                def _is_file_reference_expired(exc: BaseException) -> bool:
                    text = " ".join(
                        str(part or "")
                        for part in (
                            getattr(exc, "message", None),
                            getattr(exc, "name", None),
                            str(exc),
                        )
                    ).lower()
                    return (
                        "file reference" in text
                        and (
                            "expired" in text
                            or "no longer valid" in text
                            or "self-destructing" in text
                        )
                    )

                file_reference_refresh_count = 0
                max_file_reference_refreshes = max(
                    1, int(os.getenv("TELEGRAM_FILE_REFERENCE_REFRESHES", "5"))
                )

                async def _refresh_message_media(reason: str, sent_from_telegram: int = 0) -> None:
                    nonlocal message, total_bytes, content_type, file_reference_refresh_count
                    file_reference_refresh_count += 1
                    if file_reference_refresh_count > max_file_reference_refreshes:
                        raise RuntimeError(
                            f"Telegram 文件引用刷新超过上限：{message.id}，请稍后重试。"
                        )
                    refresh_text = (
                        f"Telegram 文件引用过期，刷新消息后继续：{message.id} "
                        f"({file_reference_refresh_count}/{max_file_reference_refreshes}) reason={reason}"
                    )
                    _write_task_log(int(task["id"]), refresh_text)
                    _merge_task_progress(
                        int(task["id"]),
                        {
                            "stage": "upload",
                            "status": refresh_text,
                            "files": {
                                upload_key: {
                                    "message_id": int(message.id),
                                    "file_name": file_name,
                                    "status": "refreshing",
                                    "upload_status": "refreshing",
                                    "bytes_downloaded": sent_from_telegram,
                                    "bytes_total": total_bytes,
                                    "upload_sent": sent_from_telegram,
                                    "upload_total": total_bytes,
                                }
                            },
                        },
                    )
                    entity = await _resolve_telegram_entity(client, channel)
                    refreshed = await client.get_messages(entity, ids=int(message.id))
                    if isinstance(refreshed, (list, tuple)):
                        refreshed = next((item for item in refreshed if item is not None), None)
                    if not refreshed or not getattr(refreshed, "media", None):
                        raise RuntimeError(f"Telegram 文件引用刷新失败：{message.id}")
                    message = refreshed
                    refreshed_size = _message_file_size(message)
                    if refreshed_size > 0:
                        total_bytes = refreshed_size
                    content_type = _message_mime_type(message) or content_type

                async def _next_telegram_chunk(offset: int = 0, sent_from_telegram: int = 0):
                    while True:
                        try:
                            aiter = client.iter_download(
                                message.media,
                                offset=offset,
                                chunk_size=512 * 1024,
                            )
                            chunk = await aiter.__anext__()
                            return aiter, bytes(chunk)
                        except StopAsyncIteration:
                            return None, b""
                        except (FloodWaitError, RPCError) as exc:
                            if _is_file_reference_expired(exc):
                                await _refresh_message_media("start-chunk", sent_from_telegram)
                                continue
                            await _sleep_for_flood_wait(exc, sent_from_telegram)

                async def _hash_telegram_media() -> tuple[Optional[str], int]:
                    digest = hashlib.md5()
                    hashed = 0
                    aiter, first_chunk = await _next_telegram_chunk(0, hashed)
                    if first_chunk:
                        hashed += len(first_chunk)
                        digest.update(first_chunk)
                    while aiter is not None:
                        try:
                            while True:
                                try:
                                    chunk = await aiter.__anext__()
                                except StopAsyncIteration:
                                    break
                                if running.stop_event.is_set():
                                    raise RuntimeError("任务已取消")
                                chunk_bytes = bytes(chunk)
                                hashed += len(chunk_bytes)
                                digest.update(chunk_bytes)
                            break
                        except (FloodWaitError, RPCError) as exc:
                            if _is_file_reference_expired(exc):
                                await _refresh_message_media("md5", hashed)
                            else:
                                await _sleep_for_flood_wait(exc, hashed)
                            aiter, first_chunk = await _next_telegram_chunk(hashed, hashed)
                            if first_chunk:
                                hashed += len(first_chunk)
                                digest.update(first_chunk)
                    return (digest.hexdigest() if hashed > 0 else None), hashed

                _merge_task_progress(
                    int(task["id"]),
                    {
                        "stage": "upload",
                        "status": f"计算MD5 ({index}/{total_upload}): {file_name}",
                    },
                )
                _write_task_log(
                    int(task["id"]),
                    f"MD5加密源数据：source=Telegram直传预检 channel={channel} message_id={message.id} file={file_name} bytes={total_bytes} mime={content_type}",
                )
                content_md5, hashed_bytes = await _hash_telegram_media()
                _write_task_log(
                    int(task["id"]),
                    f"MD5加密结果：source=Telegram直传预检 file={file_name} hashed_bytes={hashed_bytes} md5={content_md5 or '-'}",
                )
                duplicate = _fetch_uploaded_video_by_md5(content_md5)
                if duplicate:
                    done_upload += 1
                    upload_id = int(duplicate.get("upload_id") or 0)
                    _write_task_log(
                        int(task["id"]),
                        f"MD5重复，跳过直传：{file_name} md5={content_md5} 已存在 {duplicate.get('channel')}#{duplicate.get('message_id')} upload_id={upload_id}",
                    )
                    _record_uploaded_video(channel, int(message.id), file_name, total_bytes, upload_id, content_md5)
                    _merge_task_progress(
                        int(task["id"]),
                        {
                            "stage": "upload",
                            "status": "上传完成" if done_upload >= total_upload else "上传中",
                            "download_count": {"done": done_upload, "total": download_total or total_upload},
                            "upload_count": {"done": done_upload, "total": total_upload},
                            "files": {
                                upload_key: {
                                    "message_id": int(message.id),
                                    "file_name": file_name,
                                    "caption": caption_text,
                                    "tags": extract_tags(caption_text),
                                    "duration": _message_duration(message),
                                    "status": "done",
                                    "bytes_downloaded": total_bytes,
                                    "bytes_total": total_bytes,
                                    "upload_status": "done",
                                    "upload_sent": total_bytes,
                                    "upload_total": total_bytes,
                                    "upload_speed_bps": None,
                                    "upload_id": upload_id,
                                    "content_md5": content_md5,
                                    "deduped": True,
                                    "dedupe_source": {
                                        "channel": duplicate.get("channel"),
                                        "message_id": duplicate.get("message_id"),
                                    },
                                }
                            },
                        },
                    )
                    continue

                async def _direct_upload_once(attempt: int) -> tuple[int, str, int]:
                    chunks: "queue.Queue[object]" = queue.Queue(maxsize=8)
                    reader = QueueReader(chunks)
                    upload_result: dict[str, object] = {}
                    producer_error: Optional[BaseException] = None
                    sent_from_telegram = 0
                    md5_digest = hashlib.md5()

                    async def _put_queue_item(item: object) -> None:
                        while True:
                            if upload_result.get("error"):
                                raise upload_result["error"]  # type: ignore[misc]
                            try:
                                chunks.put(item, timeout=0.5)
                                return
                            except queue.Full:
                                await asyncio.sleep(0.1)

                    def _upload_worker() -> None:
                        try:
                            upload_result["upload_id"] = uploader.upload_video_reader(
                                file_name=file_name,
                                reader=reader,
                                total=total_bytes,
                                content_type=content_type,
                            )
                        except BaseException as exc:
                            upload_result["error"] = exc

                    thread = threading.Thread(target=_upload_worker, daemon=True)
                    try:
                        aiter, first_chunk = await _next_telegram_chunk(0, sent_from_telegram)
                        if aiter is not None:
                            thread.start()
                        elif aiter is None:
                            thread.start()
                        if first_chunk:
                            sent_from_telegram += len(first_chunk)
                            md5_digest.update(first_chunk)
                            await _put_queue_item(first_chunk)

                        while aiter is not None:
                            try:
                                while True:
                                    try:
                                        chunk = await aiter.__anext__()
                                    except StopAsyncIteration:
                                        break
                                    if running.stop_event.is_set():
                                        raise RuntimeError("任务已取消")
                                    chunk_bytes = bytes(chunk)
                                    sent_from_telegram += len(chunk_bytes)
                                    md5_digest.update(chunk_bytes)
                                    await _put_queue_item(chunk_bytes)
                                break
                            except (FloodWaitError, RPCError) as exc:
                                if _is_file_reference_expired(exc):
                                    await _refresh_message_media(
                                        f"upload-attempt-{attempt}", sent_from_telegram
                                    )
                                else:
                                    await _sleep_for_flood_wait(exc, sent_from_telegram)
                                aiter, first_chunk = await _next_telegram_chunk(
                                    sent_from_telegram, sent_from_telegram
                                )
                                if first_chunk:
                                    sent_from_telegram += len(first_chunk)
                                    md5_digest.update(first_chunk)
                                    await _put_queue_item(first_chunk)
                    except BaseException as exc:
                        producer_error = exc
                        try:
                            await _put_queue_item(exc)
                        except BaseException:
                            pass
                    finally:
                        try:
                            await _put_queue_item(None)
                        except BaseException:
                            pass
                        if thread.is_alive():
                            await asyncio.to_thread(thread.join)

                    if producer_error:
                        raise producer_error
                    if upload_result.get("error"):
                        raise upload_result["error"]  # type: ignore[misc]
                    return (
                        int(upload_result.get("upload_id") or 0),
                        md5_digest.hexdigest(),
                        sent_from_telegram,
                    )

                max_direct_upload_attempts = max(
                    1, int(os.getenv("DIRECT_UPLOAD_RETRIES", "3"))
                )
                upload_id = 0
                content_md5 = None
                hashed_bytes = 0
                for attempt in range(1, max_direct_upload_attempts + 1):
                    try:
                        _write_task_log(
                            int(task["id"]),
                            f"MD5加密源数据：source=Telegram直传上传 attempt={attempt} channel={channel} message_id={message.id} file={file_name} bytes={total_bytes} mime={content_type}",
                        )
                        upload_id, content_md5, hashed_bytes = await _direct_upload_once(attempt)
                        _write_task_log(
                            int(task["id"]),
                            f"MD5加密结果：source=Telegram直传上传 attempt={attempt} file={file_name} hashed_bytes={hashed_bytes} md5={content_md5 or '-'}",
                        )
                        break
                    except Exception as exc:
                        if running.stop_event.is_set() or attempt >= max_direct_upload_attempts:
                            raise
                        retry_text = (
                            f"直传失败，准备重试 {attempt}/{max_direct_upload_attempts - 1}：{exc}"
                        )
                        _write_task_log(int(task["id"]), retry_text)
                        _merge_task_progress(
                            int(task["id"]),
                            {
                                "stage": "upload",
                                "status": retry_text,
                                "files": {
                                    upload_key: {
                                        "message_id": int(message.id),
                                        "file_name": file_name,
                                        "status": "retrying",
                                        "upload_status": "retrying",
                                        "upload_sent": 0,
                                        "upload_total": total_bytes,
                                    }
                                },
                            },
                        )
                        await asyncio.sleep(min(30, attempt * 5))

                duplicate = _fetch_uploaded_video_by_md5(content_md5)
                if duplicate and str(duplicate.get("channel")) != str(channel):
                    _write_task_log(
                        int(task["id"]),
                        f"MD5重复：{file_name} md5={content_md5} 已存在 {duplicate.get('channel')}#{duplicate.get('message_id')} upload_id={duplicate.get('upload_id')}",
                    )
                _record_uploaded_video(channel, int(message.id), file_name, total_bytes, upload_id, content_md5)
                _write_task_log(
                    int(task["id"]),
                    f"直传上传完成：{file_name} upload_id={upload_id} md5={content_md5 or '-'}",
                )
                done_upload += 1
                caption = caption_text or await _resolve_message_caption(client, channel, message)
                tags = extract_tags(caption)
                duration = _message_duration(message)
                _merge_task_progress(
                    int(task["id"]),
                    {
                        "stage": "upload",
                        "status": "ä¸Šä¼ å®Œæˆ" if done_upload >= total_upload else "ä¸Šä¼ ä¸­",
                        "download_count": {"done": done_upload, "total": download_total or total_upload},
                        "upload_count": {"done": done_upload, "total": total_upload},
                        "files": {
                            upload_key: {
                                "message_id": int(message.id),
                                "file_name": file_name,
                                "caption": caption,
                                "description": caption,
                                "tags": tags,
                                "duration": duration,
                                "status": "done",
                                "bytes_downloaded": total_bytes,
                                "bytes_total": total_bytes,
                                "upload_status": "done",
                                "upload_sent": total_bytes,
                                "upload_total": total_bytes,
                                "upload_speed_bps": None,
                                "upload_id": upload_id,
                                "content_md5": content_md5,
                            }
                        },
                    },
                )

                if upload_meta:
                    content = caption or Path(file_name).stem
                    video_type = (
                        "short"
                        if isinstance(duration, int) and duration <= threshold_seconds
                        else "long"
                    )
                    if video_type == "long" and uploader.movie_create_url:
                        try:
                            thumbnail_id = await _upload_message_thumbnail(
                                message, int(task["id"]), uploader
                            )
                            if thumbnail_id <= 0:
                                _write_task_log(
                                    int(task["id"]),
                                    f"未获取到封面，继续创建影片记录：{message.id}",
                                )
                            movie_title = _movie_title_from_content(
                                content, Path(file_name).stem
                            )
                            _write_task_log(
                                int(task["id"]),
                                f"影片标题同步：title_len={len(movie_title)} content_len={len(content)} same={movie_title == content}",
                            )
                            uploader.create_movie_record(
                                title=movie_title,
                                category=config.get("movie_category_default") or "çºªå½•ç‰‡",
                                content=content,
                                tags=tags,
                                thumbnail_id=thumbnail_id,
                                video_id=upload_id,
                            )
                        except Exception as exc:
                            _write_task_log(int(task["id"]), f"影片记录失败: {exc}")
                    elif video_type == "short" and uploader.meta_url:
                        try:
                            thumbnail_id = await _upload_message_thumbnail(
                                message, int(task["id"]), uploader
                            )
                            if thumbnail_id <= 0:
                                _write_task_log(
                                    int(task["id"]),
                                    f"未获取到封面，短视频记录可能无缩略图：{message.id}",
                                )
                            uploader.create_video_record(
                                video_id=upload_id,
                                content=content,
                                tags=tags,
                                video_type=video_type,
                                thumbnail_id=thumbnail_id,
                            )
                        except Exception as exc:
                            _write_task_log(int(task["id"]), f"短视频记录失败: {exc}")

        finally:
            await _shield_close_client(client)

    def _auto_upload(
        self,
        task: dict,
        output_dir: Path,
        message_ids: list[int],
        stop_event: Optional[threading.Event] = None,
    ) -> None:
        config = _load_config()
        base_url = config.get("upload_base_url")
        account = config.get("upload_account") or ""
        password = config.get("upload_password") or ""
        upload_meta = bool(task.get("upload_meta"))
        if not base_url:
            _write_task_log(int(task["id"]), "未配置上传账号，跳过上传。")
            return

        target_message_ids: dict[str, str] = {}

        def upload_progress_cb(data: dict) -> None:
            patch: dict = {
                "stage": "upload",
                "status": "Ã¤Â¸Å Ã¤Â¼Â Ã¤Â¸Â­",
                "upload": data,
                "upload_video": data if data.get("is_video") else {},
            }
            file_name = str(data.get("file_name") or "")
            upload_key = target_message_ids.get(file_name)
            if upload_key and data.get("is_video"):
                patch["files"] = {
                    upload_key: {
                        "message_id": int(upload_key) if upload_key.isdigit() else upload_key,
                        "file_name": file_name,
                        "upload_status": "uploading",
                        "upload_sent": data.get("sent"),
                        "upload_total": data.get("total"),
                        "upload_speed_bps": data.get("speed_bps"),
                    }
                }
            _merge_task_progress(int(task["id"]), patch)

        uploader = UploadClient(
            base_url=base_url,
            account=account,
            password=password,
            api_token=str(config.get("upload_api_token", "")).strip() or None,
            meta_url=config.get("video_meta_url"),
            movie_create_url=config.get("movie_create_url"),
            movie_category_default=config.get("movie_category_default"),
            debug=True,
            log_cb=lambda msg: _write_task_log(int(task["id"]), msg),
            progress_cb=lambda data: _merge_task_progress(
                int(task["id"]),
                {
                    "stage": "upload",
                    "status": "ä¸Šä¼ ä¸­",
                    "upload": data,
                    "upload_video": data if data.get("is_video") else {},
                },
            ),
        )

        manifest = read_manifest(output_dir)
        targets: list[Path] = []
        target_message_ids: dict[str, str] = {}
        if message_ids:
            wanted = {str(mid) for mid in message_ids}
            for row in manifest:
                if row.get("message_id") in wanted:
                    local_path = row.get("local_path") or ""
                    if local_path:
                        target_path = Path(local_path)
                        targets.append(target_path)
                        target_message_ids[target_path.name] = str(row.get("message_id"))
        else:
            for row in manifest:
                local_path = row.get("local_path") or ""
                if local_path:
                    target_path = Path(local_path)
                    targets.append(target_path)
                    if row.get("message_id"):
                        target_message_ids[target_path.name] = str(row.get("message_id"))

        if not targets:
            _write_task_log(int(task["id"]), "未找到可上传文件。")
            return
        total_upload = len(targets)
        _merge_task_progress(
            int(task["id"]),
            {
                "stage": "upload",
                "status": "å‡†å¤‡ä¸Šä¼ ",
                "upload_count": {"done": 0, "total": total_upload},
            },
        )

        threshold_seconds = task.get("video_type_threshold_seconds")
        if threshold_seconds is None:
            threshold_seconds = config.get("video_type_threshold_seconds")
        try:
            threshold_seconds = int(threshold_seconds)
        except (TypeError, ValueError):
            threshold_seconds = DEFAULT_VIDEO_TYPE_THRESHOLD_SECONDS
        done_upload = 0
        for index, path in enumerate(targets, start=1):
            if stop_event is not None and stop_event.is_set():
                _write_task_log(int(task["id"]), "收到取消请求，停止后续本地文件上传。")
                return
            if not path.exists():
                _write_task_log(int(task["id"]), f"文件不存在，跳过上传: {path}")
                continue
            expected_size = None
            target_meta: dict = {}
            meta_path = output_dir / f"{path.stem}.json"
            if meta_path.exists():
                try:
                    target_meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    expected_size = target_meta.get("file_size")
                except Exception:
                    expected_size = None
                    target_meta = {}
            if isinstance(expected_size, (int, float)) and expected_size > 0:
                actual_size = path.stat().st_size
                if actual_size < expected_size * 0.98:
                    _write_task_log(
                        int(task["id"]),
                        f"æ–‡ä»¶ä¸å®Œæ•´ï¼Œè·³è¿‡ä¸Šä¼ : {path.name} ({actual_size}/{int(expected_size)})",
                    )
                    continue
            duration_value = target_meta.get("duration")
            try:
                duration_seconds = int(duration_value) if duration_value is not None else None
            except (TypeError, ValueError):
                duration_seconds = None
            if duration_seconds is not None and duration_seconds < min_video_duration_seconds:
                _write_task_log(
                    int(task["id"]),
                    f"视频时长小于 {min_video_duration_seconds} 秒，跳过上传：{path.name} duration={duration_seconds}s",
                )
                continue
            _merge_task_progress(
                int(task["id"]),
                {
                    "stage": "upload",
                    "status": f"ä¸Šä¼ ä¸­ ({index}/{total_upload}): {path.name}",
                    "upload": {},
                },
            )
            upload_key = target_message_ids.get(path.name)
            if upload_key:
                _merge_task_progress(
                    int(task["id"]),
                    {
                        "files": {
                            upload_key: {
                                "message_id": int(upload_key) if upload_key.isdigit() else upload_key,
                                "file_name": path.name,
                                "upload_status": "uploading",
                                "upload_sent": 0,
                                "upload_total": path.stat().st_size,
                                "upload_speed_bps": None,
                            }
                        }
                    },
                )
            actual_size = path.stat().st_size
            _write_task_log(
                int(task["id"]),
                f"MD5加密源数据：source=本地文件 path={path} file={path.name} bytes={actual_size}",
            )
            content_md5 = _file_content_md5(path)
            _write_task_log(
                int(task["id"]),
                f"MD5加密结果：source=本地文件 file={path.name} hashed_bytes={actual_size} md5={content_md5 or '-'}",
            )
            duplicate = _fetch_uploaded_video_by_md5(content_md5)
            if duplicate:
                done_upload += 1
                upload_id = int(duplicate.get("upload_id") or 0)
                _write_task_log(
                    int(task["id"]),
                    f"MD5重复，跳过上传：{path.name} md5={content_md5} 已存在 {duplicate.get('channel')}#{duplicate.get('message_id')} upload_id={upload_id}",
                )
                if upload_key:
                    _record_uploaded_video(
                        str(task.get("channel") or ""),
                        int(upload_key),
                        path.name,
                        path.stat().st_size,
                        upload_id,
                        content_md5,
                    )
                    _merge_task_progress(
                        int(task["id"]),
                        {
                            "stage": "upload",
                            "status": "上传完成" if done_upload >= total_upload else "上传中",
                            "upload_count": {"done": done_upload, "total": total_upload},
                            "files": {
                                upload_key: {
                                    "message_id": int(upload_key) if upload_key.isdigit() else upload_key,
                                    "file_name": path.name,
                                    "upload_status": "done",
                                    "upload_sent": path.stat().st_size,
                                    "upload_total": path.stat().st_size,
                                    "upload_speed_bps": None,
                                    "upload_id": upload_id,
                                    "content_md5": content_md5,
                                    "deduped": True,
                                    "dedupe_source": {
                                        "channel": duplicate.get("channel"),
                                        "message_id": duplicate.get("message_id"),
                                    },
                                }
                            },
                        },
                    )
                continue
            upload_id = uploader.upload_video_file(path)
            if upload_key:
                _record_uploaded_video(
                    str(task.get("channel") or ""),
                    int(upload_key),
                    path.name,
                    path.stat().st_size,
                    upload_id,
                    content_md5,
                )
            _write_task_log(
                int(task["id"]),
                f"本地上传完成：{path.name} upload_id={upload_id} md5={content_md5 or '-'}",
            )
            if upload_key:
                _merge_task_progress(
                    int(task["id"]),
                    {
                        "files": {
                            upload_key: {
                                "message_id": int(upload_key) if upload_key.isdigit() else upload_key,
                                "file_name": path.name,
                                "upload_status": "done",
                                "upload_sent": path.stat().st_size,
                                "upload_total": path.stat().st_size,
                                "upload_speed_bps": None,
                                "upload_id": upload_id,
                                "content_md5": content_md5,
                            }
                        }
                    },
                )
            if upload_meta:
                meta_path = output_dir / f"{path.stem}.json"
                content = ""
                tags: list[str] = []
                duration = None
                title = path.stem
                category = config.get("movie_category_default") or ""
                extra_images: list[str] = []
                if meta_path.exists():
                    try:
                        meta = target_meta or json.loads(meta_path.read_text(encoding="utf-8"))
                        content = str(meta.get("caption") or meta.get("description") or "")
                        raw_title = str(meta.get("title") or title)
                        title = Path(raw_title).stem or raw_title
                        category = str(meta.get("category") or category)
                        raw_tags = meta.get("tags") or []
                        if isinstance(raw_tags, list):
                            tags = [str(item) for item in raw_tags]
                        elif isinstance(raw_tags, str):
                            tags = [item.strip() for item in raw_tags.split(",") if item.strip()]
                        duration = meta.get("duration")
                        raw_images = meta.get("extra_images") or []
                        if isinstance(raw_images, list):
                            extra_images = [str(item) for item in raw_images if item]
                    except Exception as exc:
                        _write_task_log(int(task["id"]), f"读取视频元数据失败: {exc}")
                if not content:
                    content = title
                video_type = "short" if isinstance(duration, (int, float)) and duration <= threshold_seconds else "long"
                thumb_id = 0
                extra_image_ids: list[int] = []
                for rel in extra_images:
                    img_path = output_dir / rel
                    if not img_path.exists():
                        continue
                    try:
                        img_id = uploader.upload_image_file(img_path)
                        extra_image_ids.append(img_id)
                        if thumb_id == 0:
                            thumb_id = img_id
                    except Exception as exc:
                        _write_task_log(
                            int(task["id"]), f"å›¾ç‰‡ä¸Šä¼ å¤±è´¥({img_path.name}): {exc}"
                        )
                thumb_paths = (
                    sorted(output_dir.glob(f"{path.stem}_thumb_*.jpg"))
                    + sorted(output_dir.glob(f"{path.stem}_thumb_*.jpeg"))
                    + sorted(output_dir.glob(f"{path.stem}_thumb_*.png"))
                    + sorted(output_dir.glob(f"{path.stem}_thumb_*.webp"))
                )
                for idx, thumb_path in enumerate(thumb_paths):
                    try:
                        uploaded_id = uploader.upload_image_file(thumb_path)
                        if idx == 0 and thumb_id == 0:
                            thumb_id = uploaded_id
                    except Exception as exc:
                        _write_task_log(
                            int(task["id"]), f"å°é¢ä¸Šä¼ å¤±è´¥({thumb_path.name}): {exc}"
                        )
                if thumb_id == 0:
                    auto_thumb = output_dir / f"{path.stem}_auto_thumb.jpg"
                    if _extract_video_frame(path, auto_thumb, duration):
                        try:
                            thumb_id = uploader.upload_image_file(auto_thumb)
                        except Exception as exc:
                            _write_task_log(
                                int(task["id"]),
                                f"è‡ªåŠ¨å°é¢ä¸Šä¼ å¤±è´¥({auto_thumb.name}): {exc}",
                            )
                    else:
                        _write_task_log(
                            int(task["id"]), "æœªæ‰¾åˆ°å›¾ç‰‡ä¸”è‡ªåŠ¨æŠ½å¸§å¤±è´¥ï¼Œè·³è¿‡å°é¢ã€‚"
                        )
                if video_type == "long":
                    if uploader.movie_create_url:
                        try:
                            movie_title = _movie_title_from_content(
                                content, title or path.stem
                            )
                            _write_task_log(
                                int(task["id"]),
                                f"影片标题同步：title_len={len(movie_title)} content_len={len(content)} same={movie_title == content}",
                            )
                            uploader.create_movie_record(
                                title=movie_title,
                                category=category or "çºªå½•ç‰‡",
                                content=content,
                                tags=tags,
                                thumbnail_id=thumb_id,
                                video_id=upload_id,
                            )
                        except Exception as exc:
                            _write_task_log(int(task["id"]), f"影片记录失败: {exc}")
                    else:
                        _write_task_log(int(task["id"]), "未配置长视频接口，跳过影片记录。")
                else:
                    if uploader.meta_url:
                        try:
                            uploader.create_video_record(
                                video_id=upload_id,
                                content=content,
                                tags=tags,
                                video_type=video_type,
                                thumbnail_id=thumb_id,
                            )
                        except Exception as exc:
                            _write_task_log(int(task["id"]), f"短视频记录失败: {exc}")
                    else:
                        _write_task_log(int(task["id"]), "未配置短视频接口，跳过短视频记录。")
            done_upload += 1
            status_text = "ä¸Šä¼ å®Œæˆ" if done_upload >= total_upload else "ä¸Šä¼ ä¸­"
            _merge_task_progress(
                int(task["id"]),
                {
                    "stage": "upload",
                    "status": status_text,
                    "upload_count": {"done": done_upload, "total": total_upload},
                },
            )


def _parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


_ensure_db()
task_runner = TaskRunner()

app = FastAPI()


@app.on_event("startup")
async def _start_task_runner() -> None:
    # Start only after this module has finished defining the Telegram helpers.
    task_runner.start()

_cors_origins = [
    "http://localhost:9528",
    "http://127.0.0.1:9528",
]
extra_origins = os.getenv("SERVER_CORS_ORIGINS", "").strip()
if extra_origins:
    _cors_origins.extend(
        origin.strip() for origin in extra_origins.split(",") if origin.strip()
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
if WEB_DIR.exists():
    app.mount("/web", StaticFiles(directory=WEB_DIR, html=True), name="web")


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": _repair_mojibake_value(exc.detail)},
        headers=exc.headers,
    )


@app.get("/")
def web_index() -> FileResponse:
    index_path = WEB_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    raise HTTPException(status_code=404, detail="Web UI not found")


@app.websocket("/ws/tasks")
async def ws_tasks(websocket: WebSocket) -> None:
    expected = _get_api_token()
    if expected:
        token = websocket.query_params.get("token", "")
        auth = websocket.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth.split(" ", 1)[1].strip()
        if token != expected:
            await websocket.close(code=1008)
            return
    await ws_manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)


class TaskRequest(BaseModel):
    channel: str = Field(..., description="Telegram channel username or t.me link")
    api_id: Optional[str] = None
    api_hash: Optional[str] = None
    upload_base_url: Optional[str] = None
    upload_account: Optional[str] = None
    upload_password: Optional[str] = None
    upload_api_token: Optional[str] = None
    message_ids: list[int] = Field(default_factory=list)
    start_date: Optional[str] = Field(default=None, description="YYYY-MM-DD")
    end_date: Optional[str] = Field(default=None, description="YYYY-MM-DD")
    output_dir: Optional[str] = None
    video_type_threshold_seconds: Optional[int] = None
    min_video_duration_seconds: Optional[int] = None
    auto_upload: Optional[bool] = None
    upload_meta: Optional[bool] = None
    force_upload: Optional[bool] = None


class LoginRequest(BaseModel):
    api_id: str
    api_hash: str
    output_dir: Optional[str] = None
    phone: str


class VerifyRequest(BaseModel):
    api_id: str
    api_hash: str
    output_dir: Optional[str] = None
    phone: str
    code: str
    password: Optional[str] = None


class PreviewRequest(BaseModel):
    api_id: str
    api_hash: str
    output_dir: str
    channel: str
    limit: Optional[int] = None
    offset: int = 0
    offset_id: Optional[int] = None
    min_video_duration_seconds: Optional[int] = None


class RemoveItemsRequest(BaseModel):
    message_ids: list[int] = Field(default_factory=list)


class PauseRequest(BaseModel):
    message_id: int
    pause: bool = True


class DeleteCompletedRequest(BaseModel):
    output_dir: str
    message_id: int


class ExternalVideoLibraryUploadRequest(BaseModel):
    payload: object
    category: Optional[str] = None
    limit: Optional[int] = None


class ConfigUpdateRequest(BaseModel):
    telegram_api_id: Optional[str] = None
    telegram_api_hash: Optional[str] = None
    download_root: Optional[str] = None
    telegram_download_concurrency: Optional[int] = None
    upload_base_url: Optional[str] = None
    upload_account: Optional[str] = None
    upload_password: Optional[str] = None
    upload_api_token: Optional[str] = None
    video_type_threshold_seconds: Optional[int] = None
    min_video_duration_seconds: Optional[int] = None


def _manifest_dirs() -> list[Path]:
    dirs: set[Path] = set()
    config = _load_config()
    root = str(config.get("download_root", "downloads")).strip()
    if root:
        dirs.add(Path(root).expanduser().resolve())

    try:
        with _db_connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT DISTINCT output_dir FROM tasks WHERE output_dir IS NOT NULL AND output_dir != ''"
            ).fetchall()
        for row in rows:
            value = str(row["output_dir"] or "").strip()
            if value:
                dirs.add(Path(value).expanduser().resolve())
    except Exception:
        pass

    manifest_dirs: set[Path] = set()
    for directory in dirs:
        if (directory / "manifest.csv").exists():
            manifest_dirs.add(directory)
        if directory.exists():
            try:
                for manifest in directory.rglob("manifest.csv"):
                    manifest_dirs.add(manifest.parent.resolve())
            except Exception:
                pass
    return sorted(manifest_dirs, key=lambda item: str(item).lower())


def _external_library_items(payload: object) -> list[dict]:
    if isinstance(payload, dict):
        tasks = payload.get("tasks")
        if isinstance(tasks, list):
            return [item for item in tasks if isinstance(item, dict)]
        return [payload]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    raise HTTPException(status_code=400, detail="JSON 必须是对象或数组。")


def _external_upload_request_from_body(
    body: object,
    category: Optional[str] = None,
    limit: Optional[int] = None,
) -> ExternalVideoLibraryUploadRequest:
    body_category: Optional[str] = None
    body_limit: Optional[int] = None
    payload = body
    if isinstance(body, dict) and "payload" in body:
        payload = body.get("payload")
        if body.get("category") is not None:
            body_category = str(body.get("category") or "").strip() or None
        if body.get("limit") is not None:
            try:
                body_limit = int(body.get("limit"))
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="limit 必须是数字。")
    if limit is not None:
        body_limit = int(limit)
    if category is not None:
        body_category = str(category or "").strip() or None
    return ExternalVideoLibraryUploadRequest(
        payload=payload,
        category=body_category,
        limit=body_limit,
    )


def _external_tag_texts(item: dict) -> list[str]:
    tags: list[str] = []
    raw_tags = item.get("tags") or []
    if not isinstance(raw_tags, list):
        return tags
    for tag in raw_tags:
        text = ""
        if isinstance(tag, dict):
            text = str(tag.get("text") or "").strip()
        elif isinstance(tag, str):
            text = tag.strip()
        if text:
            tags.append(_repair_mojibake_text(text))
    return tags


def _external_video_url(item: dict) -> str:
    captured = item.get("capturedDownload")
    if isinstance(captured, dict) and captured.get("url"):
        return str(captured.get("url") or "").strip()
    downloads = item.get("downloads") or []
    if isinstance(downloads, list):
        for entry in downloads:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("kind") or "").lower() == "download" and entry.get("url"):
                return str(entry.get("url") or "").strip()
    return ""


def _external_cover_url(item: dict) -> str:
    cover = item.get("cover")
    if isinstance(cover, dict) and cover.get("url"):
        return str(cover.get("url") or "").strip()
    return ""


def _file_name_from_url(url: str, fallback: str, default_suffix: str) -> str:
    parsed = urlparse(url)
    name = unquote(Path(parsed.path).name or "").strip()
    if not name:
        name = fallback
    name = re.sub(r"[^\w.\- ]+", "_", name).strip(" ._") or fallback
    if not Path(name).suffix:
        name = f"{name}{default_suffix}"
    return name[:160]


def _upload_remote_media_once(
    uploader: UploadClient,
    url: str,
    file_name: str,
    kind: str,
    log_cb=None,
) -> dict:
    if not url.startswith(("http://", "https://")):
        raise RuntimeError("远程地址必须是 http/https。")
    headers = {"User-Agent": "Mozilla/5.0"}
    last_exc: Optional[Exception] = None
    for attempt in range(1, 4):
        try:
            resp_ctx = requests.get(url, stream=True, timeout=(15, 900), headers=headers)
            break
        except requests.RequestException as exc:
            last_exc = exc
            if log_cb:
                log_cb(f"远程媒体下载连接失败，重试 {attempt}/3：{file_name} {exc}")
            if attempt < 3:
                time.sleep(2 * attempt)
    else:
        error_text = str(last_exc or "")
        if "NameResolutionError" in error_text or "getaddrinfo failed" in error_text:
            raise RuntimeError(
                f"远程媒体 DNS 解析失败：{file_name}，请检查服务器 DNS/网络是否能访问 {urlparse(url).hostname}"
            )
        raise RuntimeError(f"远程媒体下载连接失败：{file_name} {last_exc}")

    with resp_ctx as resp:
        resp.raise_for_status()
        content_type = str(resp.headers.get("Content-Type") or "").split(";", 1)[0].strip()
        if not content_type or content_type == "application/octet-stream":
            content_type = "video/mp4" if kind == "video" else "image/jpeg"
        try:
            total = int(str(resp.headers.get("Content-Length") or "").strip())
        except ValueError:
            total = 0
        if total > 0:
            digest = hashlib.md5()
            hashed_bytes = 0

            class HashingReader:
                def read(self, size: int = -1) -> bytes:
                    nonlocal hashed_bytes
                    chunk = resp.raw.read(size)
                    if chunk:
                        hashed_bytes += len(chunk)
                        digest.update(chunk)
                    return chunk

            resp.raw.decode_content = True
            if kind == "image":
                upload_id = uploader.upload_image_reader(file_name, HashingReader(), total, content_type)
            else:
                upload_id = uploader.upload_video_reader(file_name, HashingReader(), total, content_type)
            return {
                "upload_id": upload_id,
                "content_md5": digest.hexdigest(),
                "hashed_bytes": hashed_bytes,
                "file_size": total,
                "content_type": content_type,
            }

        temp_dir = STATE_DIR / "external_uploads"
        temp_dir.mkdir(parents=True, exist_ok=True)
        suffix = Path(file_name).suffix or (".jpg" if kind == "image" else ".mp4")
        temp_path: Optional[Path] = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir=temp_dir) as handle:
                temp_path = Path(handle.name)
                for chunk in resp.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        handle.write(chunk)
            content_md5 = _file_content_md5(temp_path) if temp_path else None
            file_size = temp_path.stat().st_size if temp_path and temp_path.exists() else 0
            if kind == "image":
                upload_id = uploader.upload_image_file(temp_path)
            else:
                upload_id = uploader.upload_video_file(temp_path)
            return {
                "upload_id": upload_id,
                "content_md5": content_md5,
                "hashed_bytes": file_size,
                "file_size": file_size,
                "content_type": content_type,
            }
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink()
                except OSError:
                    pass


def _is_retryable_remote_upload_error(exc: Exception) -> bool:
    if isinstance(exc, requests.HTTPError):
        response = exc.response
        return response is None or response.status_code >= 500
    if isinstance(exc, (requests.RequestException, ConnectionError, TimeoutError, OSError, EOFError)):
        return True
    text = str(exc).lower()
    return any(
        marker in text
        for marker in (
            "timed out",
            "timeout",
            "ssl eof",
            "eof occurred in violation of protocol",
            "tlsv1",
            "connection aborted",
            "connection reset",
            "connection broken",
            "remote disconnected",
            "incomplete read",
        )
    )


def _upload_remote_media(
    uploader: UploadClient,
    url: str,
    file_name: str,
    kind: str,
    log_cb=None,
) -> dict:
    max_attempts = max(1, int(os.getenv("REMOTE_MEDIA_UPLOAD_ATTEMPTS", "6")))
    for attempt in range(1, max_attempts + 1):
        try:
            return _upload_remote_media_once(uploader, url, file_name, kind, log_cb=log_cb)
        except Exception as exc:
            if attempt >= max_attempts or not _is_retryable_remote_upload_error(exc):
                raise
            if log_cb:
                log_cb(
                    f"远程媒体上传中断，重新获取文件并重传 {attempt}/{max_attempts}：{file_name} {exc}"
                )
            time.sleep(min(10, attempt * 2))
    raise RuntimeError(f"远程媒体上传失败：{file_name}")


def _download_remote_media_to_temp(
    url: str,
    file_name: str,
    kind: str,
    log_cb=None,
    known_md5: str = "",
    known_file_size: int = 0,
    destination: Optional[Path] = None,
) -> dict:
    if not url.startswith(("http://", "https://")):
        raise RuntimeError("远程地址必须是 http/https。")
    temp_dir = STATE_DIR / "external_uploads"
    temp_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(file_name).suffix or (".jpg" if kind == "image" else ".mp4")
    max_attempts = max(1, int(os.getenv("REMOTE_MEDIA_DOWNLOAD_ATTEMPTS", "5")))
    range_chunk_bytes = max(
        64 * 1024,
        int(os.getenv("REMOTE_MEDIA_RANGE_CHUNK_BYTES", str(512 * 1024))),
    )
    headers = {"User-Agent": "Mozilla/5.0"}
    temporary_file = destination is None
    if destination is None:
        temp_fd, temp_name = tempfile.mkstemp(suffix=suffix, dir=temp_dir)
        os.close(temp_fd)
        temp_path = Path(temp_name)
    else:
        temp_path = destination.expanduser()
        temp_path.parent.mkdir(parents=True, exist_ok=True)
    expected_size: Optional[int] = known_file_size if known_md5 and known_file_size > 0 else None
    content_type = "video/mp4" if kind == "video" else "image/jpeg"
    retry_count = 0
    use_chunked_ranges = False

    try:
        while True:
            downloaded_size = temp_path.stat().st_size if temp_path.exists() else 0
            if expected_size is not None and downloaded_size >= expected_size:
                return {
                    "path": temp_path,
                    "content_md5": known_md5 if known_file_size == downloaded_size else (_file_content_md5(temp_path) or ""),
                    "file_size": downloaded_size,
                    "content_type": content_type,
                    "md5_reused": bool(known_md5 and known_file_size == downloaded_size),
                    "temporary_file": temporary_file,
                }
            request_headers = dict(headers)
            if downloaded_size > 0 or use_chunked_ranges:
                range_end = ""
                if expected_size is not None:
                    range_end = str(
                        min(expected_size - 1, downloaded_size + range_chunk_bytes - 1)
                    )
                request_headers["Range"] = f"bytes={downloaded_size}-{range_end}"
            try:
                with requests.get(
                    url,
                    stream=True,
                    timeout=(15, 900),
                    headers=request_headers,
                ) as response:
                    if downloaded_size > 0 and response.status_code == 200:
                        # Source does not support ranges. Restart instead of corrupting the file.
                        with temp_path.open("wb"):
                            pass
                        downloaded_size = 0
                        expected_size = None
                        use_chunked_ranges = False
                    response.raise_for_status()
                    response_content_type = str(response.headers.get("Content-Type") or "").split(";", 1)[0].strip()
                    if response_content_type and response_content_type != "application/octet-stream":
                        content_type = response_content_type
                    content_range = str(response.headers.get("Content-Range") or "")
                    total_match = re.search(r"/(\d+)$", content_range)
                    if total_match:
                        expected_size = int(total_match.group(1))
                    try:
                        response_size = int(str(response.headers.get("Content-Length") or "").strip())
                    except ValueError:
                        response_size = 0
                    if response_size > 0 and expected_size is None:
                        expected_size = downloaded_size + response_size if response.status_code == 206 else response_size
                    with temp_path.open("ab" if downloaded_size > 0 else "wb") as handle:
                        # Small chunks preserve nearly all data when a CDN closes mid-response.
                        for chunk in response.iter_content(chunk_size=64 * 1024):
                            if chunk:
                                handle.write(chunk)
                file_size = temp_path.stat().st_size
                if file_size <= 0:
                    raise RuntimeError("远程媒体下载为空。")
                if expected_size is None or file_size >= expected_size:
                    return {
                        "path": temp_path,
                        "content_md5": known_md5 if known_file_size == file_size else (_file_content_md5(temp_path) or ""),
                        "file_size": file_size,
                        "content_type": content_type,
                        "md5_reused": bool(known_md5 and known_file_size == file_size),
                        "temporary_file": temporary_file,
                    }
                # A complete range block was received; continue with the next block.
                retry_count = 0
                use_chunked_ranges = True
            except Exception as exc:
                if not _is_retryable_remote_upload_error(exc):
                    raise
                retry_count += 1
                if retry_count >= max_attempts:
                    raise
                resume_size = temp_path.stat().st_size if temp_path.exists() else 0
                use_chunked_ranges = True
                if log_cb:
                    log_cb(
                        f"远程媒体下载中断，断点续传 {retry_count}/{max_attempts}：{file_name} 已下载 {resume_size} bytes，{exc}"
                    )
                time.sleep(min(10, retry_count * 2))
    except Exception:
        if temporary_file:
            try:
                temp_path.unlink()
            except OSError:
                pass
        raise


def _upload_local_media_with_retry(
    uploader: UploadClient,
    path: Path,
    kind: str,
    log_cb=None,
) -> int:
    max_attempts = max(1, int(os.getenv("REMOTE_MEDIA_UPLOAD_ATTEMPTS", "6")))
    for attempt in range(1, max_attempts + 1):
        try:
            return (
                uploader.upload_image_file(path)
                if kind == "image"
                else uploader.upload_video_file(path)
            )
        except Exception as exc:
            if attempt >= max_attempts or not _is_retryable_remote_upload_error(exc):
                raise
            if log_cb:
                log_cb(
                    f"媒体直传中断，复用已下载文件重传 {attempt}/{max_attempts}：{path.name} {exc}"
                )
            time.sleep(min(10, attempt * 2))
    raise RuntimeError(f"媒体直传失败：{path.name}")


class _SkipExternalJsonVideo(RuntimeError):
    """Signals that a JSON video already exists and needs no further upload work."""


def _json_md5_lock(content_md5: str) -> threading.Lock:
    with _json_md5_locks_lock:
        lock = _json_md5_locks.get(content_md5)
        if lock is None:
            lock = threading.Lock()
            _json_md5_locks[content_md5] = lock
        return lock


def _upload_json_video_with_deduplication(
    uploader: UploadClient,
    url: str,
    file_name: str,
    log_cb=None,
    known_md5: str = "",
    known_file_size: int = 0,
    on_md5_ready=None,
    local_path: Optional[Path] = None,
) -> dict:
    downloaded = _download_remote_media_to_temp(
        url,
        file_name,
        "video",
        log_cb=log_cb,
        known_md5=known_md5,
        known_file_size=known_file_size,
        destination=local_path,
    )
    temp_path = downloaded["path"]
    try:
        content_md5 = str(downloaded.get("content_md5") or "").lower()
        file_size = int(downloaded.get("file_size") or 0)
        if log_cb and not downloaded.get("temporary_file"):
            log_cb(
                f"JSON视频本地下载完成：{temp_path.name} path={temp_path} bytes={file_size}"
            )
        if callable(on_md5_ready) and content_md5:
            on_md5_ready(content_md5, file_size, bool(downloaded.get("md5_reused")))
        if not content_md5:
            raise RuntimeError(f"无法计算 JSON 视频 MD5：{file_name}")
        # Only same-content files serialize here. Different videos continue uploading
        # concurrently, while duplicate inputs cannot upload twice before DB recording.
        with _json_md5_lock(content_md5):
            duplicate = _fetch_uploaded_video_by_md5(content_md5)
            existing_upload_id = int((duplicate or {}).get("upload_id") or 0)
            if existing_upload_id > 0:
                return {
                    "upload_id": existing_upload_id,
                    "content_md5": content_md5,
                    "hashed_bytes": file_size,
                    "file_size": file_size,
                    "content_type": downloaded.get("content_type"),
                    "duplicate": duplicate,
                    "skipped": True,
                }
            upload_id = _upload_local_media_with_retry(
                uploader, temp_path, "video", log_cb=log_cb
            )
            _record_uploaded_video(
                "JSON视频上传",
                int(content_md5[:15], 16),
                file_name,
                file_size,
                upload_id,
                content_md5,
            )
            return {
                "upload_id": upload_id,
                "content_md5": content_md5,
                "hashed_bytes": file_size,
                "file_size": file_size,
                "content_type": downloaded.get("content_type"),
                "skipped": False,
            }
    finally:
        if downloaded.get("temporary_file"):
            try:
                temp_path.unlink()
            except OSError:
                pass


def _safe_child_path(base_dir: Path, value: str) -> Optional[Path]:
    if not value:
        return None
    target = Path(value)
    if not target.is_absolute():
        target = base_dir / target
    try:
        resolved = target.expanduser().resolve()
        resolved.relative_to(base_dir.resolve())
    except Exception:
        return None
    return resolved


def _read_sidecar_meta(output_dir: Path, local_path: Optional[Path]) -> dict:
    if not local_path:
        return {}
    meta_path = output_dir / f"{local_path.stem}.json"
    if not meta_path.exists():
        meta_path = local_path.with_suffix(".json")
    if not meta_path.exists():
        return {}
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _completed_row(output_dir: Path, row: dict) -> dict:
    message_id = row.get("message_id")
    local_path = _safe_child_path(output_dir, row.get("local_path") or row.get("file_name") or "")
    meta = _read_sidecar_meta(output_dir, local_path)
    file_size = row.get("file_size") or meta.get("file_size")
    try:
        file_size = int(file_size) if file_size is not None and str(file_size).strip() else None
    except (TypeError, ValueError):
        file_size = None
    completed_at = row.get("date_utc")
    if local_path and local_path.exists():
        completed_at = datetime.utcfromtimestamp(local_path.stat().st_mtime).replace(microsecond=0).isoformat() + "Z"
    tags = meta.get("tags") or row.get("tags") or []
    if isinstance(tags, str):
        tags = [item for item in tags.split("|") if item]
    cover_files = meta.get("cover_files") or []
    extra_images = meta.get("extra_images") or []
    return {
        "message_id": int(message_id) if str(message_id).isdigit() else message_id,
        "channel": row.get("channel") or meta.get("channel"),
        "date_utc": row.get("date_utc") or meta.get("date_utc"),
        "completed_at": completed_at,
        "caption": row.get("caption") or meta.get("caption") or "",
        "tags": tags,
        "title": meta.get("title") or row.get("file_name") or "",
        "description": meta.get("description") or row.get("caption") or "",
        "file_name": row.get("file_name") or meta.get("file_name") or "",
        "file_size": file_size,
        "mime_type": row.get("mime_type") or meta.get("mime_type"),
        "duration": meta.get("duration"),
        "local_path": str(local_path) if local_path else row.get("local_path"),
        "output_dir": str(output_dir),
        "cover_files": cover_files if isinstance(cover_files, list) else [],
        "extra_images": extra_images if isinstance(extra_images, list) else [],
    }


def _best_preview_cache_image(output_dir: Path, message_id: object) -> Optional[str]:
    preview_dir = output_dir / "preview_cache"
    if not preview_dir.exists():
        return None
    safe_id = str(message_id or "").strip()
    if not safe_id:
        return None
    pattern_groups = (
        f"{safe_id}_preview_-1.*",
        f"{safe_id}_preview_*",
        f"{safe_id}_preview.*",
        f"{safe_id}_img_*",
        f"{safe_id}_img.*",
    )
    candidates: list[Path] = []
    for pattern in pattern_groups:
        candidates = [path for path in preview_dir.glob(pattern) if path.is_file()]
        if candidates:
            break
    if not candidates:
        return None
    best = max(candidates, key=lambda path: path.stat().st_size if path.exists() else 0)
    try:
        return best.relative_to(output_dir).as_posix()
    except ValueError:
        return str(best)


@app.post("/tasks", dependencies=[Depends(_require_token)])
def create_task(req: TaskRequest) -> dict:
    if not req.message_ids and not (req.start_date or req.end_date):
        raise HTTPException(status_code=400, detail="å¿…é¡»æä¾› message_ids æˆ–æ—¥æœŸèŒƒå›´ã€‚")
    config = _load_config()
    if req.api_id is not None:
        config["telegram_api_id"] = str(req.api_id).strip()
    if req.api_hash is not None:
        config["telegram_api_hash"] = str(req.api_hash).strip()
    if req.upload_base_url is not None:
        config["upload_base_url"] = str(req.upload_base_url).strip()
    if req.upload_account is not None:
        config["upload_account"] = str(req.upload_account).strip()
    if req.upload_password is not None:
        config["upload_password"] = str(req.upload_password)
    if req.upload_api_token is not None:
        config["upload_api_token"] = str(req.upload_api_token).strip()
    if any(
        value is not None
        for value in (
            req.api_id,
            req.api_hash,
            req.upload_base_url,
            req.upload_account,
            req.upload_password,
            req.upload_api_token,
        )
    ):
        _save_config(config)
    auto_upload = req.auto_upload
    if auto_upload is None:
        auto_upload = bool(config.get("auto_upload_default", True))
    upload_meta = req.upload_meta
    if upload_meta is None:
        upload_meta = bool(config.get("upload_meta", True))
    if req.force_upload:
        _delete_uploaded_videos(req.channel, req.message_ids)
    threshold = req.video_type_threshold_seconds
    if threshold is None:
        raw_threshold = config.get("video_type_threshold_seconds")
        try:
            threshold = int(raw_threshold) if raw_threshold is not None else None
        except (TypeError, ValueError):
            threshold = None
    min_duration = req.min_video_duration_seconds
    if min_duration is None:
        min_duration = _coerce_non_negative_int(
            config.get("min_video_duration_seconds"),
            MIN_VIDEO_DURATION_SECONDS,
        )
    else:
        min_duration = _coerce_non_negative_int(
            min_duration,
            MIN_VIDEO_DURATION_SECONDS,
        )
    task_id = _create_task(
        channel=req.channel,
        message_ids=req.message_ids,
        start_date=req.start_date,
        end_date=req.end_date,
        output_dir=req.output_dir,
        video_type_threshold_seconds=threshold,
        min_video_duration_seconds=min_duration,
        auto_upload=auto_upload,
        upload_meta=upload_meta,
    )
    _broadcast_event(
        {"type": "task_created", "task_id": task_id, "status": "pending"}
    )
    return {"id": task_id, "status": "pending"}


@app.get("/tasks/{task_id}", dependencies=[Depends(_require_token)])
def get_task(task_id: int) -> dict:
    task = _fetch_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="ä»»åŠ¡ä¸å­˜åœ¨")
    return _repair_mojibake_value(task)  # type: ignore[return-value]


@app.get("/tasks/{task_id}/files", dependencies=[Depends(_require_token)])
def get_task_files(task_id: int) -> dict:
    task = _fetch_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="ä»»åŠ¡ä¸å­˜åœ¨")
    raw = task.get("progress_json")
    data: dict = {}
    if isinstance(raw, str) and raw:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = {}
    elif isinstance(raw, dict):
        data = raw
    data = _repair_mojibake_value(data)  # type: ignore[assignment]
    files = data.get("files", {})
    if isinstance(files, dict):
        merged: dict[str, dict] = {
            str(key): value for key, value in files.items() if isinstance(value, dict)
        }
    else:
        merged = {}
    is_external_upload_task = str(task.get("channel") or "") == "JSON视频上传"

    try:
        message_ids = json.loads(task.get("message_ids") or "[]")
    except Exception:
        message_ids = []
    message_id_keys = {str(x) for x in message_ids if isinstance(x, int) or str(x).isdigit()}
    for msg_id in message_ids:
        if isinstance(msg_id, int) or str(msg_id).isdigit():
            key = str(int(msg_id))
            merged.setdefault(
                key,
                {
                    "message_id": int(msg_id),
                    "status": "pending" if task.get("status") in ("pending", "running") else task.get("status"),
                },
            )

    output_dir_text = task.get("output_dir")
    if output_dir_text:
        output_dir = Path(str(output_dir_text)).expanduser()
    else:
        config = _load_config()
        output_dir = Path(config.get("download_root", "downloads")).expanduser()
    if is_external_upload_task:
        def _sort_external_key(item: dict) -> int:
            value = item.get("message_id")
            return int(value) if isinstance(value, int) or str(value).isdigit() else 0

        items = sorted(merged.values(), key=_sort_external_key)
        return _repair_mojibake_value({"items": items})  # type: ignore[return-value]
    try:
        manifest_rows = read_manifest(output_dir)
    except Exception:
        manifest_rows = []
    for row in manifest_rows:
        msg_id = row.get("message_id")
        if not msg_id:
            continue
        key = str(msg_id)
        if message_id_keys and key not in message_id_keys:
            continue
        item = merged.setdefault(key, {"message_id": int(msg_id) if str(msg_id).isdigit() else msg_id})
        file_size = row.get("file_size")
        size_value = int(file_size) if file_size and str(file_size).isdigit() else None
        item.update(
            {
                "message_id": int(msg_id) if str(msg_id).isdigit() else msg_id,
                "file_name": row.get("file_name") or item.get("file_name"),
                "bytes_total": size_value if size_value is not None else item.get("bytes_total"),
                "bytes_downloaded": size_value if size_value is not None else item.get("bytes_downloaded"),
                "status": "done",
                "local_path": row.get("local_path") or item.get("local_path"),
            }
        )

    for key, item in merged.items():
        msg_id = item.get("message_id") or key
        if msg_id is None:
            continue
        preview_image = _best_preview_cache_image(output_dir, msg_id)
        if preview_image:
            item["preview_image"] = preview_image

    def _sort_key(item: dict) -> int:
        value = item.get("message_id")
        return int(value) if isinstance(value, int) or str(value).isdigit() else 0

    items = sorted(merged.values(), key=_sort_key)
    return _repair_mojibake_value({"items": items})  # type: ignore[return-value]


@app.get("/downloads/completed", dependencies=[Depends(_require_token)])
def list_completed_downloads(
    limit: int = 500,
    offset: int = 0,
    q: Optional[str] = None,
) -> dict:
    keyword = (q or "").strip().lower()
    items: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for output_dir in _manifest_dirs():
        try:
            manifest_rows = read_manifest(output_dir)
        except Exception:
            continue
        for row in manifest_rows:
            message_id = str(row.get("message_id") or "")
            key = (str(output_dir), message_id)
            if key in seen:
                continue
            seen.add(key)
            item = _completed_row(output_dir, row)
            if keyword:
                haystack = " ".join(
                    str(value or "")
                    for value in [
                        item.get("message_id"),
                        item.get("channel"),
                        item.get("title"),
                        item.get("description"),
                        item.get("caption"),
                        item.get("file_name"),
                        " ".join(item.get("tags") or []),
                    ]
                ).lower()
                if keyword not in haystack:
                    continue
            items.append(item)

    items.sort(key=lambda item: item.get("completed_at") or item.get("date_utc") or "", reverse=True)
    total = len(items)
    return {"items": items[offset : offset + limit], "total": total, "limit": limit, "offset": offset}


@app.post("/downloads/completed/delete", dependencies=[Depends(_require_token)])
def delete_completed_download(req: DeleteCompletedRequest) -> dict:
    output_dir = Path(req.output_dir).expanduser().resolve()
    if not (output_dir / "manifest.csv").exists():
        raise HTTPException(status_code=404, detail="ä¸‹è½½è®°å½•ä¸å­˜åœ¨")
    rows = read_manifest(output_dir)
    target_row = next((row for row in rows if row.get("message_id") == str(req.message_id)), None)
    if not target_row:
        raise HTTPException(status_code=404, detail="ä¸‹è½½è®°å½•ä¸å­˜åœ¨")

    local_path = _safe_child_path(output_dir, target_row.get("local_path") or target_row.get("file_name") or "")
    meta = _read_sidecar_meta(output_dir, local_path)
    paths: list[Path] = []
    if local_path:
        paths.append(local_path)
        paths.append(output_dir / f"{local_path.stem}.json")
        paths.append(local_path.with_suffix(".json"))
    for rel_path in (meta.get("cover_files") or []) + (meta.get("extra_images") or []):
        safe_path = _safe_child_path(output_dir, str(rel_path))
        if safe_path:
            paths.append(safe_path)

    deleted = 0
    for path in dict.fromkeys(paths):
        try:
            if path.exists() and path.is_file():
                path.unlink()
                deleted += 1
        except OSError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    remove_manifest_entry(output_dir, int(req.message_id))
    return {"message_id": req.message_id, "deleted_files": deleted}


@app.get("/config", dependencies=[Depends(_require_token)])
def get_config() -> dict:
    config = _load_config()
    return {
        "telegram_api_id": config.get("telegram_api_id"),
        "telegram_api_hash": config.get("telegram_api_hash"),
        "download_root": config.get("download_root"),
        "telegram_download_concurrency": config.get("telegram_download_concurrency"),
        "upload_base_url": config.get("upload_base_url"),
        "upload_account": config.get("upload_account"),
        "upload_password": config.get("upload_password"),
        "upload_api_token": config.get("upload_api_token"),
        "video_type_threshold_seconds": config.get("video_type_threshold_seconds"),
        "min_video_duration_seconds": config.get("min_video_duration_seconds"),
    }


@app.post("/config", dependencies=[Depends(_require_token)])
def update_config(req: ConfigUpdateRequest) -> dict:
    config = _load_config()
    if req.telegram_api_id is not None:
        config["telegram_api_id"] = str(req.telegram_api_id).strip()
    if req.telegram_api_hash is not None:
        config["telegram_api_hash"] = str(req.telegram_api_hash).strip()
    if req.download_root is not None:
        config["download_root"] = str(req.download_root).strip() or "downloads"
    if req.telegram_download_concurrency is not None:
        value = int(req.telegram_download_concurrency)
        if value < 1:
            raise HTTPException(status_code=400, detail="å¹¶å‘æ•°å¿…é¡»å¤§äºŽ 0")
        config["telegram_download_concurrency"] = value
    if req.upload_base_url is not None:
        config["upload_base_url"] = str(req.upload_base_url).strip()
    if req.upload_account is not None:
        config["upload_account"] = str(req.upload_account).strip()
    if req.upload_password is not None:
        config["upload_password"] = str(req.upload_password)
    if req.upload_api_token is not None:
        config["upload_api_token"] = str(req.upload_api_token).strip()
    if req.video_type_threshold_seconds is not None:
        config["video_type_threshold_seconds"] = _coerce_non_negative_int(
            req.video_type_threshold_seconds,
            DEFAULT_VIDEO_TYPE_THRESHOLD_SECONDS,
        )
    if req.min_video_duration_seconds is not None:
        config["min_video_duration_seconds"] = _coerce_non_negative_int(
            req.min_video_duration_seconds,
            MIN_VIDEO_DURATION_SECONDS,
        )
    _save_config(config)
    return {
        "telegram_api_id": config.get("telegram_api_id"),
        "telegram_api_hash": config.get("telegram_api_hash"),
        "download_root": config.get("download_root"),
        "telegram_download_concurrency": config.get("telegram_download_concurrency"),
        "upload_base_url": config.get("upload_base_url"),
        "upload_account": config.get("upload_account"),
        "upload_password": config.get("upload_password"),
        "upload_api_token": config.get("upload_api_token"),
        "video_type_threshold_seconds": config.get("video_type_threshold_seconds"),
        "min_video_duration_seconds": config.get("min_video_duration_seconds"),
    }


def _external_upload_request_from_task(task: dict) -> Optional[ExternalVideoLibraryUploadRequest]:
    raw_progress = task.get("progress_json") or "{}"
    try:
        progress = json.loads(raw_progress) if isinstance(raw_progress, str) else raw_progress
    except json.JSONDecodeError:
        progress = {}
    saved = progress.get("external_upload") if isinstance(progress, dict) else None
    if isinstance(saved, dict) and saved.get("payload") is not None:
        req = ExternalVideoLibraryUploadRequest(
            payload=saved.get("payload"),
            category=saved.get("category"),
            limit=saved.get("limit"),
        )
        files = progress.get("files") if isinstance(progress, dict) else {}
        failed_indexes = {
            int(key)
            for key, value in (files or {}).items()
            if str(key).isdigit()
            and isinstance(value, dict)
            and str(value.get("upload_status") or value.get("status") or "").lower() == "failed"
        }
        if failed_indexes:
            source_items = _external_library_items(req.payload)
            failed_items = [
                item for index, item in enumerate(source_items, start=1)
                if index in failed_indexes
            ]
            if failed_items:
                return ExternalVideoLibraryUploadRequest(
                    payload={"tasks": failed_items},
                    category=req.category,
                )
        return req

    # Compatibility for tasks created before the JSON source was persisted.
    with _external_upload_jobs_lock:
        jobs = list(_external_upload_jobs.values())
    for job in reversed(jobs):
        if int(job.get("task_id") or 0) != int(task.get("id") or 0):
            continue
        rows = job.get("items") or []
        recovered_items: list[dict] = []
        for row in rows:
            if (
                not isinstance(row, dict)
                or str(row.get("status") or "").lower() == "done"
                or not row.get("video_url")
            ):
                continue
            item = {
                "title": row.get("title") or "",
                "tags": [{"text": tag} for tag in row.get("tags") or [] if str(tag).strip()],
                "capturedDownload": {"url": row.get("video_url")},
            }
            if row.get("cover_url"):
                item["cover"] = {"url": row.get("cover_url")}
            recovered_items.append(item)
        if recovered_items:
            return ExternalVideoLibraryUploadRequest(payload={"tasks": recovered_items})
    return None


def _external_md5_by_url(task: Optional[dict]) -> dict:
    if not task:
        return {}
    raw_progress = task.get("progress_json") or "{}"
    try:
        progress = json.loads(raw_progress) if isinstance(raw_progress, str) else raw_progress
    except json.JSONDecodeError:
        return {}
    external_upload = progress.get("external_upload") if isinstance(progress, dict) else None
    values = external_upload.get("md5_by_url") if isinstance(external_upload, dict) else None
    return dict(values) if isinstance(values, dict) else {}


def _external_known_md5(task_id: int, url: str) -> tuple[str, int]:
    value = _external_md5_by_url(_fetch_task(task_id)).get(url)
    if not isinstance(value, dict):
        return "", 0
    content_md5 = str(value.get("content_md5") or "").strip().lower()
    if not re.fullmatch(r"[a-f0-9]{32}", content_md5):
        return "", 0
    try:
        file_size = int(value.get("file_size") or 0)
    except (TypeError, ValueError):
        file_size = 0
    return content_md5, max(0, file_size)


def _external_json_video_path(task_id: int, index: int, file_name: str) -> Path:
    task = _fetch_task(task_id) or {}
    config = _load_config()
    output_dir = Path(task.get("output_dir") or config.get("download_root") or "downloads")
    safe_name = re.sub(r"[^\w.\- ]+", "_", str(file_name or "")).strip(" ._")
    if not safe_name:
        safe_name = f"external_{index}.mp4"
    if not Path(safe_name).suffix:
        safe_name = f"{safe_name}.mp4"
    return output_dir.expanduser() / "json_video_uploads" / f"task_{task_id}" / f"{index:04d}_{safe_name}"


def _record_external_md5(
    task_id: int,
    url: str,
    file_name: str,
    content_md5: str,
    file_size: int,
    local_path: Optional[Path] = None,
) -> None:
    with _task_progress_write_lock:
        _record_external_md5_unlocked(
            task_id,
            url,
            file_name,
            content_md5,
            file_size,
            local_path,
        )


def _record_external_md5_unlocked(
    task_id: int,
    url: str,
    file_name: str,
    content_md5: str,
    file_size: int,
    local_path: Optional[Path] = None,
) -> None:
    task = _fetch_task(task_id)
    if not task:
        return
    raw_progress = task.get("progress_json") or "{}"
    try:
        progress = json.loads(raw_progress) if isinstance(raw_progress, str) else raw_progress
    except json.JSONDecodeError:
        progress = {}
    external_upload = progress.setdefault("external_upload", {})
    if not isinstance(external_upload, dict):
        external_upload = {}
        progress["external_upload"] = external_upload
    md5_by_url = external_upload.setdefault("md5_by_url", {})
    if not isinstance(md5_by_url, dict):
        md5_by_url = {}
        external_upload["md5_by_url"] = md5_by_url
    md5_by_url[url] = {
        "file_name": file_name,
        "content_md5": content_md5,
        "file_size": int(file_size),
        "local_path": str(local_path) if local_path else "",
        "recorded_at": _utc_now(),
    }
    _update_task(task_id, progress_json=json.dumps(progress, ensure_ascii=False))


def _start_external_video_library_upload(
    req: ExternalVideoLibraryUploadRequest,
    task_id: Optional[int] = None,
) -> dict:
    items = _external_library_items(req.payload)
    if req.limit is not None:
        items = items[: max(0, int(req.limit))]
    is_retry = task_id is not None
    if task_id is None:
        task_id = _create_external_upload_task(
            len(items), req.payload, req.category, req.limit
        )
    else:
        saved_md5_by_url = _external_md5_by_url(_fetch_task(task_id))
        progress = _external_upload_progress(
            len(items), req.payload, req.category, req.limit, saved_md5_by_url
        )
        _update_task(
            task_id,
            status="pending",
            error=None,
            progress_json=json.dumps(progress, ensure_ascii=False),
        )
    _write_task_version_log(task_id)
    action = "任务重试" if is_retry else "任务开始"
    _write_task_log(
        task_id,
        f"JSON视频上传{action}：共 {len(items)} 条，等待全局任务执行位。",
    )

    job_id = uuid.uuid4().hex
    cancel_event = threading.Event()
    with _external_upload_jobs_lock:
        _external_upload_cancel_events[task_id] = cancel_event
        _external_upload_jobs[job_id] = {
            "job_id": job_id,
            "task_id": task_id,
            "status": "pending",
            "created_at": _utc_now(),
            "updated_at": _utc_now(),
            "total": len(items),
            "success": 0,
            "skipped": 0,
            "failed": 0,
            "items": [],
        }

    def _worker() -> None:
        try:
            if cancel_event.is_set():
                result = {
                    "task_id": task_id,
                    "total": len(items),
                    "success": 0,
                    "skipped": 0,
                    "failed": 0,
                    "items": [],
                }
            else:
                with _external_upload_jobs_lock:
                    if job_id in _external_upload_jobs:
                        _external_upload_jobs[job_id].update(
                            {"status": "running", "updated_at": _utc_now()}
                        )
                _update_task(task_id, status="running", error=None)
                _merge_task_progress(
                    task_id,
                    {"stage": "upload", "status": "JSON视频上传开始执行"},
                )
                _write_task_log(
                    task_id,
                    f"JSON视频上传开始执行：全局并发上限 {EXTERNAL_JSON_TASK_CONCURRENCY} 个任务。",
                )
                result = _process_external_video_library_upload(
                    req, job_id, task_id, cancel_event
                )
            if cancel_event.is_set():
                result.update({"job_id": job_id, "task_id": task_id, "status": "cancelled", "updated_at": _utc_now()})
                _merge_task_progress(task_id, {"stage": "upload", "status": "JSON视频上传已取消"})
                _update_task(task_id, status="cancelled", error=None)
                _write_task_log(task_id, "JSON视频上传已取消。")
            else:
                result.update({"job_id": job_id, "task_id": task_id, "status": "done", "updated_at": _utc_now()})
                completed_count = result.get("success", 0) + result.get("skipped", 0)
                final_status = "done" if completed_count > 0 or result.get("total", 0) == 0 else "failed"
                _merge_task_progress(
                    task_id,
                    {
                        "stage": "upload",
                        "status": f"JSON视频上传完成：成功 {result.get('success', 0)}，跳过 {result.get('skipped', 0)}，失败 {result.get('failed', 0)}",
                        "upload_count": {
                            "done": result.get("total", 0),
                            "total": result.get("total", 0),
                        },
                        "download_count": {
                            "done": result.get("total", 0),
                            "total": result.get("total", 0),
                        },
                    },
                )
                _update_task(task_id, status=final_status, error=None if final_status == "done" else "全部上传失败")
                _write_task_log(
                    task_id,
                    f"JSON视频上传完成：成功 {result.get('success', 0)}，跳过 {result.get('skipped', 0)}，失败 {result.get('failed', 0)}。",
                )
        except Exception as exc:
            result = {
                "job_id": job_id,
                "task_id": task_id,
                "status": "failed",
                "updated_at": _utc_now(),
                "error": str(exc),
                "total": 0,
                "success": 0,
                "skipped": 0,
                "failed": 1,
                "items": [],
            }
            _update_task(task_id, status="failed", error=str(exc))
            _write_task_log(task_id, f"JSON视频上传失败: {exc}")
        with _external_upload_jobs_lock:
            _external_upload_jobs[job_id] = result
            if _external_upload_cancel_events.get(task_id) is cancel_event:
                _external_upload_cancel_events.pop(task_id, None)

    _external_upload_executor.submit(_worker)
    return {"job_id": job_id, "task_id": task_id, "status": "pending"}


@app.post("/external/video-library/upload", dependencies=[Depends(_require_token)])
@app.post("/external/video-library/ingest", dependencies=[Depends(_require_token)])
async def upload_external_video_library(
    request: Request,
    category: Optional[str] = Query(default=None),
    limit: Optional[int] = Query(default=None),
) -> dict:
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="请求体必须是 JSON。")
    req = _external_upload_request_from_body(body, category=category, limit=limit)
    return _start_external_video_library_upload(req)


@app.get("/external/video-library/jobs/{job_id}", dependencies=[Depends(_require_token)])
def get_external_video_library_job(job_id: str) -> dict:
    with _external_upload_jobs_lock:
        job = _external_upload_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="上传任务不存在。")
    return _repair_mojibake_value(job)  # type: ignore[return-value]


@app.get("/external/video-library/progress", dependencies=[Depends(_require_token)])
def get_external_video_library_progress_summary() -> dict:
    """Return durable aggregate progress across every JSON video upload task."""
    with _db_connect() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT id, status, created_at, updated_at, progress_json
            FROM tasks
            WHERE channel=?
            ORDER BY id DESC
            """,
            ("JSON视频上传",),
        ).fetchall()

    totals = {
        "total": 0,
        "completed": 0,
        "pending": 0,
        "uploading": 0,
        "success": 0,
        "skipped": 0,
        "failed": 0,
    }
    for raw_task in rows:
        task = dict(raw_task)
        try:
            progress = json.loads(task.get("progress_json") or "{}")
        except json.JSONDecodeError:
            progress = {}
        progress = progress if isinstance(progress, dict) else {}
        files = progress.get("files")
        file_values = list(files.values()) if isinstance(files, dict) else []
        upload_count = progress.get("upload_count")
        expected_total = 0
        if isinstance(upload_count, dict):
            try:
                expected_total = max(0, int(upload_count.get("total") or 0))
            except (TypeError, ValueError):
                expected_total = 0
        expected_total = max(expected_total, len(file_values))
        totals["total"] += expected_total
        counted = 0
        for item in file_values:
            if not isinstance(item, dict):
                continue
            status = str(item.get("upload_status") or item.get("status") or "pending")
            if status == "done":
                totals["success"] += 1
                totals["completed"] += 1
            elif status == "skipped":
                totals["skipped"] += 1
                totals["completed"] += 1
            elif status == "failed":
                totals["failed"] += 1
                totals["completed"] += 1
            elif status in ("uploading", "running", "downloading"):
                totals["uploading"] += 1
            else:
                totals["pending"] += 1
            counted += 1
        remaining = max(0, expected_total - counted)
        if remaining:
            if str(task.get("status") or "") == "failed":
                totals["failed"] += remaining
                totals["completed"] += remaining
            else:
                totals["pending"] += remaining

    return _repair_mojibake_value(
        {"task_total": len(rows), **totals}
    )  # type: ignore[return-value]


@app.get(
    "/external/video-library/tasks/{task_id}/progress",
    dependencies=[Depends(_require_token)],
)
def get_external_video_library_progress(task_id: int) -> dict:
    """Return durable JSON-upload progress for external systems polling by task ID."""
    task = _fetch_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="JSON 视频上传任务不存在。")
    if str(task.get("channel") or "") != "JSON视频上传":
        raise HTTPException(status_code=400, detail="该 task_id 不是 JSON 视频上传任务。")

    raw_progress = task.get("progress_json") or "{}"
    try:
        progress = json.loads(raw_progress) if isinstance(raw_progress, str) else raw_progress
    except json.JSONDecodeError:
        progress = {}
    if not isinstance(progress, dict):
        progress = {}

    file_response = get_task_files(task_id)
    files = list(file_response.get("items") or [])
    counts = {"done": 0, "skipped": 0, "failed": 0, "uploading": 0, "pending": 0}
    for item in files:
        status = str(item.get("upload_status") or item.get("status") or "pending")
        if status in counts:
            counts[status] += 1
        elif status in ("running", "downloading"):
            counts["uploading"] += 1
        else:
            counts["pending"] += 1
    upload_count = progress.get("upload_count")
    if not isinstance(upload_count, dict):
        upload_count = {}
    total = int(upload_count.get("total") or len(files) or 0)
    completed = counts["done"] + counts["skipped"] + counts["failed"]
    return _repair_mojibake_value(
        {
            "task_id": task_id,
            "status": task.get("status"),
            "message": progress.get("status") or "",
            "stage": progress.get("stage") or "upload",
            "created_at": task.get("created_at"),
            "updated_at": task.get("updated_at"),
            "total": total,
            "completed": completed,
            "pending": max(0, total - completed - counts["uploading"]),
            "uploading": counts["uploading"],
            "success": counts["done"],
            "skipped": counts["skipped"],
            "failed": counts["failed"],
            "files": files,
        }
    )  # type: ignore[return-value]


def _request_external_upload_cancel(task_id: int) -> bool:
    with _external_upload_jobs_lock:
        cancel_event = _external_upload_cancel_events.get(task_id)
    if cancel_event is None:
        return False
    cancel_event.set()
    return True


def _process_external_video_library_upload(
    req: ExternalVideoLibraryUploadRequest,
    job_id: str,
    task_id: int,
    cancel_event: Optional[threading.Event] = None,
) -> dict:
    config = _load_config()
    base_url = str(config.get("upload_base_url") or "").strip()
    if not base_url:
        raise HTTPException(status_code=400, detail="未配置上传服务地址。")
    uploader = UploadClient(
        base_url=base_url,
        account=str(config.get("upload_account") or ""),
        password=str(config.get("upload_password") or ""),
        api_token=str(config.get("upload_api_token") or ""),
        meta_url=config.get("video_meta_url"),
        movie_create_url=config.get("movie_create_url"),
        movie_category_default=config.get("movie_category_default"),
        debug=True,
        log_cb=lambda msg: _write_task_log(task_id, msg),
    )
    if not uploader.movie_create_url:
        raise HTTPException(status_code=400, detail="未配置长视频影片接口 movie_create_url。")
    # Resolve account/password authentication once before worker threads share it.
    if not uploader.token and uploader.account and uploader.password:
        uploader._auth_headers()

    items = _external_library_items(req.payload)
    if req.limit is not None:
        items = items[: max(0, int(req.limit))]
    category = str(
        req.category or config.get("movie_category_default") or "纪录片"
    ).strip() or "纪录片"
    results: list[dict] = []
    success = 0
    skipped = 0
    with _external_upload_jobs_lock:
        if job_id in _external_upload_jobs:
            _external_upload_jobs[job_id].update(
                {"total": len(items), "success": 0, "skipped": 0, "failed": 0, "items": [], "updated_at": _utc_now()}
            )

    def _process_item(index: int, item: dict) -> dict:
        if cancel_event is not None and cancel_event.is_set():
            return {"index": index, "status": "cancelled"}
        title = _repair_mojibake_text(str(item.get("title") or "")).strip()
        if not title:
            title = str(item.get("pageKey") or item.get("pageUrl") or f"video-{index}")
        tags = _external_tag_texts(item)
        video_url = _external_video_url(item)
        cover_url = _external_cover_url(item)
        row: dict = {
            "index": index,
            "title": title,
            "content": title,
            "tags": tags,
            "video_url": video_url,
            "cover_url": cover_url,
            "status": "pending",
        }
        _merge_task_progress(
            task_id,
            {
                "stage": "upload",
                "status": f"JSON视频上传中 {index}/{len(items)}",
                "upload_count": {"done": len(results), "total": len(items)},
                "download_count": {"done": len(results), "total": len(items)},
                "files": {
                    str(index): {
                        "message_id": index,
                        "file_name": title,
                        "source_file_name": _file_name_from_url(video_url, f"external_{index}.mp4", ".mp4") if video_url else f"external_{index}.mp4",
                        "title": title,
                        "caption": title,
                        "description": title,
                        "tags": tags,
                        "status": "uploading",
                        "upload_status": "uploading",
                    }
                },
            },
        )
        _write_task_log(task_id, f"开始上传 JSON 视频 {index}/{len(items)}：{title}")
        try:
            if not video_url:
                raise RuntimeError("JSON 中缺少 capturedDownload.url。")
            file_name = _file_name_from_url(video_url, f"external_{index}.mp4", ".mp4")
            local_video_path = _external_json_video_path(task_id, index, file_name)
            _write_task_log(
                task_id,
                f"JSON视频下载路径：index={index} path={local_video_path}",
            )
            _write_task_log(
                task_id,
                f"MD5加密源数据：source=JSON视频上传 index={index} file={file_name} local_path={local_video_path} url={video_url}",
            )
            known_md5, known_file_size = _external_known_md5(task_id, video_url)

            def _on_md5_ready(value: str, file_size: int, reused: bool) -> None:
                _record_external_md5(
                    task_id,
                    video_url,
                    file_name,
                    value,
                    file_size,
                    local_video_path,
                )
                if reused:
                    _write_task_log(
                        task_id,
                        f"MD5加密记录复用：source=JSON视频上传 index={index} file={file_name} hashed_bytes={file_size} md5={value}",
                    )
                else:
                    _write_task_log(
                        task_id,
                        f"MD5加密结果：source=JSON视频上传 index={index} file={file_name} hashed_bytes={file_size} md5={value}",
                    )

            video_upload = _upload_json_video_with_deduplication(
                uploader,
                video_url,
                file_name,
                log_cb=lambda msg: _write_task_log(task_id, msg),
                known_md5=known_md5,
                known_file_size=known_file_size,
                on_md5_ready=_on_md5_ready,
                local_path=local_video_path,
            )
            video_id = int(video_upload.get("upload_id") or 0)
            content_md5 = str(video_upload.get("content_md5") or "").lower()
            hashed_bytes = int(video_upload.get("hashed_bytes") or 0)
            duplicate = video_upload.get("duplicate")
            if duplicate:
                _write_task_log(
                    task_id,
                    f"MD5重复：JSON视频 {file_name} md5={content_md5} 已存在 {duplicate.get('channel')}#{duplicate.get('message_id')} upload_id={duplicate.get('upload_id')}，整条跳过上传。",
                )
                raise _SkipExternalJsonVideo()
            _write_task_log(
                task_id,
                f"直传上传完成：{file_name} upload_id={video_id} md5={content_md5 or '-'}",
            )
            thumbnail_id = 0
            if cover_url:
                cover_name = _file_name_from_url(cover_url, f"external_{index}.jpg", ".jpg")
                try:
                    _write_task_log(
                        task_id,
                        f"开始上传封面：source=cover.url index={index} file={cover_name} url={cover_url}",
                    )
                    cover_upload = _upload_remote_media(
                        uploader,
                        cover_url,
                        cover_name,
                        "image",
                        log_cb=lambda msg: _write_task_log(task_id, msg),
                    )
                    thumbnail_id = int(cover_upload.get("upload_id") or 0)
                    _write_task_log(
                        task_id,
                        f"封面上传完成：source=cover.url index={index} thumbnail_id={thumbnail_id or '-'}",
                    )
                except Exception as exc:
                    row["cover_error"] = str(exc)
                    _write_task_log(
                        task_id,
                        f"封面上传失败：source=cover.url index={index} {exc}",
                    )
            else:
                _write_task_log(task_id, f"未找到封面：index={index} JSON 缺少 cover.url")
            _write_task_log(
                task_id,
                f"影片标题同步：title_len={len(title)} content_len={len(title)} same=True",
            )
            uploader.create_movie_record(
                title=title,
                category=category,
                content=title,
                tags=tags,
                video_id=video_id,
                thumbnail_id=thumbnail_id,
            )
            _write_task_log(
                task_id,
                f"JSON影片提交数据：title={title} content={title} category={category} tags={tags} video_id={video_id} thumbnail_id={thumbnail_id or '-'} Categories={[category]}",
            )
            local_deleted = False
            try:
                if local_video_path.exists():
                    local_video_path.unlink()
                    local_deleted = True
                    _write_task_log(
                        task_id,
                        f"JSON视频本地文件已删除：index={index} path={local_video_path}",
                    )
            except OSError as exc:
                _write_task_log(
                    task_id,
                    f"JSON视频本地文件删除失败，保留用于重试：index={index} path={local_video_path} error={exc}",
                )
            row.update(
                {
                    "status": "done",
                    "video_id": video_id,
                    "thumbnail_id": thumbnail_id,
                    "cover_id": thumbnail_id,
                    "thumb_id": thumbnail_id,
                    "cover_source": "cover.url" if cover_url else "",
                    "cover_url": cover_url,
                    "category": category,
                    "content_md5": content_md5,
                    "file_size": int(video_upload.get("file_size") or hashed_bytes or 0),
                    "reused_video_upload": False,
                    "local_path": str(local_video_path),
                    "local_deleted": local_deleted,
                }
            )
            _write_task_log(task_id, f"JSON视频上传完成：{index} video_id={video_id} thumbnail_id={thumbnail_id or '-'} md5={content_md5 or '-'}")
        except _SkipExternalJsonVideo:
            row.update(
                {
                    "status": "skipped",
                    "video_id": video_id,
                    "content_md5": content_md5,
                    "file_size": int(video_upload.get("file_size") or hashed_bytes or 0),
                    "local_path": str(local_video_path),
                    "skip_reason": "MD5重复",
                }
            )
            _write_task_log(task_id, f"JSON视频上传跳过：{index} MD5重复，不上传视频、封面或影片记录。")
        except Exception as exc:
            row.update({"status": "failed", "error": str(exc)})
            _write_task_log(task_id, f"JSON视频上传失败：{index} {exc}")
        return row

    def _record_item_result(row: dict) -> None:
        nonlocal success, skipped
        with _task_progress_write_lock:
            results.append(row)
            results.sort(key=lambda value: int(value.get("index") or 0))
            success = sum(1 for value in results if value.get("status") == "done")
            skipped = sum(1 for value in results if value.get("status") == "skipped")
            completed = len(results)
            failed = sum(1 for value in results if value.get("status") == "failed")
        _merge_task_progress(
            task_id,
            {
                "stage": "upload",
                "status": f"JSON视频上传中 {completed}/{len(items)}",
                "upload_count": {"done": completed, "total": len(items)},
                "download_count": {"done": completed, "total": len(items)},
                "files": {
                    str(row.get("index")): {
                        "message_id": row.get("index"),
                        "file_name": row.get("title"),
                        "source_file_name": _file_name_from_url(str(row.get("video_url") or ""), f"external_{row.get('index')}.mp4", ".mp4"),
                        "title": row.get("title"),
                        "caption": row.get("title"),
                        "description": row.get("content"),
                        "tags": row.get("tags") or [],
                        "status": row.get("status") or "failed",
                        "upload_status": row.get("status"),
                        "upload_id": row.get("video_id"),
                        "thumbnail_id": row.get("thumbnail_id"),
                        "cover_id": row.get("cover_id"),
                        "thumb_id": row.get("thumb_id"),
                        "video_url": row.get("video_url"),
                        "local_path": row.get("local_path"),
                        "local_deleted": row.get("local_deleted"),
                        "cover_url": row.get("cover_url"),
                        "content_md5": row.get("content_md5"),
                        "reused_video_upload": row.get("reused_video_upload"),
                        "skip_reason": row.get("skip_reason"),
                        "bytes_total": row.get("file_size"),
                        "bytes_downloaded": row.get("file_size"),
                        "error": row.get("error"),
                    }
                },
            },
        )
        with _external_upload_jobs_lock:
            if job_id in _external_upload_jobs:
                _external_upload_jobs[job_id].update(
                    {
                        "total": len(items),
                        "success": success,
                        "skipped": skipped,
                        "failed": failed,
                        "items": list(results),
                        "updated_at": _utc_now(),
                    }
                )

    concurrency = 1
    _write_task_log(task_id, "JSON视频上传模式：逐条顺序处理。")
    item_iterator = iter(enumerate(items, start=1))
    pending: dict[object, int] = {}
    with ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="json-video-upload") as executor:
        def _submit_one() -> bool:
            if cancel_event is not None and cancel_event.is_set():
                return False
            try:
                index, item = next(item_iterator)
            except StopIteration:
                return False
            pending[executor.submit(_process_item, index, item)] = index
            return True

        for _ in range(min(concurrency, len(items))):
            if not _submit_one():
                break
        while pending:
            future = next(as_completed(pending))
            pending.pop(future, None)
            try:
                row = future.result()
            except Exception as exc:
                row = {"index": 0, "status": "failed", "error": str(exc)}
            if row.get("status") != "cancelled":
                _record_item_result(row)
            _submit_one()

    return _repair_mojibake_value(
        {
            "task_id": task_id,
            "total": len(items),
            "success": success,
            "skipped": skipped,
            "failed": len(items) - success - skipped,
            "items": results,
        }
    )  # type: ignore[return-value]


@app.get("/tasks/{task_id}/log", dependencies=[Depends(_require_token)])
def get_task_log(
    task_id: int,
    limit: int = 200,
    offset: int = 0,
    search: Optional[str] = None,
) -> dict:
    if not _fetch_task(task_id):
        raise HTTPException(status_code=404, detail="ä»»åŠ¡ä¸å­˜åœ¨")
    return _read_task_log(task_id, limit=limit, offset=offset, search=search)


@app.post("/tasks/{task_id}/remove", dependencies=[Depends(_require_token)])
def remove_task_items(task_id: int, req: RemoveItemsRequest) -> dict:
    task = _fetch_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="ä»»åŠ¡ä¸å­˜åœ¨")
    ids = [int(x) for x in (req.message_ids or []) if isinstance(x, int) or str(x).isdigit()]
    ids = list(dict.fromkeys(ids))
    if not ids:
        return {"id": task_id, "removed": []}
    try:
        current = json.loads(task.get("message_ids") or "[]")
    except Exception:
        current = []
    current_set = {int(x) for x in current if isinstance(x, int) or str(x).isdigit()}
    if not current_set:
        try:
            progress = json.loads(task.get("progress_json") or "{}")
        except Exception:
            progress = {}
        if isinstance(progress, dict):
            files = progress.get("files") or {}
            if isinstance(files, dict):
                current_set = {int(x) for x in files.keys() if str(x).isdigit()}
    removed = [x for x in ids if x in current_set]
    if not removed:
        return {"id": task_id, "removed": []}
    new_ids = [x for x in current if int(x) not in set(removed)]
    _update_task(task_id, message_ids=json.dumps(new_ids, ensure_ascii=False))
    task_runner.remove_ids(task_id, removed)
    try:
        progress = json.loads(task.get("progress_json") or "{}")
    except Exception:
        progress = {}
    if isinstance(progress, dict):
        files = progress.get("files") or {}
        if isinstance(files, dict):
            for msg_id in removed:
                files.pop(str(msg_id), None)
            progress["files"] = files
        count = progress.get("download_count") or {}
        if isinstance(count, dict):
            total = count.get("total")
            done = count.get("done")
            if isinstance(total, int):
                total = max(0, total - len(removed))
            elif new_ids:
                total = len(new_ids)
            if isinstance(done, int) and isinstance(total, int):
                done = min(done, total)
            count["total"] = total
            count["done"] = done
            progress["download_count"] = count
        _update_task(task_id, progress_json=json.dumps(progress))
    _write_task_log(task_id, f"已删除所选：{','.join(str(x) for x in removed)}")
    return {"id": task_id, "removed": removed}


@app.post("/tasks/{task_id}/pause", dependencies=[Depends(_require_token)])
def pause_task_item(task_id: int, req: PauseRequest) -> dict:
    task = _fetch_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="ä»»åŠ¡ä¸å­˜åœ¨")
    msg_id = int(req.message_id)
    paused = bool(req.pause)
    task_runner.set_pause(task_id, msg_id, paused)
    raw = task.get("progress_json") or {}
    if isinstance(raw, str):
        try:
            progress = json.loads(raw)
        except Exception:
            progress = {}
    else:
        progress = raw if isinstance(raw, dict) else {}
    files = progress.get("files") or {}
    key = str(msg_id)
    state = files.get(key) or {"message_id": msg_id}
    state["status"] = "paused" if paused else "downloading"
    files[key] = state
    progress["files"] = files
    _update_task(task_id, progress_json=json.dumps(progress, ensure_ascii=False))
    _write_task_log(task_id, f"{'已暂停' if paused else '继续下载'}：{msg_id}")
    _broadcast_event({"type": "task_updated", "task_id": task_id})
    return {"id": task_id, "paused": paused}


@app.get("/tasks", dependencies=[Depends(_require_token)])
def list_tasks(
    limit: int = 100,
    offset: int = 0,
    status: Optional[str] = None,
    channel: Optional[str] = None,
    q: Optional[str] = None,
    created_from: Optional[str] = None,
    created_to: Optional[str] = None,
    updated_from: Optional[str] = None,
    updated_to: Optional[str] = None,
    sort_by: str = "id",
    sort_order: str = "desc",
    cache: bool = Query(default=False),
) -> dict:
    if cache:
        with _task_cache_lock:
            items = list(_task_cache.values())
        allowed_sort = {"id", "created_at", "updated_at", "status", "channel"}
        key = sort_by if sort_by in allowed_sort else "id"
        reverse = sort_order.lower() != "asc"
        items.sort(key=lambda x: x.get(key) or "", reverse=reverse)
        total = len(items)
        return _repair_mojibake_value(
            {"items": items[offset : offset + limit], "total": total, "limit": limit, "offset": offset}
        )  # type: ignore[return-value]
    status_list = [item.strip() for item in status.split(",")] if status else None
    items, total = _list_tasks(
        limit=limit,
        offset=offset,
        status=status_list,
        channel=channel,
        q=q,
        created_from=created_from,
        created_to=created_to,
        updated_from=updated_from,
        updated_to=updated_to,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    for item in items:
        _cache_task(item)
    return _repair_mojibake_value(
        {"items": items, "total": total, "limit": limit, "offset": offset}
    )  # type: ignore[return-value]


def _login_key(api_id: str, api_hash: str, output_dir: str, phone: str = "") -> str:
    # Keep API credentials and phone numbers out of both memory keys and SQLite.
    raw_key = f"{api_id}:{api_hash}:{output_dir}:{phone}"
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def _save_login_code(login_key: str, code_hash: str) -> None:
    created_at = time.time()
    with _login_lock:
        _login_codes[login_key] = code_hash
    _db_write(
        lambda conn: conn.execute(
            """
            INSERT INTO login_code_requests (login_key, code_hash, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(login_key) DO UPDATE SET
                code_hash=excluded.code_hash,
                created_at=excluded.created_at
            """,
            (login_key, code_hash, created_at),
        )
    )


def _load_login_code(login_key: str) -> Optional[str]:
    with _login_lock:
        cached = _login_codes.get(login_key)
    if cached:
        return cached
    with _db_connect() as conn:
        row = conn.execute(
            "SELECT code_hash, created_at FROM login_code_requests WHERE login_key=?",
            (login_key,),
        ).fetchone()
    if not row:
        return None
    code_hash, created_at = str(row[0] or ""), float(row[1] or 0)
    if not code_hash or time.time() - created_at > LOGIN_CODE_TTL_SECONDS:
        _delete_login_code(login_key)
        return None
    with _login_lock:
        _login_codes[login_key] = code_hash
    return code_hash


def _delete_login_code(login_key: str) -> None:
    with _login_lock:
        _login_codes.pop(login_key, None)
    _db_write(
        lambda conn: conn.execute(
            "DELETE FROM login_code_requests WHERE login_key=?", (login_key,)
        )
    )


def _resolve_telegram_credentials(
    api_id: Optional[str] = None,
    api_hash: Optional[str] = None,
) -> tuple[str, str]:
    config = _load_config()
    resolved_api_id = str(api_id or config.get("telegram_api_id") or "").strip()
    resolved_api_hash = str(api_hash or config.get("telegram_api_hash") or "").strip()
    if not resolved_api_id or not resolved_api_hash:
        raise HTTPException(status_code=400, detail="è¯·å…ˆåœ¨ä»»åŠ¡é…ç½®é¡µé…ç½® API ID å’Œ API Hashã€‚")
    return resolved_api_id, resolved_api_hash


def _resolve_login_output_dir(output_dir: Optional[str] = None) -> str:
    config = _load_config()
    return str(output_dir or config.get("download_root") or "downloads")


def _ensure_output_dir(output_dir: str) -> Path:
    path = Path(output_dir).expanduser()
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise HTTPException(
            status_code=400, detail=f"è¾“å‡ºç›®å½•ä¸å¯å†™: {path} ({exc})"
        ) from exc
    return path


def _promote_session_to_root(output_dir: Path) -> None:
    config = _load_config()
    root_dir = Path(config.get("download_root", "downloads")).expanduser().resolve()
    root_dir.mkdir(parents=True, exist_ok=True)
    session_files = list(output_dir.glob("user_session.session*"))
    if not session_files:
        return
    for session_file in session_files:
        target = root_dir / session_file.name
        try:
            target.write_bytes(session_file.read_bytes())
        except Exception as exc:
            raise HTTPException(
                status_code=500, detail=f"æ— æ³•å¤åˆ¶ç™»å½•ä¼šè¯åˆ°ä¸‹è½½æ ¹ç›®å½•: {exc}"
            ) from exc


def _copy_session_files(source_base: Path, target_base: Path) -> list[Path]:
    copied: list[Path] = []
    for source in source_base.parent.glob(f"{source_base.name}.session*"):
        suffix = source.name.replace(source_base.name, "", 1)
        target = target_base.parent / f"{target_base.name}{suffix}"
        try:
            target.write_bytes(source.read_bytes())
            copied.append(target)
        except OSError:
            pass
    return copied


def _pool_session_base(key: tuple[str, str, str]) -> Path:
    pool_session_dir = STATE_DIR / "pool_sessions"
    pool_session_dir.mkdir(parents=True, exist_ok=True)
    key_text = "|".join(key)
    base_name = "pool_" + hashlib.md5(key_text.encode("utf-8")).hexdigest()
    return pool_session_dir / base_name


def _sync_pool_session_to_output(
    api_id: str, api_hash: str, output_dir: Path
) -> None:
    key = _telegram_pool_key(api_id, api_hash, output_dir)
    source_base = _pool_session_base(key)
    target_base = output_dir / "user_session"
    copied = _copy_session_files(source_base, target_base)
    if copied:
        _promote_session_to_root(output_dir)


def _validate_login_input(api_id: str, api_hash: str, phone: str) -> None:
    if not str(api_id).strip() or not str(api_hash).strip():
        raise HTTPException(status_code=400, detail="è¯·å¡«å†™ API ID å’Œ API Hashã€‚")
    if not str(phone).strip():
        raise HTTPException(status_code=400, detail="è¯·å¡«å†™æ‰‹æœºå·ã€‚")
    if not str(phone).strip().startswith("+"):
        raise HTTPException(status_code=400, detail="æ‰‹æœºå·éœ€åŒ…å«å›½å®¶åŒºå·ï¼Œä¾‹å¦‚ +82 æˆ– +86ã€‚")


def _build_tracked_client(
    api_id: str,
    api_hash: str,
    output_dir: Path,
    loop: Optional[asyncio.AbstractEventLoop] = None,
    session_path: Optional[Path] = None,
) -> TelegramClient:
    client = build_client(
        api_id,
        api_hash,
        output_dir,
        loop=loop,
        session_path=session_path,
    )
    _patch_telethon_session_lock_handling(client)
    _active_telegram_clients.add(client)
    return client


def _patch_telethon_session_lock_handling(client: TelegramClient) -> None:
    save_states = getattr(client, "_save_states_and_entities", None)
    if callable(save_states) and not getattr(client, "_state_save_patch_applied", False):
        def _safe_save_states(*args, **kwargs):
            try:
                return save_states(*args, **kwargs)
            except sqlite3.OperationalError as exc:
                if _is_db_locked(exc):
                    return None
                raise

        setattr(client, "_save_states_and_entities", _safe_save_states)
        try:
            setattr(client, "_state_save_patch_applied", True)
        except Exception:
            pass

    session = getattr(client, "session", None)
    if session is None or getattr(session, "_lock_patch_applied", False):
        return

    for method_name in ("save", "process_entities"):
        method = getattr(session, method_name, None)
        if not callable(method):
            continue

        def _make_safe(original):
            def _safe(*args, **kwargs):
                try:
                    return original(*args, **kwargs)
                except sqlite3.OperationalError as exc:
                    if _is_db_locked(exc):
                        return None
                    raise

            return _safe

        setattr(session, method_name, _make_safe(method))
    try:
        setattr(session, "_lock_patch_applied", True)
    except Exception:
        pass


def _telegram_pool_key(
    api_id: str,
    api_hash: str,
    output_dir: Path,
) -> tuple[str, str, str]:
    return (str(api_id), str(api_hash), str(output_dir.resolve()))


async def _get_pooled_telegram_client(
    api_id: str,
    api_hash: str,
    output_dir: Path,
) -> TelegramClient:
    await _cleanup_idle_pooled_telegram_clients()
    key = _telegram_pool_key(api_id, api_hash, output_dir)
    loop = asyncio.get_running_loop()
    client = _telegram_client_pool.get(key)
    client_loop = getattr(client, "loop", None) if client is not None else None
    if client is not None and client_loop is not None and client_loop is not loop:
        await _close_pooled_telegram_client(key)
        client = None
    if client is None:
        session_path, session_files = _copy_session_for_pool(key, output_dir)
        client = _build_tracked_client(
            api_id,
            api_hash,
            output_dir,
            loop=loop,
            session_path=session_path,
        )
        _telegram_client_pool[key] = client
        _telegram_client_pool_sessions[key] = session_files
    if not client.is_connected():
        await asyncio.wait_for(client.connect(), timeout=12)
    _telegram_client_pool_last_used[key] = time.monotonic()
    return client


async def _cleanup_idle_pooled_telegram_clients() -> None:
    if TELEGRAM_POOL_IDLE_SECONDS <= 0:
        return
    now = time.monotonic()
    stale_keys = [
        key
        for key, last_used in list(_telegram_client_pool_last_used.items())
        if now - last_used > TELEGRAM_POOL_IDLE_SECONDS
    ]
    for key in stale_keys:
        await _close_pooled_telegram_client(key)


async def _close_pooled_telegram_client(key: tuple[str, str, str]) -> None:
    client = _telegram_client_pool.pop(key, None)
    session_files = _telegram_client_pool_sessions.pop(key, [])
    _telegram_client_pool_last_used.pop(key, None)
    if client is not None:
        await _shield_close_client(client)
    session_base = _pool_session_base(key)
    session_files = list(session_files) + list(
        session_base.parent.glob(f"{session_base.name}.session*")
    )
    if session_files:
        _cleanup_session_files(session_files)


async def _close_all_pooled_telegram_clients() -> None:
    keys = list(_telegram_client_pool.keys())
    for key in keys:
        await _close_pooled_telegram_client(key)


def _drop_client_tracking(client: TelegramClient) -> None:
    _active_telegram_clients.discard(client)
    for key, pooled_client in list(_telegram_client_pool.items()):
        if pooled_client is client:
            _telegram_client_pool.pop(key, None)
            session_files = _telegram_client_pool_sessions.pop(key, [])
            _telegram_client_pool_last_used.pop(key, None)
            if session_files:
                _cleanup_session_files(session_files)


async def _close_client(client: TelegramClient) -> None:
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
    _drop_client_tracking(client)


async def _shield_close_client(client: TelegramClient) -> None:
    loop = asyncio.get_running_loop()
    client_loop = getattr(client, "loop", None)
    if client_loop is not None and client_loop is not loop:
        if getattr(client_loop, "is_closed", lambda: True)():
            _drop_client_tracking(client)
            return
        if getattr(client_loop, "is_running", lambda: False)():
            future = asyncio.run_coroutine_threadsafe(_close_client(client), client_loop)
            try:
                await asyncio.wait_for(asyncio.wrap_future(future), timeout=8)
            except asyncio.TimeoutError:
                future.cancel()
            except BaseException:
                pass
            return
    close_task = asyncio.create_task(_close_client(client))
    try:
        await asyncio.shield(close_task)
    except asyncio.CancelledError:
        try:
            await asyncio.wait_for(asyncio.shield(close_task), timeout=6)
        except BaseException:
            pass
        raise


async def _get_preview_client(
    api_id: str, api_hash: str, output_dir: Path
) -> TelegramClient:
    return await _get_pooled_telegram_client(api_id, api_hash, output_dir)


async def _close_preview_client() -> None:
    await _close_all_pooled_telegram_clients()


@app.on_event("shutdown")
async def _shutdown_preview_client() -> None:
    await _close_preview_client()
    clients = list(_active_telegram_clients)
    for client in clients:
        await _shield_close_client(client)
    await _cancel_pending_telethon_tasks()
    await asyncio.sleep(0.5)
    await _cancel_pending_telethon_tasks()


def _is_telethon_internal_task(task: asyncio.Task) -> bool:
    if task.done() or task is asyncio.current_task():
        return False
    coro = task.get_coro()
    code = getattr(coro, "cr_code", None)
    filename = str(getattr(code, "co_filename", "")).replace("\\", "/").lower()
    name = str(getattr(code, "co_name", ""))
    if "telethon/" not in filename and "telethon\\" not in filename:
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
    current_loop = asyncio.get_running_loop()
    objects = [
        client,
        getattr(client, "_sender", None),
        getattr(getattr(client, "_sender", None), "_connection", None),
    ]
    for obj in objects:
        if obj is None:
            continue
        for value in getattr(obj, "__dict__", {}).values():
            if not isinstance(value, asyncio.Task):
                continue
            try:
                if value.get_loop() is not current_loop:
                    continue
            except RuntimeError:
                continue
            if _is_telethon_internal_task(value):
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


def _copy_session_for_pool(
    key: tuple[str, str, str], output_dir: Path
) -> tuple[Path, list[Path]]:
    target_base = _pool_session_base(key)
    copied = _copy_session_files(output_dir / "user_session", target_base)
    return target_base, copied


def _cleanup_session_files(paths: list[Path]) -> None:
    cleanup: set[Path] = set(paths)
    for path in paths:
        if ".session" in path.name:
            base_name = path.name.split(".session", 1)[0]
            cleanup.update(path.parent.glob(f"{base_name}.session*"))
    for path in cleanup:
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass


async def _with_client_retry(
    api_id: str,
    api_hash: str,
    output_dir: Path,
    action,
) -> object:
    last_exc: Optional[Exception] = None
    key = _telegram_pool_key(api_id, api_hash, output_dir)
    for _ in range(2):
        try:
            client = await _get_pooled_telegram_client(api_id, api_hash, output_dir)
            return await action(client)
        except sqlite3.OperationalError as exc:
            last_exc = exc
            if "locked" not in str(exc).lower():
                raise
            await _close_pooled_telegram_client(key)
            await asyncio.sleep(0.3)
        except Exception as exc:
            last_exc = exc
            if not _is_retryable_telegram_disconnect(exc):
                raise
            await _close_pooled_telegram_client(key)
            await asyncio.sleep(0.3)
    if last_exc:
        raise last_exc
    raise RuntimeError("æœªçŸ¥é”™è¯¯")


def _is_retryable_telegram_disconnect(exc: Exception) -> bool:
    text = str(exc).lower()
    retry_markers = (
        "server closed the connection",
        "0 bytes read",
        "connection reset",
        "connection aborted",
        "connection lost",
        "disconnected",
        "not connected",
        "transport endpoint is not connected",
        "cannot send requests while disconnected",
    )
    return isinstance(exc, (ConnectionError, OSError, EOFError)) or any(
        marker in text for marker in retry_markers
    )


@app.post("/auth/send_code", dependencies=[Depends(_require_token)])
async def send_login_code(req: LoginRequest) -> dict:
    api_id, api_hash = _resolve_telegram_credentials(req.api_id, req.api_hash)
    output_dir_text = _resolve_login_output_dir(req.output_dir)
    _validate_login_input(api_id, api_hash, req.phone)
    output_dir = _ensure_output_dir(output_dir_text)
    async def _do_send() -> object:
        return await _with_client_retry(
            api_id,
            api_hash,
            output_dir,
            lambda client: client.send_code_request(req.phone),
        )

    try:
        sent = await _with_client_lock_async(_do_send)
    except PhoneNumberInvalidError:
        raise HTTPException(status_code=400, detail="手机号格式不正确，请检查国家区号和号码。")
    except RPCError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    code_hash = getattr(sent, "phone_code_hash", "")
    if not code_hash:
        raise HTTPException(status_code=500, detail="未获取到验证码会话，请重新发送验证码。")
    key = _login_key(api_id, api_hash, output_dir_text, req.phone)
    _save_login_code(key, code_hash)
    return {"status": "code_sent"}


@app.post("/auth/verify_code", dependencies=[Depends(_require_token)])
async def verify_login_code(req: VerifyRequest) -> dict:
    api_id, api_hash = _resolve_telegram_credentials(req.api_id, req.api_hash)
    output_dir_text = _resolve_login_output_dir(req.output_dir)
    _validate_login_input(api_id, api_hash, req.phone)
    key = _login_key(api_id, api_hash, output_dir_text, req.phone)
    code_hash = _load_login_code(key)
    if not code_hash:
        raise HTTPException(
            status_code=400,
            detail="请先发送验证码，或验证码会话已过期，请重新发送。",
        )
    output_dir = _ensure_output_dir(output_dir_text)
    async def _do_sign_in() -> None:
        async def _sign_in(client: TelegramClient) -> None:
            try:
                await client.sign_in(
                    phone=req.phone,
                    code=req.code,
                    phone_code_hash=code_hash,
                )
            except SessionPasswordNeededError:
                if not req.password:
                    raise HTTPException(status_code=400, detail="éœ€è¦ä¸¤æ­¥éªŒè¯å¯†ç ")
                await client.sign_in(password=req.password)

        try:
            await _with_client_retry(api_id, api_hash, output_dir, _sign_in)
        finally:
            _delete_login_code(key)

    await _with_client_lock_async(_do_sign_in)
    _sync_pool_session_to_output(api_id, api_hash, output_dir)
    _promote_session_to_root(output_dir)
    return {"status": "ok"}


@app.get("/auth/status", dependencies=[Depends(_require_token)])
async def login_status(
    api_id: Optional[str] = Query(default=None),
    api_hash: Optional[str] = Query(default=None),
    output_dir: Optional[str] = Query(default=None),
) -> dict:
    try:
        api_id, api_hash = _resolve_telegram_credentials(api_id, api_hash)
    except HTTPException:
        return {"authorized": False, "user": None}
    output_dir_text = _resolve_login_output_dir(output_dir)
    output_path = _ensure_output_dir(output_dir_text)
    async def _do_status() -> object:
        async def _status(client: TelegramClient) -> dict:
            authorized = await client.is_user_authorized()
            if not authorized:
                return {"authorized": False, "user": None}
            me = await client.get_me()
            first_name = getattr(me, "first_name", "") or ""
            last_name = getattr(me, "last_name", "") or ""
            username = getattr(me, "username", "") or ""
            display_name = " ".join(part for part in (first_name, last_name) if part).strip()
            return {
                "authorized": True,
                "user": {
                    "id": getattr(me, "id", None),
                    "nickname": display_name or username or "-",
                    "username": username,
                    "phone": getattr(me, "phone", "") or "",
                    "checked_at": _utc_now(),
                    "session_status": "有效",
                },
            }

        return await _with_client_retry(api_id, api_hash, output_path, _status)

    try:
        status = await asyncio.wait_for(
            _with_client_lock_async(_do_status),
            timeout=AUTH_STATUS_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        await _close_pooled_telegram_client(
            _telegram_pool_key(api_id, api_hash, output_path)
        )
        await _cancel_pending_telethon_tasks()
        return {
            "authorized": False,
            "user": None,
            "detail": "Telegram 登录状态检查超时，请稍后重试。",
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    if status.get("authorized"):
        _sync_pool_session_to_output(api_id, api_hash, output_path)
        _promote_session_to_root(output_path)
    return status


@app.post("/auth/logout", dependencies=[Depends(_require_token)])
async def logout(
    api_id: Optional[str] = Query(default=None),
    api_hash: Optional[str] = Query(default=None),
    output_dir: Optional[str] = Query(default=None),
) -> dict:
    output_dir_text = _resolve_login_output_dir(output_dir)
    output_path = _ensure_output_dir(output_dir_text)
    try:
        api_id, api_hash = _resolve_telegram_credentials(api_id, api_hash)
    except HTTPException:
        api_id = ""
        api_hash = ""

    async def _do_logout() -> None:
        if not api_id or not api_hash:
            return
        pool_key = _telegram_pool_key(api_id, api_hash, output_path)
        try:
            await _with_client_retry(
                api_id,
                api_hash,
                output_path,
                lambda client: client.log_out(),
            )
        except BaseException:
            pass
        await _close_pooled_telegram_client(pool_key)

    await _with_client_lock_async(_do_logout)
    for session_file in output_path.glob("user_session.session*"):
        try:
            session_file.unlink()
        except Exception:
            pass
    config = _load_config()
    root_dir = Path(config.get("download_root", "downloads")).expanduser().resolve()
    for session_file in root_dir.glob("user_session.session*"):
        try:
            session_file.unlink()
        except Exception:
            pass
    return {"status": "logged_out"}


@app.post("/preview", dependencies=[Depends(_require_token)])
async def preview_videos(req: PreviewRequest) -> dict:
    output_dir = _ensure_output_dir(req.output_dir)
    config = _load_config()
    min_video_duration_seconds = (
        _coerce_non_negative_int(req.min_video_duration_seconds, MIN_VIDEO_DURATION_SECONDS)
        if req.min_video_duration_seconds is not None
        else _coerce_non_negative_int(
            config.get("min_video_duration_seconds"),
            MIN_VIDEO_DURATION_SECONDS,
        )
    )

    def _login_required() -> str:
        raise ValueError("æœåŠ¡å™¨æœªç™»å½• Telegramï¼Œè¯·å…ˆåœ¨ç½‘é¡µç™»å½•ã€‚")

    limit = min(max(int(req.limit or 30), 1), 50)
    offset = max(0, int(req.offset or 0))
    offset_id = req.offset_id
    max_scan_messages = max(15, min(60, limit * 4))
    pool_key = _telegram_pool_key(req.api_id, req.api_hash, output_dir)
    try:
        async def _do_list_once() -> object:
            common_kwargs = {
                "channel": req.channel,
                "output_dir": output_dir,
                "api_id": req.api_id,
                "api_hash": req.api_hash,
                "limit": limit + 1,
                "offset": offset,
                "offset_id": offset_id,
                "deadline_monotonic": time.monotonic() + PREVIEW_SOFT_TIMEOUT_SECONDS,
                "preview_media_timeout": 1.8,
                "nearby_lookup_timeout": 0.4,
                "max_extra_images": 1,
                "max_thumb_attempts": 3,
                "preview_thumb_total_timeout": 1.8,
                "allow_nearby_extra_images": False,
                "min_video_duration_seconds": min_video_duration_seconds,
                "get_phone_cb": _login_required,
                "get_code_cb": _login_required,
                "get_password_cb": _login_required,
            }
            client = await _get_preview_client(req.api_id, req.api_hash, output_dir)
            return await list_videos(
                **common_kwargs,
                max_scan_messages=max_scan_messages,
                return_scan_limited=True,
                client=client,
            )

        async def _do_list() -> object:
            last_exc: Optional[Exception] = None
            for attempt in range(2):
                try:
                    return await _do_list_once()
                except Exception as exc:
                    last_exc = exc
                    if attempt >= 1 or not _is_retryable_telegram_disconnect(exc):
                        raise
                    await _close_pooled_telegram_client(pool_key)
                    await asyncio.sleep(0.5)
            if last_exc:
                raise last_exc
            raise RuntimeError("预览加载失败")

        items, next_offset_id, scan_limited = await asyncio.wait_for(
            _with_client_lock_async(_do_list),
            timeout=PREVIEW_HARD_TIMEOUT_SECONDS,
        )
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except asyncio.TimeoutError:
        await _close_pooled_telegram_client(pool_key)
        return {
            "items": [],
            "limit": limit,
            "offset": offset,
            "has_more": True,
            "next_offset_id": offset_id,
            "detail": "预览加载超时，请降低加载条数后重试，或稍后再点下一页。",
            "partial_timeout": True,
        }
    except RPCError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    has_more = len(items) > limit or bool(scan_limited)
    if has_more:
        if len(items) > limit and items[:limit]:
            next_offset_id = items[limit - 1].message_id
        items = items[:limit]
    if not has_more:
        next_offset_id = None
    return {
        "items": [item.__dict__ for item in items],
        "limit": limit,
        "offset": offset,
        "has_more": has_more,
        "next_offset_id": next_offset_id,
    }


@app.get("/preview/image", dependencies=[Depends(_require_token)])
def preview_image(
    output_dir: str = Query(...),
    path: str = Query(...),
) -> FileResponse:
    base_dir = _ensure_output_dir(output_dir).resolve()
    safe_path = path.replace("\\", "/")
    target = (base_dir / safe_path).resolve()
    if not str(target).startswith(str(base_dir)):
        raise HTTPException(status_code=400, detail="éžæ³•è·¯å¾„")
    if not _is_valid_image_file(target):
        for suffix in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
            candidate = target.with_suffix(suffix)
            if str(candidate.resolve()).startswith(str(base_dir)) and _is_valid_image_file(candidate):
                target = candidate
                break
        else:
            raise HTTPException(status_code=404, detail="å›¾ç‰‡ä¸å­˜åœ¨")
    return FileResponse(target, media_type=_image_media_type(target))


@app.get("/preview/video", dependencies=[Depends(_require_token)])
def preview_video(
    output_dir: str = Query(...),
    path: str = Query(...),
) -> FileResponse:
    base_dir = _ensure_output_dir(output_dir).resolve()
    safe_path = path.replace("\\", "/")
    target = (base_dir / safe_path).resolve()
    if not str(target).startswith(str(base_dir)):
        raise HTTPException(status_code=400, detail="éžæ³•è·¯å¾„")
    if not target.exists():
        raise HTTPException(status_code=404, detail="è§†é¢‘ä¸å­˜åœ¨")
    return FileResponse(target)


@app.get("/preview/stream", dependencies=[Depends(_require_token)], response_model=None)
async def preview_stream(
    api_id: str = Query(...),
    api_hash: str = Query(...),
    output_dir: str = Query(...),
    channel: str = Query(...),
    message_id: int = Query(...),
    request: Request = None,
):
    output_path = _ensure_output_dir(output_dir)
    if not str(api_id).strip() or not str(api_hash).strip():
        raise HTTPException(status_code=400, detail="è¯·å¡«å†™ API ID å’Œ API Hashã€‚")
    range_header = request.headers.get("range") if request else None
    try:
        for row in read_manifest(output_path):
            if str(row.get("message_id") or "") != str(message_id):
                continue
            local_value = row.get("local_path") or row.get("file_name") or ""
            local_path = _safe_child_path(output_path.resolve(), str(local_value))
            if local_path and local_path.exists():
                return FileResponse(local_path, media_type=row.get("mime_type") or "video/mp4")
    except Exception:
        pass

    async def _do_fetch_stream_info() -> tuple[TelegramClient, object, str, Optional[int]]:
        key = _telegram_pool_key(api_id, api_hash, output_path)
        client = await _get_pooled_telegram_client(api_id, api_hash, output_path)
        authorized = await client.is_user_authorized()
        if not authorized:
            await _close_pooled_telegram_client(key)
            raise HTTPException(status_code=400, detail="æœªç™»å½• Telegramã€‚")
        entity = await _resolve_telegram_entity(client, channel)
        message = await client.get_messages(entity, ids=message_id)
        if not message or not (message.video or message.document):
            await _close_pooled_telegram_client(key)
            raise HTTPException(status_code=404, detail="è§†é¢‘ä¸å­˜åœ¨")
        media = message.media or message.video or message.document
        mime_type = (
            message.file.mime_type
            if getattr(message.file, "mime_type", None)
            else media.mime_type
            if getattr(media, "mime_type", None)
            else "video/mp4"
        )
        total_size = getattr(media, "size", None) or getattr(
            message.file, "size", None
        )
        return client, media, mime_type, total_size

    lock_acquired = False
    try:
        await _acquire_client_lock_async()
        lock_acquired = True
        client, media, mime_type, total_size = await _do_fetch_stream_info()
    except HTTPException:
        if lock_acquired:
            _client_lock.release()
        raise
    except RPCError as exc:
        if lock_acquired:
            _client_lock.release()
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        if lock_acquired:
            _client_lock.release()
        raise HTTPException(status_code=500, detail=str(exc))

    start = 0
    end = (total_size - 1) if total_size else None
    if range_header and total_size:
        try:
            units, rng = range_header.split("=")
            if units.strip() == "bytes":
                start_s, end_s = rng.split("-")
                if start_s:
                    start = int(start_s)
                if end_s:
                    end = int(end_s)
        except ValueError:
            start = 0
            end = total_size - 1
        if end is None or end >= total_size:
            end = total_size - 1
        if start < 0:
            start = 0
        if start > end:
            start = 0
            end = total_size - 1
    length = (end - start + 1) if (total_size and end is not None) else None

    async def _stream() -> bytes:
        sent = 0
        try:
            async for chunk in client.iter_download(
                media,
                offset=start,
                request_size=1024 * 128,
            ):
                if length is not None:
                    remaining = length - sent
                    if remaining <= 0:
                        break
                    if len(chunk) > remaining:
                        chunk = chunk[:remaining]
                    sent += len(chunk)
                yield chunk
        except asyncio.CancelledError:
            return
        finally:
            try:
                _client_lock.release()
            except RuntimeError:
                pass

    headers = {"Accept-Ranges": "bytes"}
    status_code = 200
    if total_size and end is not None:
        headers["Content-Length"] = str(length)
        if range_header:
            headers["Content-Range"] = f"bytes {start}-{end}/{total_size}"
            status_code = 206
    return StreamingResponse(_stream(), media_type=mime_type, headers=headers, status_code=status_code)


@app.get("/tasks/summary", dependencies=[Depends(_require_token)])
def task_summary() -> dict:
    return _task_summary()


@app.post("/tasks/{task_id}/cancel", dependencies=[Depends(_require_token)])
def cancel_task(task_id: int) -> dict:
    task = _fetch_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="ä»»åŠ¡ä¸å­˜åœ¨")
    if task["status"] in ("done", "failed", "cancelled"):
        return {"id": task_id, "status": task["status"]}
    if str(task.get("channel") or "") == "JSON视频上传":
        if _request_external_upload_cancel(task_id):
            _update_task(task_id, status="cancel_requested")
            _write_task_log(task_id, "已请求取消 JSON 视频上传。")
            return {"id": task_id, "status": "cancel_requested"}
        _update_task(task_id, status="cancelled")
        _write_task_log(task_id, "JSON 视频上传未在运行，已标记为取消。")
        return {"id": task_id, "status": "cancelled"}
    if task["status"] == "pending":
        _update_task(task_id, status="cancelled")
        _write_task_log(task_id, "任务已取消。")
        return {"id": task_id, "status": "cancelled"}
    if task_runner.cancel(task_id):
        return {"id": task_id, "status": "cancelled"}
    # A process restart can leave an old task marked as running without an
    # in-memory worker. It cannot be cancelled cooperatively, so finish it now.
    _update_task(task_id, status="cancelled", error=None)
    _write_task_log(task_id, "未找到运行中的任务线程，已标记为取消。")
    return {"id": task_id, "status": "cancelled"}


@app.post("/tasks/{task_id}/retry", dependencies=[Depends(_require_token)])
def retry_task(task_id: int) -> dict:
    task = _fetch_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task["status"] == "running":
        raise HTTPException(status_code=400, detail="任务运行中，请先取消")
    if str(task.get("channel") or "") == "JSON视频上传":
        if task["status"] not in ("failed", "cancelled"):
            return {"id": task_id, "status": task["status"]}
        req = _external_upload_request_from_task(task)
        if req is None:
            raise HTTPException(
                status_code=400,
                detail="该旧 JSON 上传任务未保存原始视频地址，无法重试，请重新提交 JSON。",
            )
        return _start_external_video_library_upload(req, task_id=task_id)
    if task["status"] in ("failed", "cancelled"):
        _update_task(task_id, status="pending", error=None, progress_json=json.dumps({}))
        _write_task_log(task_id, "已重试：继续当前任务。")
        return {"id": task_id, "status": "pending"}
    return {"id": task_id, "status": task["status"]}


@app.post("/tasks/{task_id}/upload", dependencies=[Depends(_require_token)])
def upload_task(task_id: int) -> dict:
    task = _fetch_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task["status"] in ("running", "pending", "cancel_requested"):
        raise HTTPException(status_code=400, detail="任务还未结束，不能单独上传")

    def _run_upload() -> None:
        latest = _fetch_task(task_id)
        if not latest:
            return
        try:
            config = _load_config()
            root_dir = Path(config.get("download_root", "downloads")).expanduser().resolve()
            output_dir = (
                Path(latest["output_dir"])
                if latest.get("output_dir")
                else root_dir / str(latest.get("channel", "")).replace("/", "_")
            )
            output_dir = output_dir.expanduser().resolve()
            try:
                message_ids = json.loads(latest.get("message_ids") or "[]")
            except Exception:
                message_ids = []
            _write_task_version_log(task_id)
            _write_task_log(task_id, "开始上传已下载文件。")
            _update_task(task_id, status="uploading")
            task_runner._auto_upload(latest, output_dir, message_ids)
            _update_task(task_id, status="done")
            _write_task_log(task_id, "已下载文件上传完成。")
        except Exception as exc:
            _update_task(task_id, status="failed", error=str(exc))
            _write_task_log(task_id, f"上传失败: {exc}")

    threading.Thread(target=_run_upload, daemon=True).start()
    return {"id": task_id, "status": "uploading"}


@app.delete("/tasks/{task_id}", dependencies=[Depends(_require_token)])
def delete_task(task_id: int) -> dict:
    task = _fetch_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task["status"] == "running":
        raise HTTPException(status_code=400, detail="任务运行中，请先取消")
    _delete_task(task_id)
    return {"id": task_id, "status": "deleted"}


@app.post("/tasks/clean_stale", dependencies=[Depends(_require_token)])
def clean_stale_tasks() -> dict:
    stale_seconds = int(os.getenv("SERVER_STALE_SECONDS", "3600"))
    def _clean(conn):
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, status, updated_at FROM tasks WHERE status IN ('running','pending','cancel_requested')"
        ).fetchall()
        cleaned = 0
        for row in rows:
            if _is_stale(row["updated_at"], stale_seconds):
                conn.execute(
                    "UPDATE tasks SET status=?, updated_at=? WHERE id=?",
                    ("stale", _utc_now(), row["id"]),
                )
                cleaned += 1
        return cleaned

    cleaned = int(_db_write(_clean) or 0)
    return {"cleaned": cleaned, "stale_seconds": stale_seconds}
