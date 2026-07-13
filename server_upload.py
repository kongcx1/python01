import json
import mimetypes
import time
from pathlib import Path
from typing import Callable, Optional

import requests


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
    if isinstance(value, dict):
        return {key: _repair_mojibake_value(item) for key, item in value.items()}
    return value


def _limit_tags(tags: list[str], max_count: int = 5) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in tags or []:
        tag = _repair_mojibake_text(item).strip()
        if not tag or tag in seen:
            continue
        cleaned.append(tag)
        seen.add(tag)
        if len(cleaned) >= max_count:
            break
    return cleaned


class UploadClient:
    def __init__(
        self,
        base_url: str,
        account: str,
        password: str,
        api_token: Optional[str] = None,
        meta_url: Optional[str] = None,
        movie_create_url: Optional[str] = None,
        movie_category_default: Optional[str] = None,
        debug: bool = False,
        log_cb: Optional[Callable[[str], None]] = None,
        progress_cb: Optional[Callable[[dict], None]] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.account = account
        self.password = password
        self.meta_url = meta_url.strip() if meta_url else ""
        self.movie_create_url = movie_create_url.strip() if movie_create_url else ""
        self.movie_category_default = (
            movie_category_default.strip() if movie_category_default else ""
        )
        self.debug = debug
        self.log_cb = log_cb
        self.progress_cb = progress_cb
        self.token: Optional[str] = api_token.strip() if api_token else None

    def _auth_headers(self) -> dict:
        if self.token:
            return {"Authorization": f"Bearer {self.token}"}
        if self.account and self.password:
            token = self._login_server()
            return {"Authorization": f"Bearer {token}"}
        return {}

    def _log(self, message: str) -> None:
        if self.log_cb:
            self.log_cb(message)

    def _guess_content_type(self, file_path: Path) -> str:
        guessed, _ = mimetypes.guess_type(file_path.name)
        if guessed:
            return guessed
        if file_path.suffix.lower() == ".mp4":
            return "video/mp4"
        return "application/octet-stream"

    def _guess_content_type_by_name(self, file_name: str) -> str:
        guessed, _ = mimetypes.guess_type(file_name)
        if guessed:
            return guessed
        if file_name.lower().endswith(".mp4"):
            return "video/mp4"
        return "application/octet-stream"

    def _collect_sidecar_paths(self, output_dir: Path, video_path: Path) -> list[Path]:
        paths: list[Path] = []
        meta_path = output_dir / f"{video_path.stem}.json"
        if meta_path.exists():
            paths.append(meta_path)
            try:
                data = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                data = {}
            extra_images = data.get("extra_images")
            if isinstance(extra_images, list):
                for rel in extra_images:
                    if not isinstance(rel, str):
                        continue
                    img_path = output_dir / rel
                    if img_path.exists():
                        paths.append(img_path)
        for ext in ("jpg", "jpeg", "png", "webp"):
            for thumb in output_dir.glob(f"{video_path.stem}_thumb_*.{ext}"):
                paths.append(thumb)
        return sorted({p.resolve() for p in paths})

    def _login_server(self) -> str:
        if self.debug:
            self._log("登录上传服务器中...")
        if not self.account or not self.password:
            raise RuntimeError("未配置上传账号密码，无法登录")
        resp = requests.post(
            f"{self.base_url}/login/account",
            json={"account": self.account, "password": self.password},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("ret") != "OK":
            raise RuntimeError(f"登录失败: {data}")
        token = data["token"]
        self.token = token
        self._log("登录上传服务器成功")
        return token

    def _get_upload_url(
        self, file_path: Path, content_type: str, kind: str = "video"
    ) -> tuple[str, int]:
        if self.debug:
            self._log("请求上传地址中...")
        headers = self._auth_headers()
        if kind == "image":
            url = f"{self.base_url}/api/amazon/pic/getToken"
            payload = {"content_type": content_type, "file_name": file_path.name}
        else:
            url = f"{self.base_url}/api/amazon/video/getToken"
            payload = {"content_type": content_type, "file_name": file_path.name}
        resp = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("ret") != "OK":
            raise RuntimeError(f"getToken失败: {data}")
        upload_url = data.get("data", {}).get("token")
        upload_id = data.get("data", {}).get("id")
        if not upload_url or upload_id is None:
            raise RuntimeError(f"getToken返回缺少字段: {data}")
        if self.debug:
            self._log(f"已获取上传地址 (id={upload_id}, len={len(upload_url)})")
        return upload_url, int(upload_id)

    def _notify_upload_finish(
        self, upload_id: int, upload_url: str, kind: str = "video"
    ) -> None:
        if self.debug:
            self._log("通知上传完成中...")
        if kind == "image":
            url = f"{self.base_url}/api/amazon/pic/uploadFinish"
        else:
            url = f"{self.base_url}/api/amazon/video/uploadFinish"
        headers = self._auth_headers()
        payloads = [
            {"ID": upload_id, "Token": upload_url},
            {"ID": upload_id, "token": upload_url},
            {"data": {"ID": upload_id, "Token": upload_url}, "ret": "OK"},
            {"data": {"ID": upload_id, "token": upload_url}},
            {"id": upload_id, "token": upload_url},
            {"id": upload_id},
            {"ID": upload_id},
            {"data": {"id": upload_id}},
        ]
        last_exc = None
        for payload in payloads:
            try:
                if self.debug:
                    self._log(f"uploadFinish请求体: {payload}")
                resp = requests.post(url, json=payload, headers=headers, timeout=10)
                resp.raise_for_status()
                self._log("已通知上传完成")
                return
            except requests.HTTPError as exc:
                last_exc = exc
                if exc.response is None or exc.response.status_code != 400:
                    raise
        if last_exc is not None:
            raise last_exc

    def _put_to_s3(
        self,
        upload_url: str,
        file_path: Path,
        content_type: str,
        progress_cb_override: Optional[Callable[[dict], None]] = None,
    ) -> None:
        total = file_path.stat().st_size
        if self.debug:
            self._log(f"S3上传开始：{file_path.name} ({total} bytes)")

        progress_cb = progress_cb_override or self.progress_cb

        class ProgressFile:
            def __init__(self, path: Path) -> None:
                self.handle = path.open("rb")
                self.sent = 0
                self.last_sent = 0
                self.last_time = time.monotonic()

            def read(self, size: int = -1) -> bytes:
                chunk = self.handle.read(size)
                if chunk:
                    self.sent += len(chunk)
                    percent = int(self.sent * 100 / total) if total else 0
                    now = time.monotonic()
                    elapsed = now - self.last_time
                    speed_bps = None
                    if elapsed > 0:
                        speed_bps = (self.sent - self.last_sent) / elapsed
                    self.last_time = now
                    self.last_sent = self.sent
                    if progress_cb:
                        progress_cb(
                            {
                                "file_name": file_path.name,
                                "sent": self.sent,
                                "total": total,
                                "percent": percent,
                                "speed_bps": speed_bps,
                            }
                        )
                return chunk

            def __len__(self) -> int:
                return total

            def tell(self) -> int:
                return self.handle.tell()

            def seek(self, offset: int, whence: int = 0) -> int:
                return self.handle.seek(offset, whence)

            def close(self) -> None:
                self.handle.close()

        progress_file = ProgressFile(file_path)
        try:
            resp = requests.put(
                upload_url,
                data=progress_file,
                headers={
                    "Content-Type": content_type,
                    "Content-Length": str(total),
                    "Connection": "close",
                },
                timeout=(10, 600),
            )
            resp.raise_for_status()
            if progress_file.sent != total:
                raise RuntimeError(f"S3上传不完整: {progress_file.sent}/{total}")
            if self.debug:
                self._log(f"S3响应：{resp.status_code}")
        finally:
            progress_file.close()

    def upload_file(self, file_path: Path) -> int:
        return self.upload_video_file(file_path)

    def _put_reader_to_s3(
        self,
        upload_url: str,
        file_name: str,
        reader,
        total: int,
        content_type: str,
        progress_cb_override: Optional[Callable[[dict], None]] = None,
    ) -> None:
        progress_cb = progress_cb_override or self.progress_cb
        sent = 0
        last_sent = 0
        last_time = time.monotonic()

        class ProgressReader:
            def read(self, size: int = -1) -> bytes:
                nonlocal sent, last_sent, last_time
                chunk = reader.read(size)
                if chunk:
                    sent += len(chunk)
                    percent = int(sent * 100 / total) if total else 0
                    now = time.monotonic()
                    elapsed = now - last_time
                    speed_bps = None
                    if elapsed > 0:
                        speed_bps = (sent - last_sent) / elapsed
                    last_time = now
                    last_sent = sent
                    if progress_cb:
                        progress_cb(
                            {
                                "file_name": file_name,
                                "sent": sent,
                                "total": total,
                                "percent": percent,
                                "speed_bps": speed_bps,
                            }
                        )
                return chunk

            def __len__(self) -> int:
                return total

        resp = requests.put(
            upload_url,
            data=ProgressReader(),
            headers={
                "Content-Type": content_type,
                "Content-Length": str(total),
                "Connection": "close",
            },
            timeout=(10, 600),
        )
        resp.raise_for_status()
        if sent != total:
            raise RuntimeError(f"S3上传不完整: {sent}/{total}")

    def upload_video_reader(
        self,
        file_name: str,
        reader,
        total: int,
        content_type: Optional[str] = None,
    ) -> int:
        content_type = content_type or self._guess_content_type_by_name(file_name)
        upload_url, upload_id = self._get_upload_url(Path(file_name), content_type, "video")
        self._log(f"开始直传：{file_name}")
        progress_cb = self.progress_cb

        def _wrap(data: dict) -> None:
            if progress_cb:
                progress_cb({**data, "is_video": True})

        self._put_reader_to_s3(upload_url, file_name, reader, total, content_type, _wrap)
        self._log(f"已直传：{file_name}")
        self._notify_upload_finish(upload_id, upload_url, "video")
        return upload_id

    def upload_video_file(self, file_path: Path) -> int:
        content_type = self._guess_content_type(file_path)
        upload_url, upload_id = self._get_upload_url(file_path, content_type, "video")
        self._log(f"开始上传：{file_path.name}")
        progress_cb = self.progress_cb
        def _wrap(data: dict) -> None:
            if progress_cb:
                progress_cb({**data, "is_video": True})
        self._put_to_s3(upload_url, file_path, content_type, _wrap)
        self._log(f"已上传：{file_path.name}")
        self._notify_upload_finish(upload_id, upload_url, "video")
        return upload_id

    def upload_image_file(self, file_path: Path) -> int:
        content_type = self._guess_content_type(file_path)
        upload_url, upload_id = self._get_upload_url(file_path, content_type, "image")
        self._log(f"开始上传：{file_path.name}")
        progress_cb = self.progress_cb
        def _wrap(data: dict) -> None:
            if progress_cb:
                progress_cb({**data, "is_video": False})
        self._put_to_s3(upload_url, file_path, content_type, _wrap)
        self._log(f"已上传：{file_path.name}")
        self._notify_upload_finish(upload_id, upload_url, "image")
        return upload_id

    def create_video_record(
        self,
        video_id: int,
        content: str,
        tags: list[str],
        video_type: str,
        thumbnail_id: int = 0,
    ) -> None:
        if not self.meta_url:
            self._log("未配置短视频接口，跳过视频记录上传。")
            return
        url = self.meta_url
        if url.startswith("/"):
            url = f"{self.base_url}{url}"
        elif not url.startswith("http://") and not url.startswith("https://"):
            url = f"{self.base_url}/{url.lstrip('/')}"
        headers = self._auth_headers()
        tags = _limit_tags(tags)
        payload = {
            "content": content,
            "tags": tags,
            "video_id": video_id,
            "video_type": video_type,
        }
        if thumbnail_id > 0:
            payload["thumbnail_id"] = thumbnail_id
            payload["cover_id"] = thumbnail_id
            payload["thumb_id"] = thumbnail_id
        payload = _repair_mojibake_value(payload)  # type: ignore[assignment]
        if self.debug:
            self._log(f"短视频记录请求体: {payload}")
        resp = requests.post(
            url, json=payload, headers=headers, timeout=10
        )
        resp.raise_for_status()
        if self.debug:
            self._log("短视频记录创建完成。")

    def create_movie_record(
        self,
        title: str,
        category: str,
        content: str,
        tags: list[str],
        video_id: int,
        thumbnail_id: int = 0,
    ) -> None:
        if not self.movie_create_url:
            self._log("未配置 movie create 接口，跳过影片记录上传。")
            return
        url = self.movie_create_url
        if url.startswith("/"):
            url = f"{self.base_url}{url}"
        elif not url.startswith("http://") and not url.startswith("https://"):
            url = f"{self.base_url}/{url.lstrip('/')}"
        headers = self._auth_headers()
        tags = _limit_tags(tags)
        payload = {
            "title": title,
            "category": category,
            "content": content,
            "tags": tags,
            "video_id": video_id,
        }
        if thumbnail_id > 0:
            payload["thumbnail_id"] = thumbnail_id
            payload["cover_id"] = thumbnail_id
            payload["thumb_id"] = thumbnail_id
        payload = _repair_mojibake_value(payload)  # type: ignore[assignment]
        if self.debug:
            self._log(f"影片记录请求体: {payload}")
        resp = requests.post(
            url, json=payload, headers=headers, timeout=10
        )
        if not resp.ok:
            body = (resp.text or "").strip()
            if len(body) > 500:
                body = body[:500] + "..."
            raise RuntimeError(f"影片记录创建失败: HTTP {resp.status_code} {body}")
        data = resp.json()
        if data.get("ret") != "OK":
            raise RuntimeError(f"影片记录创建失败: {data}")
        if self.debug:
            self._log("影片记录创建完成。")

    def upload_video_with_sidecars(
        self, output_dir: Path, video_path: Path, upload_meta: bool = True
    ) -> None:
        self.upload_video_file(video_path)
        if not upload_meta:
            return
        for sidecar in self._collect_sidecar_paths(output_dir, video_path):
            self.upload_image_file(sidecar)
