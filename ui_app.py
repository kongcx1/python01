import json
import os
import queue
import subprocess
import sys
import threading
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Optional

import requests
from downloader_core import (
    load_config,
    read_manifest,
    run_download,
    run_list,
    run_login,
    save_config,
)


DEFAULT_CHANNEL = "@sosocw"
DEFAULT_OUTPUT_DIR = Path.home() / "Desktop" / "telegram_videos_sosocw"
APP_VERSION = "1.4.9"
REQUEST_TIMEOUT = (5, 25)
UPDATE_URL = os.getenv("TELEGRAM_DOWNLOADER_UPDATE_URL", "")


def _set_tk_env() -> None:
    if not hasattr(sys, "_MEIPASS"):
        return
    base = Path(sys._MEIPASS) / "tcl"
    candidates = [("tcl8.6", "tk8.6"), ("tcl8.5", "tk8.5")]
    for tcl_name, tk_name in candidates:
        tcl_path = base / tcl_name
        tk_path = base / tk_name
        if tcl_path.exists() and tk_path.exists():
            os.environ.setdefault("TCL_LIBRARY", str(tcl_path))
            os.environ.setdefault("TK_LIBRARY", str(tk_path))
            return
    system_candidates = [
        (
            Path("/System/Library/Frameworks/Tcl.framework/Versions/8.6/Resources/Scripts"),
            Path("/System/Library/Frameworks/Tk.framework/Versions/8.6/Resources/Scripts"),
        ),
        (
            Path("/System/Library/Frameworks/Tcl.framework/Versions/8.5/Resources/Scripts"),
            Path("/System/Library/Frameworks/Tk.framework/Versions/8.5/Resources/Scripts"),
        ),
    ]
    for tcl_path, tk_path in system_candidates:
        if tcl_path.exists() and tk_path.exists():
            os.environ.setdefault("TCL_LIBRARY", str(tcl_path))
            os.environ.setdefault("TK_LIBRARY", str(tk_path))
            return


_set_tk_env()

import tkinter as tk


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"Telegram 视频下载器 v{APP_VERSION}")
        self.geometry("920x700")

        self.event_queue: queue.Queue[dict] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.pause_event = threading.Event()
        self.stop_event = threading.Event()
        self.prompt_lock = threading.Lock()

        self.api_id_var = tk.StringVar()
        self.api_hash_var = tk.StringVar()
        self.channel_var = tk.StringVar(value=DEFAULT_CHANNEL)
        self.output_var = tk.StringVar(value=str(DEFAULT_OUTPUT_DIR))
        self.progress_var = tk.DoubleVar(value=0.0)
        self.status_var = tk.StringVar(value="空闲")
        self.status_text_var = tk.StringVar(value=f"就绪 (v{APP_VERSION})")
        self.login_status_var = tk.StringVar(value="未登录")
        self.preview_rows: dict[str, dict] = {}
        self.selected_ids: set[str] = set()
        self.current_task: Optional[str] = None
        self.active_allowed_ids: Optional[set[int]] = None
        self.progress_details: dict[int, dict] = {}
        self.current_message_id: Optional[int] = None
        self.detail_window: Optional[tk.Toplevel] = None
        self.detail_tree: Optional[ttk.Treeview] = None
        self.detail_sort_key = "status"
        self.detail_sort_reverse = False
        self.task_window: Optional[tk.Toplevel] = None
        self.task_tree: Optional[ttk.Treeview] = None
        self.task_files_window: Optional[tk.Toplevel] = None
        self.task_files_tree: Optional[ttk.Treeview] = None
        self.task_auto_refresh_var = tk.BooleanVar(value=True)
        self.task_page_var = tk.StringVar(value="1/1")
        self.task_page_size = 20
        self.task_offset = 0
        self.task_total = 0
        self.task_selected_ids: set[int] = set()
        self.task_menu: Optional[tk.Menu] = None

        self.server_base_url_var = tk.StringVar(value="http://127.0.0.1:8787")
        self.server_auto_upload_var = tk.BooleanVar(value=True)
        self.server_upload_meta_var = tk.BooleanVar(value=True)
        self.server_ssh_user_var = tk.StringVar(value="ubuntu")
        self.server_ssh_pem_var = tk.StringVar(value="~/Downloads/telegramDownload.pem")
        self.server_download_root_var = tk.StringVar(value="/data/telegram_downloads")
        self.video_type_threshold_var = tk.StringVar(value="60")

        self._build_ui()
        self._load_saved_config()
        self.after(200, self._drain_queue)

    def _build_ui(self) -> None:
        frame = tk.Frame(self, padx=16, pady=16)
        frame.pack(fill=tk.BOTH, expand=True)

        self._add_labeled_entry(frame, "API ID", self.api_id_var)
        self._add_labeled_entry(frame, "API Hash", self.api_hash_var, show="*")
        self._add_labeled_entry(frame, "频道", self.channel_var)

        output_row = tk.Frame(frame)
        output_row.pack(fill=tk.X, pady=(0, 10))
        tk.Label(output_row, text="输出文件夹", width=18, anchor="w").pack(
            side=tk.LEFT
        )
        tk.Entry(output_row, textvariable=self.output_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True
        )
        tk.Button(output_row, text="选择", command=self._pick_folder).pack(
            side=tk.LEFT, padx=(8, 0)
        )
        tk.Button(output_row, text="打开", command=self._open_output).pack(
            side=tk.LEFT, padx=(8, 0)
        )

        server_row = tk.Frame(frame)
        server_row.pack(fill=tk.X, pady=(0, 10))
        tk.Label(server_row, text="任务服务器", width=18, anchor="w").pack(side=tk.LEFT)
        tk.Entry(server_row, textvariable=self.server_base_url_var, width=30).pack(
            side=tk.LEFT, padx=(0, 8)
        )
        tk.Checkbutton(
            server_row, text="自动上传", variable=self.server_auto_upload_var
        ).pack(side=tk.LEFT, padx=(0, 8))
        tk.Checkbutton(
            server_row, text="上传元数据", variable=self.server_upload_meta_var
        ).pack(side=tk.LEFT, padx=(0, 8))
        tk.Button(server_row, text="保存配置", command=self._save_server_config).pack(
            side=tk.LEFT, padx=(8, 0)
        )

        ssh_row = tk.Frame(frame)
        ssh_row.pack(fill=tk.X, pady=(0, 10))
        tk.Label(ssh_row, text="SSH用户", width=18, anchor="w").pack(side=tk.LEFT)
        tk.Entry(ssh_row, textvariable=self.server_ssh_user_var, width=12).pack(
            side=tk.LEFT, padx=(0, 8)
        )
        tk.Label(ssh_row, text="PEM路径", width=8, anchor="w").pack(side=tk.LEFT)
        tk.Entry(ssh_row, textvariable=self.server_ssh_pem_var, width=36).pack(
            side=tk.LEFT, padx=(0, 8)
        )
        tk.Label(ssh_row, text="下载根目录", width=10, anchor="w").pack(
            side=tk.LEFT
        )
        tk.Entry(ssh_row, textvariable=self.server_download_root_var, width=18).pack(
            side=tk.LEFT, padx=(0, 8)
        )
        tk.Label(ssh_row, text="短视频阀值(秒)", width=12, anchor="w").pack(
            side=tk.LEFT
        )
        tk.Entry(ssh_row, textvariable=self.video_type_threshold_var, width=6).pack(
            side=tk.LEFT, padx=(0, 8)
        )
        tk.Button(ssh_row, text="同步Session", command=self._sync_session_to_server).pack(
            side=tk.LEFT
        )

        btn_row = tk.Frame(frame)
        btn_row.pack(fill=tk.X, pady=(0, 10))
        self.login_btn = tk.Button(btn_row, text="登录", command=self._login)
        self.login_btn.pack(side=tk.LEFT)
        self.scan_btn = tk.Button(btn_row, text="检测视频", command=self._toggle_scan)
        self.scan_btn.pack(side=tk.LEFT, padx=(8, 0))
        self.start_btn = tk.Button(btn_row, text="开始下载", command=self._toggle_download)
        self.start_btn.pack(side=tk.LEFT, padx=(8, 0))
        tk.Button(btn_row, text="提交任务", command=self._submit_task).pack(
            side=tk.LEFT, padx=(8, 0)
        )
        tk.Button(btn_row, text="校验频道", command=self._validate_channel).pack(
            side=tk.LEFT, padx=(8, 0)
        )

        status_row = tk.Frame(frame)
        status_row.pack(fill=tk.X, pady=(0, 4))
        ttk.Progressbar(
            status_row,
            variable=self.progress_var,
            maximum=100,
        ).pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Label(status_row, textvariable=self.status_var, width=28, anchor="w").pack(
            side=tk.LEFT, padx=(8, 0)
        )
        tk.Button(status_row, text="详细", command=self._open_detail_window).pack(
            side=tk.LEFT, padx=(8, 0)
        )
        tk.Button(status_row, text="任务列表", command=self._open_task_window).pack(
            side=tk.LEFT, padx=(8, 0)
        )

        status_text_row = tk.Frame(frame)
        status_text_row.pack(fill=tk.X, pady=(0, 8))
        tk.Label(status_text_row, text="状态：", width=6, anchor="w").pack(
            side=tk.LEFT
        )
        tk.Label(status_text_row, textvariable=self.status_text_var, anchor="w").pack(
            side=tk.LEFT, fill=tk.X, expand=True
        )
        tk.Label(status_text_row, text="登录：", width=6, anchor="w").pack(
            side=tk.LEFT
        )
        tk.Label(status_text_row, textvariable=self.login_status_var, anchor="w").pack(
            side=tk.LEFT
        )

        preview_row = tk.Frame(frame)
        preview_row.pack(fill=tk.BOTH, expand=False, pady=(0, 10))
        header_row = tk.Frame(preview_row)
        header_row.pack(fill=tk.X)
        tk.Label(header_row, text="频道视频列表（点击第一列勾选，点击视频名预览）").pack(
            side=tk.LEFT
        )
        tk.Button(header_row, text="删除", command=self._delete_selected).pack(
            side=tk.RIGHT, padx=(8, 0)
        )
        self.select_all_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            header_row,
            text="全选",
            variable=self.select_all_var,
            command=self._toggle_select_all,
        ).pack(side=tk.RIGHT)
        preview_frame = tk.Frame(preview_row)
        preview_frame.pack(fill=tk.BOTH, expand=True)
        columns = ("pick", "name", "size", "tags", "caption")
        self.preview_tree = ttk.Treeview(
            preview_frame,
            columns=columns,
            show="headings",
            selectmode="extended",
            height=8,
        )
        self.preview_tree.heading("pick", text="选")
        self.preview_tree.heading("name", text="视频名称")
        self.preview_tree.heading("size", text="大小")
        self.preview_tree.heading("tags", text="标签")
        self.preview_tree.heading("caption", text="简介")
        self.preview_tree.column("pick", width=40, anchor="center")
        self.preview_tree.column("name", width=220, anchor="w")
        self.preview_tree.column("size", width=80, anchor="center")
        self.preview_tree.column("tags", width=140, anchor="w")
        self.preview_tree.column("caption", width=360, anchor="w")
        self.preview_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.preview_tree.bind("<Button-1>", self._on_preview_click)
        preview_scroll = tk.Scrollbar(preview_frame, command=self.preview_tree.yview)
        preview_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.preview_tree.config(yscrollcommand=preview_scroll.set)

        log_box = ttk.Notebook(frame)
        log_box.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        log_tab = tk.Frame(log_box)
        task_log_tab = tk.Frame(log_box)
        log_box.add(log_tab, text="日志")
        log_box.add(task_log_tab, text="任务日志")
        self.log = tk.Text(log_tab, height=10, state=tk.DISABLED)
        self.log.pack(fill=tk.BOTH, expand=True)
        self.task_log = tk.Text(task_log_tab, height=10, state=tk.DISABLED)
        self.task_log.pack(fill=tk.BOTH, expand=True)

        history_row = tk.Frame(frame)
        history_row.pack(fill=tk.BOTH, expand=False, pady=(0, 10))
        tk.Label(history_row, text="历史记录").pack(anchor="w")
        list_frame = tk.Frame(history_row)
        list_frame.pack(fill=tk.BOTH, expand=True)
        self.history = tk.Listbox(list_frame, height=6)
        self.history.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = tk.Scrollbar(list_frame, command=self.history.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.history.config(yscrollcommand=scrollbar.set)
        tk.Button(history_row, text="刷新历史", command=self._refresh_history).pack(
            anchor="w", pady=(4, 0)
        )

        bottom_row = tk.Frame(frame)
        bottom_row.pack(fill=tk.X, pady=(10, 0))
        tk.Label(bottom_row, text=f"版本 {APP_VERSION}").pack(side=tk.LEFT)
        tk.Button(bottom_row, text="检查更新", command=self._check_update).pack(
            side=tk.LEFT, padx=(8, 0)
        )

        self._set_running(False)
        self._refresh_history()

    def _set_running(self, running: bool) -> None:
        state = tk.DISABLED if running else tk.NORMAL
        self.start_btn.config(state=tk.NORMAL if not running else tk.NORMAL)
        if running and self.current_task == "scan":
            self.scan_btn.config(state=tk.NORMAL)
        else:
            self.scan_btn.config(state=state)
        self.login_btn.config(state=state)
        if not running and self.status_text_var.get() == "准备下载...":
            self.status_text_var.set("就绪")
        if not running and self.status_text_var.get().endswith("中..."):
            self.status_text_var.set("就绪")

    def _add_labeled_entry(
        self,
        parent: tk.Widget,
        label: str,
        var: tk.StringVar,
        show: Optional[str] = None,
    ) -> None:
        row = tk.Frame(parent)
        row.pack(fill=tk.X, pady=(0, 10))
        tk.Label(row, text=label, width=18, anchor="w").pack(side=tk.LEFT)
        entry = (
            tk.Entry(row, textvariable=var, show=show)
            if show
            else tk.Entry(row, textvariable=var)
        )
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

    def _pick_folder(self) -> None:
        chosen = filedialog.askdirectory()
        if chosen:
            self.output_var.set(chosen)

    def _open_output(self) -> None:
        output_dir = self.output_var.get().strip()
        if output_dir:
            subprocess.run(["open", output_dir], check=False)

    def _save_server_config(self) -> None:
        output_dir = Path(self.output_var.get().strip())
        save_config(
            output_dir,
            {
                "api_id": self.api_id_var.get().strip(),
                "api_hash": self.api_hash_var.get().strip(),
                "server_base_url": self.server_base_url_var.get().strip(),
                "server_auto_upload": self.server_auto_upload_var.get(),
                "server_upload_meta": self.server_upload_meta_var.get(),
                "server_ssh_user": self.server_ssh_user_var.get().strip(),
                "server_ssh_pem": self.server_ssh_pem_var.get().strip(),
                "server_download_root": self.server_download_root_var.get().strip(),
                "video_type_threshold_seconds": self.video_type_threshold_var.get().strip(),
            },
        )
        messagebox.showinfo("提示", "服务器配置已保存。")

    def _sync_session_to_server(self) -> None:
        base_url = self.server_base_url_var.get().strip().rstrip("/")
        if not base_url:
            messagebox.showerror("错误", "请先填写任务服务器地址。")
            return
        host = base_url.replace("http://", "").replace("https://", "")
        if ":" in host:
            host = host.split(":", 1)[0]
        user = self.server_ssh_user_var.get().strip() or "ubuntu"
        pem_path = self.server_ssh_pem_var.get().strip()
        download_root = self.server_download_root_var.get().strip() or "/data/telegram_downloads"
        if not pem_path:
            messagebox.showerror("错误", "请填写 PEM 路径。")
            return
        local_dir = Path(self.output_var.get().strip())
        session_files = sorted(local_dir.glob("user_session.session*"))
        if not session_files:
            messagebox.showerror("错误", f"本地未找到 session：{local_dir}/user_session.session*")
            return
        ssh_opts = [
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            "-o",
            "IdentitiesOnly=yes",
        ]
        for session_file in session_files:
            target_path = (
                f"{user}@{host}:{download_root}/user_session.session"
                if session_file.name == "user_session.session"
                else f"{user}@{host}:{download_root}/{session_file.name}"
            )
            cmd = [
                "scp",
                *ssh_opts,
                "-i",
                os.path.expanduser(pem_path),
                str(session_file),
                target_path,
            ]
            self._log(f"同步Session到服务器：{session_file.name}")
            try:
                subprocess.run(cmd, check=True)
            except subprocess.CalledProcessError as exc:
                self._log(f"同步失败：{exc}")
                messagebox.showerror("错误", f"同步失败：{exc}")
                return
        verify_cmd = [
            "ssh",
            *ssh_opts,
            "-i",
            os.path.expanduser(pem_path),
            f"{user}@{host}",
            f"test -f {download_root}/user_session.session",
        ]
        try:
            subprocess.run(verify_cmd, check=True)
        except subprocess.CalledProcessError:
            self._log("同步完成，但服务器未检测到 session 文件。")
            messagebox.showwarning("提示", "同步完成，但服务器未检测到 session 文件。")
            return
        messagebox.showinfo("提示", "Session 同步成功。")

    def _load_saved_config(self) -> None:
        output_dir = Path(self.output_var.get())
        config = load_config(output_dir)
        if config.get("api_id"):
            self.api_id_var.set(config["api_id"])
        if config.get("api_hash"):
            self.api_hash_var.set(config["api_hash"])
        if config.get("server_base_url"):
            self.server_base_url_var.set(config["server_base_url"])
        if config.get("server_auto_upload") is not None:
            self.server_auto_upload_var.set(bool(config.get("server_auto_upload")))
        if config.get("server_upload_meta") is not None:
            self.server_upload_meta_var.set(bool(config.get("server_upload_meta")))
        if config.get("server_ssh_user"):
            self.server_ssh_user_var.set(config["server_ssh_user"])
        if config.get("server_ssh_pem"):
            self.server_ssh_pem_var.set(config["server_ssh_pem"])
        if config.get("server_download_root"):
            self.server_download_root_var.set(config["server_download_root"])
        if config.get("video_type_threshold_seconds") is not None:
            self.video_type_threshold_var.set(
                str(config.get("video_type_threshold_seconds"))
            )

    def _normalize_channel(self, raw: str) -> str:
        channel = raw.strip()
        if channel.startswith("https://t.me/"):
            channel = channel.replace("https://t.me/", "")
        if channel.startswith("t.me/"):
            channel = channel.replace("t.me/", "")
        if channel.startswith("@"):
            channel = channel[1:]
        if channel.startswith("-100") and channel[4:].isdigit():
            return channel
        if not channel or not channel.replace("_", "").isalnum():
            raise ValueError("频道必须是 Telegram 用户名或 t.me 链接。")
        if not (5 <= len(channel) <= 32):
            raise ValueError("频道用户名长度必须是 5-32。")
        return f"@{channel}"

    def _validate_channel(self) -> None:
        try:
            normalized = self._normalize_channel(self.channel_var.get())
            self.channel_var.set(normalized)
        except ValueError as exc:
            messagebox.showerror("频道错误", str(exc))
            return
        messagebox.showinfo("OK", "频道格式正确。")

    def _start(self) -> None:
        self._download_selected()

    def _login(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("运行中", "当前已有任务在运行。")
            return

        api_id = self.api_id_var.get().strip()
        api_hash = self.api_hash_var.get().strip()
        output_dir = Path(self.output_var.get().strip())

        if not api_id or not api_hash:
            messagebox.showerror("错误", "必须填写 API ID 和 API Hash。")
            return

        save_config(output_dir, {"api_id": api_id, "api_hash": api_hash})
        self._set_running(True)
        self.pause_event.clear()
        self.stop_event.clear()
        self.status_text_var.set("登录中...")
        self._log("开始登录...")

        def worker() -> None:
            try:
                run_login(
                    output_dir=output_dir,
                    api_id=api_id,
                    api_hash=api_hash,
                    status_cb=lambda msg: self.event_queue.put(
                        {"type": "log", "message": msg}
                    ),
                    get_phone_cb=self._request_phone,
                    get_code_cb=lambda: self._request_prompt(
                        "验证码", "请输入 Telegram 登录验证码"
                    ),
                    get_password_cb=lambda: self._request_prompt(
                        "两步验证密码", "请输入 Telegram 两步验证密码"
                    ),
                    allow_prompt=False,
                )
                self.event_queue.put({"type": "log", "message": "登录完成"})
            except Exception as exc:  # pragma: no cover - UI path
                self.event_queue.put({"type": "log", "message": f"错误：{exc}"})
            finally:
                self.event_queue.put({"type": "done"})

        self.worker = threading.Thread(target=worker, daemon=True)
        self.worker.start()

    def _scan(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("运行中", "当前已有任务在运行。")
            return

        api_id = self.api_id_var.get().strip()
        api_hash = self.api_hash_var.get().strip()
        output_dir = Path(self.output_var.get().strip())

        try:
            channel = self._normalize_channel(self.channel_var.get())
        except ValueError as exc:
            messagebox.showerror("错误", str(exc))
            return

        start_date = None
        end_date = None

        if not api_id or not api_hash:
            messagebox.showerror("错误", "必须填写 API ID 和 API Hash。")
            return

        save_config(output_dir, {"api_id": api_id, "api_hash": api_hash})
        self.current_task = "scan"
        self._set_running(True)
        self.pause_event.clear()
        self.stop_event.clear()
        self._log("开始检测频道视频...")
        self.status_text_var.set("检测中...")
        self.preview_tree.delete(*self.preview_tree.get_children())
        self.preview_rows.clear()
        self.selected_ids.clear()
        self.select_all_var.set(False)
        self.scan_btn.config(text="暂停检测")
        self.selected_ids.clear()

        def worker() -> None:
            try:
                items = run_list(
                    channel=channel,
                    output_dir=output_dir,
                    api_id=api_id,
                    api_hash=api_hash,
                    start_date=start_date,
                    end_date=end_date,
                    status_cb=lambda msg: self.event_queue.put(
                        {"type": "log", "message": msg}
                    ),
                    pause_event=self.pause_event,
                    stop_event=self.stop_event,
                    get_phone_cb=self._request_phone,
                    get_code_cb=lambda: self._request_prompt(
                        "验证码", "请输入 Telegram 登录验证码"
                    ),
                    get_password_cb=lambda: self._request_prompt(
                        "两步验证密码", "请输入 Telegram 两步验证密码"
                    ),
                    allow_prompt=False,
                )
                self.event_queue.put(
                    {"type": "preview", "items": [item.__dict__ for item in items]}
                )
            except Exception as exc:  # pragma: no cover - UI path
                self.event_queue.put({"type": "log", "message": f"错误：{exc}"})
            finally:
                self.event_queue.put({"type": "done"})

        self.worker = threading.Thread(target=worker, daemon=True)
        self.worker.start()

    def _download_selected(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("运行中", "当前已有任务在运行。")
            return

        selected = set(self.preview_tree.selection()) | self.selected_ids
        if not selected:
            messagebox.showinfo("提示", "请先选择要下载的视频。")
            return

        api_id = self.api_id_var.get().strip()
        api_hash = self.api_hash_var.get().strip()
        output_dir = Path(self.output_var.get().strip())

        try:
            channel = self._normalize_channel(self.channel_var.get())
        except ValueError as exc:
            messagebox.showerror("错误", str(exc))
            return

        if not api_id or not api_hash:
            messagebox.showerror("错误", "必须填写 API ID 和 API Hash。")
            return

        ids = {int(self.preview_rows[item_id]["message_id"]) for item_id in selected}
        self.active_allowed_ids = set(ids)
        self.progress_details = {
            msg_id: {"status": "待下载", "bytes_downloaded": 0, "bytes_total": None}
            for msg_id in ids
        }
        self._refresh_detail_rows()
        save_config(output_dir, {"api_id": api_id, "api_hash": api_hash})
        self.current_task = "download"
        self._set_running(True)
        self.pause_event.clear()
        self.stop_event.clear()
        self.progress_var.set(0.0)
        self.status_var.set("开始中...")
        self.status_text_var.set("准备下载选中项...")
        self._log(f"开始下载选中视频：{len(ids)}")
        self.start_btn.config(text="暂停下载")

        def worker() -> None:
            try:
                total = run_download(
                    channel=channel,
                    max_videos=len(ids),
                    output_dir=output_dir,
                    api_id=api_id,
                    api_hash=api_hash,
                    allowed_ids=self.active_allowed_ids,
                    status_cb=lambda msg: self.event_queue.put(
                        {"type": "log", "message": msg}
                    ),
                    progress_cb=lambda info: self.event_queue.put(
                        {"type": "progress", "info": info}
                    ),
                    pause_event=self.pause_event,
                    stop_event=self.stop_event,
                    get_phone_cb=self._request_phone,
                    get_code_cb=lambda: self._request_prompt(
                        "验证码", "请输入 Telegram 登录验证码"
                    ),
                    get_password_cb=lambda: self._request_prompt(
                        "两步验证密码", "请输入 Telegram 两步验证密码"
                    ),
                    allow_prompt=False,
                )
                self.event_queue.put(
                    {"type": "log", "message": f"完成，已下载：{total}"}
                )
            except Exception as exc:  # pragma: no cover - UI path
                self.event_queue.put({"type": "log", "message": f"错误：{exc}"})
            finally:
                self.event_queue.put({"type": "done"})

        self.worker = threading.Thread(target=worker, daemon=True)
        self.worker.start()

    def _submit_task(self) -> None:
        selected = set(self.preview_tree.selection()) | self.selected_ids
        if not selected:
            messagebox.showinfo("提示", "请先选择要提交的视频。")
            return
        base_url = self.server_base_url_var.get().strip().rstrip("/")
        if not base_url:
            messagebox.showerror("错误", "请先填写任务服务器地址。")
            return
        try:
            channel = self._normalize_channel(self.channel_var.get())
        except ValueError as exc:
            messagebox.showerror("错误", str(exc))
            return
        ids = sorted({int(self.preview_rows[item_id]["message_id"]) for item_id in selected})

        output_dir = Path(self.output_var.get().strip())
        save_config(
            output_dir,
            {
                "api_id": self.api_id_var.get().strip(),
                "api_hash": self.api_hash_var.get().strip(),
                "server_base_url": self.server_base_url_var.get().strip(),
                "server_auto_upload": self.server_auto_upload_var.get(),
                "server_upload_meta": self.server_upload_meta_var.get(),
                "video_type_threshold_seconds": self.video_type_threshold_var.get().strip(),
            },
        )

        payload = {
            "channel": channel,
            "message_ids": ids,
            "auto_upload": self.server_auto_upload_var.get(),
            "upload_meta": self.server_upload_meta_var.get(),
        }
        threshold_raw = self.video_type_threshold_var.get().strip()
        if threshold_raw:
            try:
                payload["video_type_threshold_seconds"] = int(threshold_raw)
            except ValueError:
                messagebox.showerror("错误", "短视频阀值必须是整数秒。")
                return
        self.status_var.set("提交中...")
        self.status_text_var.set("正在提交任务到服务器...")
        self._log(f"提交任务：{len(ids)} 个视频")
        self._log_task(f"提交任务：{len(ids)} 个视频")
        try:
            resp = requests.post(
                f"{base_url}/tasks", json=payload, timeout=REQUEST_TIMEOUT
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.Timeout:
            self.status_var.set("提交超时")
            self.status_text_var.set("服务器响应超时")
            self._log("任务提交失败：服务器响应超时，请检查服务器或网络。")
            messagebox.showerror("错误", "任务提交超时，请检查服务器或网络。")
            return
        except Exception as exc:
            self.status_var.set("提交失败")
            self.status_text_var.set("任务提交失败")
            self._log(f"任务提交失败：{exc}")
            messagebox.showerror("错误", f"任务提交失败：{exc}")
            return
        task_id = data.get("id")
        self.status_var.set("已提交")
        self.status_text_var.set("任务已提交，正在刷新任务列表...")
        self._log(f"任务已提交，任务ID：{task_id}")
        self._log_task(f"任务已提交，任务ID：{task_id}")
        self._open_task_window()
        messagebox.showinfo("提示", f"任务已提交，任务ID：{task_id}")

    def _toggle_select_all(self) -> None:
        if self.select_all_var.get():
            self.selected_ids = set(self.preview_rows.keys())
        else:
            self.selected_ids.clear()
        for item_id in self.preview_rows.keys():
            values = list(self.preview_tree.item(item_id, "values"))
            if values:
                values[0] = "☑" if item_id in self.selected_ids else "☐"
                self.preview_tree.item(item_id, values=values)

    def _toggle_download(self) -> None:
        if self.worker and self.worker.is_alive():
            if self.current_task != "download":
                messagebox.showinfo("运行中", "当前正在检测视频，请稍后。")
                return
            if self.pause_event.is_set():
                self.pause_event.clear()
                self.start_btn.config(text="暂停下载")
                self._log("继续下载。")
                self.status_text_var.set("继续下载")
            else:
                self.pause_event.set()
                self.start_btn.config(text="开始下载")
                self._log("暂停下载中（等待当前文件完成）...")
                self.status_text_var.set("暂停下载中（等待当前文件完成）")
            return
        self._download_selected()

    def _toggle_scan(self) -> None:
        if self.worker and self.worker.is_alive():
            if self.current_task != "scan":
                messagebox.showinfo("运行中", "当前正在下载，请稍后。")
                return
            if self.pause_event.is_set():
                self.pause_event.clear()
                self.scan_btn.config(text="暂停检测")
                self._log("继续检测。")
                self.status_text_var.set("继续检测")
            else:
                self.pause_event.set()
                self.scan_btn.config(text="检测视频")
                self._log("暂停检测中（等待当前消息处理完成）...")
                self.status_text_var.set("暂停检测中（等待当前消息处理完成）")
            return
        self._scan()

    def _open_detail_window(self) -> None:
        if self.detail_window and self.detail_window.winfo_exists():
            self.detail_window.lift()
            return
        win = tk.Toplevel(self)
        win.title("下载详情")
        win.geometry("720x360")
        self.detail_window = win

        columns = ("name", "progress", "size", "speed", "status")
        tree = ttk.Treeview(win, columns=columns, show="headings", height=10)
        tree.heading("name", text="视频名称", command=lambda: self._sort_detail("name"))
        tree.heading(
            "progress", text="进度", command=lambda: self._sort_detail("progress")
        )
        tree.heading("size", text="大小", command=lambda: self._sort_detail("size"))
        tree.heading("speed", text="速度", command=lambda: self._sort_detail("speed"))
        tree.heading(
            "status", text="状态", command=lambda: self._sort_detail("status")
        )
        tree.column("name", width=260, anchor="w")
        tree.column("progress", width=80, anchor="center")
        tree.column("size", width=120, anchor="center")
        tree.column("speed", width=80, anchor="center")
        tree.column("status", width=120, anchor="center")
        tree.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        self.detail_tree = tree

        btn_row = tk.Frame(win)
        btn_row.pack(fill=tk.X, padx=8, pady=(0, 8))
        tk.Button(btn_row, text="暂停/继续", command=self._toggle_download).pack(
            side=tk.LEFT
        )
        tk.Button(btn_row, text="删除选中", command=self._delete_selected).pack(
            side=tk.LEFT, padx=(8, 0)
        )
        tk.Button(btn_row, text="关闭", command=win.destroy).pack(
            side=tk.RIGHT
        )

        self._refresh_detail_rows()
        self._schedule_detail_refresh()

    def _open_task_window(self) -> None:
        if self.task_window and self.task_window.winfo_exists():
            self.task_window.lift()
            self._refresh_task_window()
            return
        win = tk.Toplevel(self)
        win.title("任务列表")
        win.geometry("860x420")
        self.task_window = win

        toolbar = tk.Frame(win)
        toolbar.pack(fill=tk.X, padx=8, pady=(8, 0))
        tk.Button(toolbar, text="刷新", command=self._refresh_task_window).pack(
            side=tk.LEFT
        )
        tk.Checkbutton(
            toolbar, text="自动刷新", variable=self.task_auto_refresh_var
        ).pack(side=tk.LEFT, padx=(8, 0))
        tk.Button(toolbar, text="文件详情", command=self._open_task_files).pack(
            side=tk.LEFT, padx=(8, 0)
        )
        tk.Button(
            toolbar, text="重试选中", command=lambda: self._perform_task_action("retry")
        ).pack(side=tk.LEFT, padx=(8, 0))
        tk.Button(
            toolbar, text="取消选中", command=lambda: self._perform_task_action("cancel")
        ).pack(side=tk.LEFT, padx=(8, 0))
        tk.Button(
            toolbar, text="删除记录", command=lambda: self._perform_task_action("delete")
        ).pack(side=tk.LEFT, padx=(8, 0))
        tk.Button(
            toolbar, text="清理失败/卡住", command=lambda: self._perform_task_action("clean")
        ).pack(side=tk.LEFT, padx=(8, 0))
        tk.Label(toolbar, textvariable=self.task_page_var).pack(
            side=tk.RIGHT, padx=(8, 0)
        )
        tk.Button(toolbar, text="上一页", command=lambda: self._change_task_page(-1)).pack(
            side=tk.RIGHT
        )
        tk.Button(toolbar, text="下一页", command=lambda: self._change_task_page(1)).pack(
            side=tk.RIGHT, padx=(8, 0)
        )

        columns = (
            "select",
            "id",
            "status",
            "channel",
            "download",
            "upload",
            "updated",
            "detail",
            "error",
        )
        tree = ttk.Treeview(win, columns=columns, show="headings", height=12)
        tree.heading("select", text="选中")
        tree.heading("id", text="ID")
        tree.heading("status", text="状态")
        tree.heading("channel", text="频道")
        tree.heading("download", text="下载进度")
        tree.heading("upload", text="上传进度")
        tree.heading("updated", text="更新时间")
        tree.heading("detail", text="详情")
        tree.heading("error", text="错误")
        tree.column("select", width=50, anchor="center")
        tree.column("id", width=60, anchor="center")
        tree.column("status", width=90, anchor="center")
        tree.column("channel", width=140, anchor="w")
        tree.column("download", width=140, anchor="center")
        tree.column("upload", width=140, anchor="center")
        tree.column("updated", width=140, anchor="center")
        tree.column("detail", width=180, anchor="w")
        tree.column("error", width=180, anchor="w")
        tree.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        self.task_tree = tree
        tree.bind("<Button-1>", self._toggle_task_selection, add=True)
        tree.bind("<Button-3>", self._open_task_context_menu, add=True)
        tree.bind("<Control-Button-1>", self._open_task_context_menu, add=True)

        self._refresh_task_window()

    def _task_api_base(self) -> Optional[str]:
        base_url = self.server_base_url_var.get().strip().rstrip("/")
        return base_url or None

    def _change_task_page(self, delta: int) -> None:
        new_offset = self.task_offset + delta * self.task_page_size
        new_offset = max(0, new_offset)
        if self.task_total:
            max_offset = max(0, ((self.task_total - 1) // self.task_page_size) * self.task_page_size)
            new_offset = min(new_offset, max_offset)
        if new_offset != self.task_offset:
            self.task_offset = new_offset
            self._refresh_task_window()

    def _refresh_task_window(self) -> None:
        if not self.task_tree:
            return
        base_url = self._task_api_base()
        if not base_url:
            messagebox.showinfo("提示", "请先填写任务服务器地址。")
            return
        try:
            resp = requests.get(
                f"{base_url}/tasks",
                params={"limit": self.task_page_size, "offset": self.task_offset},
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            items = data.get("items", [])
            self.task_total = int(data.get("total") or 0)
        except requests.exceptions.Timeout:
            self._log("获取任务列表失败：服务器响应超时，请检查服务器或网络。")
            return
        except Exception as exc:
            self._log(f"获取任务列表失败：{exc}")
            return
        total_pages = max(1, (self.task_total + self.task_page_size - 1) // self.task_page_size)
        current_page = min(total_pages, (self.task_offset // self.task_page_size) + 1)
        self.task_page_var.set(f"{current_page}/{total_pages}")

        self.task_tree.delete(*self.task_tree.get_children())
        for item in items:
            progress_info = {}
            raw_progress = item.get("progress_json")
            if isinstance(raw_progress, str) and raw_progress:
                try:
                    progress_info = json.loads(raw_progress)
                except json.JSONDecodeError:
                    progress_info = {}
            elif isinstance(raw_progress, dict):
                progress_info = raw_progress
            download_text, upload_text = self._format_task_progress(progress_info)
            detail_text = (
                self._format_task_detail(progress_info)
                if isinstance(progress_info, dict)
                else ""
            )
            task_id = item.get("id")
            selected = ""
            try:
                if int(task_id) in self.task_selected_ids:
                    selected = "[x]"
                else:
                    selected = "[ ]"
            except (TypeError, ValueError):
                selected = "[ ]"
            self.task_tree.insert(
                "",
                tk.END,
                values=(
                    selected,
                    item.get("id"),
                    self._format_task_status(item.get("status")),
                    item.get("channel"),
                    download_text,
                    upload_text,
                    self._format_time_jst(item.get("updated_at")),
                    detail_text[:40],
                    (item.get("error") or "")[:30],
                ),
            )
        self._schedule_task_refresh()

    def _schedule_task_refresh(self) -> None:
        if not self.task_window or not self.task_window.winfo_exists():
            return
        if not self.task_auto_refresh_var.get():
            return
        self.task_window.after(3000, self._refresh_task_window)

    @staticmethod
    def _format_task_detail(progress_info: dict) -> str:
        raw_status = str(progress_info.get("status") or "")
        if "Skipped (already in manifest)" in raw_status:
            suffix = raw_status.replace("Skipped (already in manifest)", "").strip()
            suffix = suffix.lstrip(":").strip()
            if suffix:
                return f"已下载过，已跳过：{suffix}"
            return "已下载过，已跳过"
        return raw_status

    def _get_selected_task_id(self) -> Optional[int]:
        if not self.task_tree:
            return None
        selection = self.task_tree.selection()
        if not selection:
            return None
        values = self.task_tree.item(selection[0], "values")
        if not values:
            return None
        try:
            return int(values[1])
        except (TypeError, ValueError):
            return None

    def _get_checked_task_ids(self) -> list[int]:
        ids: set[int] = set(self.task_selected_ids)
        if not ids and self.task_tree:
            for item in self.task_tree.selection():
                values = self.task_tree.item(item, "values")
                if len(values) >= 2:
                    try:
                        ids.add(int(values[1]))
                    except (TypeError, ValueError):
                        continue
        return sorted(ids)

    def _toggle_task_selection(self, event: tk.Event) -> None:
        if not self.task_tree:
            return
        row_id = self.task_tree.identify_row(event.y)
        col_id = self.task_tree.identify_column(event.x)
        if not row_id or col_id != "#1":
            return
        values = self.task_tree.item(row_id, "values")
        if len(values) < 2:
            return
        try:
            task_id = int(values[1])
        except (TypeError, ValueError):
            return
        if task_id in self.task_selected_ids:
            self.task_selected_ids.remove(task_id)
            new_check = "[ ]"
        else:
            self.task_selected_ids.add(task_id)
            new_check = "[x]"
        new_values = list(values)
        new_values[0] = new_check
        self.task_tree.item(row_id, values=new_values)

    def _open_task_context_menu(self, event: tk.Event) -> None:
        if not self.task_tree:
            return
        row_id = self.task_tree.identify_row(event.y)
        if row_id:
            self.task_tree.selection_set(row_id)
            values = self.task_tree.item(row_id, "values")
            if len(values) >= 2:
                try:
                    self.task_selected_ids.add(int(values[1]))
                except (TypeError, ValueError):
                    pass
        if not self.task_menu:
            menu = tk.Menu(self, tearoff=0)
            menu.add_command(
                label="重试选中", command=lambda: self._perform_task_action("retry")
            )
            menu.add_command(
                label="取消选中", command=lambda: self._perform_task_action("cancel")
            )
            menu.add_command(
                label="删除记录", command=lambda: self._perform_task_action("delete")
            )
            menu.add_separator()
            menu.add_command(
                label="清理失败/卡住", command=lambda: self._perform_task_action("clean")
            )
            self.task_menu = menu
        self.task_menu.tk_popup(event.x_root, event.y_root)

    def _perform_task_action(self, action: str) -> None:
        base_url = self._task_api_base()
        if not base_url:
            messagebox.showinfo("提示", "请先填写任务服务器地址。")
            return
        if action == "clean":
            if not messagebox.askyesno("确认清理", "确认清理失败/卡住的任务？"):
                return
            try:
                resp = requests.post(
                    f"{base_url}/tasks/clean_stale", timeout=REQUEST_TIMEOUT
                )
                resp.raise_for_status()
                self._log_task("清理失败/卡住任务：完成")
                messagebox.showinfo("提示", "清理完成。")
            except requests.exceptions.Timeout:
                messagebox.showerror("错误", "清理失败：服务器响应超时。")
            except Exception as exc:
                messagebox.showerror("错误", f"清理失败：{exc}")
            self._refresh_task_window()
            return
        task_ids = self._get_checked_task_ids()
        if not task_ids:
            messagebox.showinfo("提示", "请先选择任务。")
            return
        if action == "delete":
            if not messagebox.askyesno("确认删除", "确认删除选中的任务记录？"):
                return
        if action == "cancel":
            if not messagebox.askyesno("确认取消", "确认取消选中的任务？"):
                return
        for task_id in task_ids:
            try:
                if action == "retry":
                    resp = requests.post(
                        f"{base_url}/tasks/{task_id}/retry", timeout=REQUEST_TIMEOUT
                    )
                elif action == "cancel":
                    resp = requests.post(
                        f"{base_url}/tasks/{task_id}/cancel", timeout=REQUEST_TIMEOUT
                    )
                elif action == "delete":
                    resp = requests.delete(
                        f"{base_url}/tasks/{task_id}", timeout=REQUEST_TIMEOUT
                    )
                else:
                    continue
                resp.raise_for_status()
                self._log_task(f"{action} 任务成功：{task_id}")
            except requests.exceptions.Timeout:
                messagebox.showerror("错误", f"{action} 失败：服务器响应超时。")
                break
            except Exception as exc:
                messagebox.showerror("错误", f"{action} 失败：{exc}")
                break
        self._refresh_task_window()

    def _open_task_files(self) -> None:
        task_id = self._get_selected_task_id()
        if task_id is None:
            messagebox.showinfo("提示", "请先选择任务。")
            return
        if self.task_files_window and self.task_files_window.winfo_exists():
            self.task_files_window.lift()
        else:
            win = tk.Toplevel(self)
            win.title(f"任务文件详情 #{task_id}")
            win.geometry("860x360")
            self.task_files_window = win
            columns = ("name", "size", "downloaded", "speed", "status", "duration")
            tree = ttk.Treeview(win, columns=columns, show="headings", height=10)
            tree.heading("name", text="文件名")
            tree.heading("size", text="总大小")
            tree.heading("downloaded", text="已下载")
            tree.heading("speed", text="速度")
            tree.heading("status", text="状态")
            tree.heading("duration", text="耗时")
            tree.column("name", width=300, anchor="w")
            tree.column("size", width=100, anchor="center")
            tree.column("downloaded", width=120, anchor="center")
            tree.column("speed", width=100, anchor="center")
            tree.column("status", width=80, anchor="center")
            tree.column("duration", width=100, anchor="center")
            tree.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
            self.task_files_tree = tree
        self._refresh_task_files(task_id)

    def _refresh_task_files(self, task_id: int) -> None:
        if not self.task_files_tree:
            return
        base_url = self._task_api_base()
        if not base_url:
            return
        try:
            resp = requests.get(
                f"{base_url}/tasks/{task_id}/files", timeout=REQUEST_TIMEOUT
            )
            resp.raise_for_status()
            items = resp.json().get("items", [])
        except requests.exceptions.Timeout:
            self._log("获取任务文件失败：服务器响应超时。")
            return
        except Exception as exc:
            self._log(f"获取任务文件失败：{exc}")
            return
        self.task_files_tree.delete(*self.task_files_tree.get_children())
        for item in items:
            total = item.get("bytes_total") or 0
            downloaded = item.get("bytes_downloaded") or 0
            speed = item.get("speed_bps")
            started = item.get("started_at")
            finished = item.get("finished_at")
            duration = self._format_duration(started, finished)
            self.task_files_tree.insert(
                "",
                tk.END,
                values=(
                    item.get("file_name") or "",
                    self._format_bytes(int(total)) if total else "--",
                    self._format_bytes(int(downloaded)) if downloaded else "--",
                    self._format_speed(speed),
                    item.get("status") or "",
                    duration,
                ),
            )

    def _refresh_detail_rows(self) -> None:
        if not self.detail_tree:
            return
        self.detail_tree.delete(*self.detail_tree.get_children())
        rows = []
        for msg_id, info in self.progress_details.items():
            row = self.preview_rows.get(str(msg_id), {})
            name = row.get("file_name", f"{msg_id}")
            downloaded = info.get("bytes_downloaded") or 0
            total = info.get("bytes_total")
            progress = "--"
            if total:
                progress = f"{int(downloaded * 100 / total)}%"
            size_text = (
                f"{self._format_bytes(downloaded)}/{self._format_bytes(total)}"
                if total
                else self._format_bytes(downloaded)
            )
            speed = info.get("speed_bps")
            speed_text = self._format_speed(speed) if speed else "--"
            status = info.get("status", "")
            rows.append(
                {
                    "id": str(msg_id),
                    "name": name,
                    "progress": progress,
                    "size": size_text,
                    "speed": speed_text,
                    "status": status,
                    "progress_num": int(progress.replace("%", ""))
                    if progress.endswith("%")
                    else -1,
                    "size_num": total or downloaded,
                    "speed_num": speed or 0,
                }
            )
        rows.sort(
            key=lambda r: r.get(self._detail_sort_key(), ""),
            reverse=self.detail_sort_reverse,
        )
        for row in rows:
            self.detail_tree.insert(
                "",
                tk.END,
                iid=row["id"],
                values=(
                    row["name"],
                    row["progress"],
                    row["size"],
                    row["speed"],
                    row["status"],
                ),
            )

    def _set_status_by_filename(self, file_name: str, status: str) -> None:
        for msg_id, row in self.preview_rows.items():
            if row.get("file_name") == file_name:
                msg_id_int = int(row["message_id"])
                info = self.progress_details.get(msg_id_int, {})
                info["status"] = status
                self.progress_details[msg_id_int] = info
                self._refresh_detail_rows()
                return

    def _detail_sort_key(self) -> str:
        mapping = {
            "name": "name",
            "progress": "progress_num",
            "size": "size_num",
            "speed": "speed_num",
            "status": "status",
        }
        return mapping.get(self.detail_sort_key, "status")

    def _sort_detail(self, key: str) -> None:
        if self.detail_sort_key == key:
            self.detail_sort_reverse = not self.detail_sort_reverse
        else:
            self.detail_sort_key = key
            self.detail_sort_reverse = False
        self._refresh_detail_rows()

    def _schedule_detail_refresh(self) -> None:
        if not self.detail_window or not self.detail_window.winfo_exists():
            return
        self._refresh_detail_rows()
        self.detail_window.after(500, self._schedule_detail_refresh)

    def _delete_selected(self) -> None:
        selected = set(self.preview_tree.selection()) | self.selected_ids
        if self.detail_tree:
            selected |= set(self.detail_tree.selection())
        if not selected:
            messagebox.showinfo("提示", "请先选择要删除的视频。")
            return
        if not messagebox.askyesno("确认删除", "确认删除选中的视频及其本地文件？"):
            return
        for item_id in list(selected):
            self._delete_item(item_id)
        self._refresh_detail_rows()
        self._refresh_history()

    def _delete_item(self, item_id: str) -> None:
        row = self.preview_rows.get(item_id)
        if not row:
            return
        msg_id = int(row["message_id"])
        output_dir = Path(self.output_var.get().strip())
        local_path = output_dir / row.get("file_name", "")
        meta_path = output_dir / f"{Path(row.get('file_name', '')).stem}.json"
        if local_path.exists():
            local_path.unlink()
        if meta_path.exists():
            meta_path.unlink()
        try:
            from downloader_core import remove_manifest_entry

            remove_manifest_entry(output_dir, msg_id)
        except Exception:
            pass
        if self.active_allowed_ids and msg_id in self.active_allowed_ids:
            self.active_allowed_ids.remove(msg_id)
        self.progress_details.pop(msg_id, None)
        self.selected_ids.discard(item_id)
        if item_id in self.preview_tree.get_children():
            self.preview_tree.delete(item_id)
        self.preview_rows.pop(item_id, None)
        self.select_all_var.set(
            len(self.selected_ids) == len(self.preview_rows) and self.preview_rows
        )


    def _refresh_history(self) -> None:
        output_dir = Path(self.output_var.get().strip())
        rows = read_manifest(output_dir)
        self.history.delete(0, tk.END)
        for row in rows[-200:]:
            caption = row.get("caption", "").replace("\n", " ")
            line = f"{row.get('date_utc','')} | {row.get('file_name','')} | {self._truncate(caption, 80)}"
            self.history.insert(tk.END, line)

    def _truncate(self, text: str, max_len: int) -> str:
        if len(text) <= max_len:
            return text
        return text[: max_len - 3] + "..."

    def _check_update(self) -> None:
        if not UPDATE_URL:
            messagebox.showinfo(
                "更新",
                "未配置更新地址。请设置 TELEGRAM_DOWNLOADER_UPDATE_URL。",
            )
            return
        try:
            with urllib.request.urlopen(UPDATE_URL, timeout=6) as resp:
                data = json_load(resp.read().decode("utf-8"))
        except Exception:
            messagebox.showerror("更新", "检查更新失败。")
            return
        latest = data.get("version", "")
        url = data.get("url", "")
        if not latest:
            messagebox.showinfo("更新", "没有获取到版本信息。")
            return
        if self._compare_versions(latest, APP_VERSION) > 0:
            if messagebox.askyesno(
                "更新", f"发现新版本 {latest}，是否打开下载页面？"
            ):
                if url:
                    subprocess.run(["open", url], check=False)
        else:
            messagebox.showinfo("更新", "已经是最新版本。")

    def _compare_versions(self, a: str, b: str) -> int:
        def parts(v: str) -> list[int]:
            return [int(p) for p in v.split(".") if p.isdigit()]

        pa = parts(a)
        pb = parts(b)
        for left, right in zip(pa, pb):
            if left != right:
                return 1 if left > right else -1
        if len(pa) == len(pb):
            return 0
        return 1 if len(pa) > len(pb) else -1

    def _drain_queue(self) -> None:
        while True:
            try:
                event = self.event_queue.get_nowait()
            except queue.Empty:
                break
            etype = event.get("type")
            if etype == "done":
                self._set_running(False)
                self.scan_btn.config(text="检测视频")
                self.start_btn.config(text="开始下载")
                self.current_task = None
                if self.status_text_var.get().startswith("检测中"):
                    self.status_text_var.set("检测完成")
                elif self.status_text_var.get().startswith("开始"):
                    self.status_text_var.set("完成")
                continue
            if etype == "log":
                message = event.get("message", "")
                self._log(message)
                if message:
                    self.status_text_var.set(message)
                if message in ("已登录", "登录完成"):
                    self.login_status_var.set("已登录")
                if message.startswith("Done: "):
                    self._set_status_by_filename(message.replace("Done: ", ""), "完成")
                if message.startswith("Recorded existing: "):
                    self._set_status_by_filename(
                        message.replace("Recorded existing: ", ""), "已存在"
                    )
                if message.startswith("跳过已移除："):
                    msg_id = message.replace("跳过已移除：", "").strip()
                    if msg_id.isdigit():
                        msg_id_int = int(msg_id)
                        info = self.progress_details.get(msg_id_int, {})
                        info["status"] = "已移除"
                        self.progress_details[msg_id_int] = info
                        self._refresh_detail_rows()
                if message.startswith("错误："):
                    messagebox.showerror("错误", message)
                continue
            if etype == "prompt":
                self._handle_prompt(event)
                continue
            if etype == "preview":
                self._render_preview(event.get("items", []))
                continue
            if etype == "preview_open":
                item_id = event.get("item_id")
                if item_id:
                    row = self.preview_rows.get(item_id)
                    if row:
                        channel = self._normalize_channel(self.channel_var.get())
                        if channel.startswith("@"):
                            link = f"https://t.me/{channel[1:]}/{row['message_id']}"
                            subprocess.run(["open", link], check=False)
                continue
            if etype == "progress":
                self._handle_progress(event.get("info", {}))
        self.after(200, self._drain_queue)

    def _handle_progress(self, info: dict) -> None:
        current = info.get("current_index", 0)
        total = info.get("total", 0) or 0
        bytes_downloaded = info.get("bytes_downloaded", 0) or 0
        bytes_total = info.get("bytes_total")
        speed = info.get("speed_bps")
        file_name = info.get("file_name", "")
        message_id = info.get("message_id")
        percent = (current / total * 100) if total else 0
        self.progress_var.set(percent)
        size_text = ""
        if bytes_total:
            size_text = f"{self._format_bytes(bytes_downloaded)}/{self._format_bytes(bytes_total)}"
        speed_text = f"{self._format_speed(speed)}" if speed else "--"
        self.status_var.set(f"{current}/{total} {size_text} {speed_text}")
        if file_name:
            self.status_text_var.set(f"下载中：{file_name}")
        if message_id is not None:
            self.current_message_id = int(message_id)
            status = "下载中"
            if bytes_total and bytes_downloaded >= bytes_total:
                status = "完成"
            self.progress_details[int(message_id)] = {
                "bytes_downloaded": bytes_downloaded,
                "bytes_total": bytes_total,
                "speed_bps": speed,
                "status": status,
            }
            self._refresh_detail_rows()

    def _render_preview(self, items: list[dict]) -> None:
        for row in items:
            item_id = str(row["message_id"])
            tags = ",".join(row.get("tags", []))
            caption = (row.get("caption") or "").replace("\n", " ")
            size_text = self._format_bytes(row.get("file_size") or 0)
            self.preview_rows[item_id] = row
            self.preview_tree.insert(
                "",
                tk.END,
                iid=item_id,
                values=(
                    "☑" if item_id in self.selected_ids else "☐",
                    row.get("file_name", ""),
                    size_text,
                    tags,
                    self._truncate(caption, 120),
                ),
            )

    def _on_preview_click(self, event: tk.Event) -> None:
        row_id = self.preview_tree.identify_row(event.y)
        col = self.preview_tree.identify_column(event.x)
        if not row_id:
            return
        if col == "#1":
            if row_id in self.selected_ids:
                self.selected_ids.remove(row_id)
            else:
                self.selected_ids.add(row_id)
            values = list(self.preview_tree.item(row_id, "values"))
            if values:
                values[0] = "☑" if row_id in self.selected_ids else "☐"
                self.preview_tree.item(row_id, values=values)
            self.select_all_var.set(
                len(self.selected_ids) == len(self.preview_rows) and self.preview_rows
            )
            return
        if col == "#2":
            self._preview_row(row_id)

    def _preview_row(self, item_id: str) -> None:
        row = self.preview_rows.get(item_id)
        if not row:
            return
        channel = self._normalize_channel(self.channel_var.get())
        if channel.startswith("@"):
            link = f"https://t.me/{channel[1:]}/{row['message_id']}"
            subprocess.run(["open", link], check=False)
            return


    def _format_bytes(self, value: int) -> str:
        units = ["B", "KB", "MB", "GB"]
        size = float(value)
        for unit in units:
            if size < 1024:
                return f"{size:.1f}{unit}"
            size /= 1024
        return f"{size:.1f}TB"

    def _format_task_progress(self, info: dict) -> tuple[str, str]:
        download_text = "--"
        upload_text = "--"
        if info:
            download_info = info.get("download") if isinstance(info.get("download"), dict) else info
            upload_info = info.get("upload") if isinstance(info.get("upload"), dict) else info
            downloaded = download_info.get(
                "task_bytes_downloaded", download_info.get("bytes_downloaded")
            )
            total = download_info.get(
                "task_bytes_total", download_info.get("bytes_total")
            )
            if isinstance(downloaded, int) or isinstance(downloaded, float):
                if total:
                    percent = int(downloaded * 100 / total)
                    download_text = f"{percent}% ({self._format_bytes(int(downloaded))}/{self._format_bytes(int(total))})"
                else:
                    download_text = f"{self._format_bytes(int(downloaded))}"
            sent = upload_info.get("sent")
            upload_total = upload_info.get("total")
            percent = upload_info.get("percent")
            if isinstance(percent, int):
                upload_text = f"{percent}%"
            elif (isinstance(sent, int) or isinstance(sent, float)) and upload_total:
                percent = int(sent * 100 / upload_total)
                upload_text = f"{percent}% ({self._format_bytes(int(sent))}/{self._format_bytes(int(upload_total))})"
            download_text = self._append_task_count(
                download_text, info.get("download_count")
            )
            upload_text = self._append_task_count(upload_text, info.get("upload_count"))
        return download_text, upload_text

    @staticmethod
    def _append_task_count(text: str, count_info: Optional[dict]) -> str:
        if not isinstance(count_info, dict):
            return text
        done = count_info.get("done")
        total = count_info.get("total")
        if isinstance(done, int) and isinstance(total, int) and total > 0:
            suffix = f"({done}/{total})"
            if text and text != "--":
                return f"{text} {suffix}"
            return suffix
        return text

    @staticmethod
    def _format_task_status(status: Optional[str]) -> str:
        mapping = {
            "pending": "等待中",
            "running": "进行中",
            "done": "已完成",
            "failed": "失败",
            "cancelled": "已取消",
            "cancel_requested": "取消中",
            "stale": "卡住",
        }
        if not status:
            return ""
        return mapping.get(status, status)

    def _format_time_jst(self, iso_text: Optional[str]) -> str:
        if not iso_text:
            return ""
        try:
            text = iso_text.strip()
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            dt = datetime.fromisoformat(text)
        except Exception:
            return iso_text
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        jst = dt.astimezone(timezone(timedelta(hours=9)))
        return jst.strftime("%Y-%m-%d %H:%M:%S")

    def _format_duration(self, started_at: Optional[str], finished_at: Optional[str]) -> str:
        if not started_at:
            return "--"
        try:
            start_text = started_at.replace("Z", "+00:00")
            start = datetime.fromisoformat(start_text)
        except Exception:
            return "--"
        end = None
        if finished_at:
            try:
                end_text = finished_at.replace("Z", "+00:00")
                end = datetime.fromisoformat(end_text)
            except Exception:
                end = None
        if end is None:
            end = datetime.now(timezone.utc)
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        duration = end - start
        seconds = int(duration.total_seconds())
        if seconds < 0:
            return "--"
        return f"{seconds//60:02d}:{seconds%60:02d}"

    def _format_speed(self, value: Optional[float]) -> str:
        if value is None:
            return "--"
        return f"{self._format_bytes(int(value))}/s"

    def _log(self, text: str) -> None:
        self.log.config(state=tk.NORMAL)
        self.log.insert(tk.END, text + "\n")
        self.log.see(tk.END)
        self.log.config(state=tk.DISABLED)

    def _log_task(self, text: str) -> None:
        if not hasattr(self, "task_log") or self.task_log is None:
            return
        self.task_log.config(state=tk.NORMAL)
        self.task_log.insert(tk.END, text + "\n")
        self.task_log.see(tk.END)
        self.task_log.config(state=tk.DISABLED)

    def _request_prompt(self, title: str, message: str) -> str:
        response_queue: queue.Queue[str] = queue.Queue(maxsize=1)
        self.event_queue.put(
            {
                "type": "prompt",
                "title": title,
                "message": message,
                "response_queue": response_queue,
            }
        )
        return response_queue.get()

    def _handle_prompt(self, event: dict) -> None:
        with self.prompt_lock:
            response_queue = event.get("response_queue")
            if not isinstance(response_queue, queue.Queue):
                return
            title = event.get("title", "输入")
            message = event.get("message", "")
            value = simpledialog.askstring(title, message, parent=self)
            response_queue.put(value or "")

    def _request_phone(self) -> str:
        while True:
            code = self._request_prompt(
                "国家/地区区号", "请输入国家区号（如 86 / 1）"
            )
            if not code:
                return ""
            code = code.strip().lstrip("+")
            if not code.isdigit():
                messagebox.showerror("错误", "国家区号只能是数字。")
                continue

            number = self._request_prompt("手机号", "请输入手机号（不含区号）")
            if not number:
                return ""
            number = number.strip().replace(" ", "").replace("-", "")
            if not number.isdigit():
                messagebox.showerror("错误", "手机号只能包含数字。")
                continue
            if len(number) < 5:
                messagebox.showerror("错误", "手机号长度过短。")
                continue
            return f"+{code}{number}"


def json_load(text: str) -> dict:
    try:
        return json.loads(text)
    except Exception:
        return {}


if __name__ == "__main__":
    app = App()
    app.mainloop()
