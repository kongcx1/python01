import json
import queue
import threading
import time
import tkinter as tk
from contextlib import redirect_stderr, redirect_stdout
from tkinter import filedialog, messagebox, scrolledtext

import okx_bot


class QueueWriter:
    def __init__(self, q: queue.Queue) -> None:
        self.q = q

    def write(self, msg: str) -> None:
        if msg:
            self.q.put(msg)

    def flush(self) -> None:
        return


class OKXTraderUI(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("OKX 现货自动交易（演示）")
        self.geometry("980x720")

        self.log_queue: queue.Queue[str] = queue.Queue()
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.current_config_path = "okx_config.json"

        self._build_ui()
        self.after(200, self._poll_log_queue)

    def _build_ui(self) -> None:
        api_frame = tk.LabelFrame(self, text="API 配置")
        api_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=6)
        api_frame.columnconfigure(1, weight=1)

        trade_frame = tk.LabelFrame(self, text="交易配置")
        trade_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=6)
        trade_frame.columnconfigure(1, weight=1)

        strat_frame = tk.LabelFrame(self, text="策略阈值")
        strat_frame.grid(row=2, column=0, sticky="ew", padx=10, pady=6)
        strat_frame.columnconfigure(1, weight=1)

        risk_frame = tk.LabelFrame(self, text="风控配置")
        risk_frame.grid(row=3, column=0, sticky="ew", padx=10, pady=6)
        risk_frame.columnconfigure(1, weight=1)

        loop_frame = tk.LabelFrame(self, text="循环配置")
        loop_frame.grid(row=4, column=0, sticky="ew", padx=10, pady=6)
        loop_frame.columnconfigure(1, weight=1)

        self.api_key_var = tk.StringVar()
        self.api_secret_var = tk.StringVar()
        self.passphrase_var = tk.StringVar()
        self.base_url_var = tk.StringVar(value="https://www.okx.com")

        self._add_entry(api_frame, "API Key", self.api_key_var, 0)
        self._add_entry(api_frame, "API Secret", self.api_secret_var, 1, show="*")
        self._add_entry(api_frame, "Passphrase", self.passphrase_var, 2, show="*")
        self._add_entry(api_frame, "Base URL", self.base_url_var, 3)

        self.inst_id_var = tk.StringVar(value="BTC-USDT")
        self.td_mode_var = tk.StringVar(value="cash")
        self.dry_run_var = tk.BooleanVar(value=True)
        self._add_entry(trade_frame, "交易对 inst_id", self.inst_id_var, 0)
        self._add_entry(trade_frame, "交易模式 td_mode", self.td_mode_var, 1)
        tk.Checkbutton(trade_frame, text="仅模拟 dry_run", variable=self.dry_run_var).grid(
            row=2, column=1, sticky="w", padx=6, pady=4
        )

        self.buy_below_var = tk.StringVar()
        self.sell_above_var = tk.StringVar()
        self.strategy_type_var = tk.StringVar(value="threshold")
        self.strategy_bar_var = tk.StringVar(value="1m")
        self.ma_short_var = tk.StringVar(value="7")
        self.ma_long_var = tk.StringVar(value="25")
        self.rsi_period_var = tk.StringVar(value="14")
        self.rsi_buy_var = tk.StringVar(value="30")
        self.rsi_sell_var = tk.StringVar(value="70")
        self.breakout_window_var = tk.StringVar(value="20")

        tk.Label(strat_frame, text="策略类型").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        tk.OptionMenu(
            strat_frame,
            self.strategy_type_var,
            "threshold",
            "ma_cross",
            "rsi_reversion",
            "breakout",
        ).grid(row=0, column=1, sticky="w", padx=6, pady=4)

        self._add_entry(strat_frame, "K线周期 bar", self.strategy_bar_var, 1)
        self._add_entry(strat_frame, "买入阈值 buy_below", self.buy_below_var, 2)
        self._add_entry(strat_frame, "卖出阈值 sell_above", self.sell_above_var, 3)
        self._add_entry(strat_frame, "均线短期 ma_short_window", self.ma_short_var, 4)
        self._add_entry(strat_frame, "均线长期 ma_long_window", self.ma_long_var, 5)
        self._add_entry(strat_frame, "RSI 周期 rsi_period", self.rsi_period_var, 6)
        self._add_entry(strat_frame, "RSI 买入阈值 rsi_buy", self.rsi_buy_var, 7)
        self._add_entry(strat_frame, "RSI 卖出阈值 rsi_sell", self.rsi_sell_var, 8)
        self._add_entry(strat_frame, "突破周期 breakout_window", self.breakout_window_var, 9)

        self.max_order_var = tk.StringVar(value="20")
        self.max_position_var = tk.StringVar(value="100")
        self.min_order_var = tk.StringVar(value="5")
        self.min_balance_var = tk.StringVar(value="5")
        self.stop_loss_var = tk.StringVar(value="0.05")
        self.take_profit_var = tk.StringVar(value="0.1")
        self.cooldown_var = tk.StringVar(value="30")
        self.max_daily_loss_var = tk.StringVar(value="0.1")
        self.max_drawdown_var = tk.StringVar(value="0.2")
        self.max_trades_var = tk.StringVar(value="20")
        self._add_entry(risk_frame, "单笔上限 max_order_usdt", self.max_order_var, 0)
        self._add_entry(risk_frame, "仓位上限 max_position_usdt", self.max_position_var, 1)
        self._add_entry(risk_frame, "最小下单 min_order_usdt", self.min_order_var, 2)
        self._add_entry(risk_frame, "保留余额 min_balance_usdt", self.min_balance_var, 3)
        self._add_entry(risk_frame, "止损比例 stop_loss_pct", self.stop_loss_var, 4)
        self._add_entry(risk_frame, "止盈比例 take_profit_pct", self.take_profit_var, 5)
        self._add_entry(risk_frame, "冷却时间 cooldown_seconds", self.cooldown_var, 6)
        self._add_entry(risk_frame, "日内最大亏损 max_daily_loss_pct", self.max_daily_loss_var, 7)
        self._add_entry(risk_frame, "最大回撤 max_drawdown_pct", self.max_drawdown_var, 8)
        self._add_entry(risk_frame, "日内最大交易次数 max_trades_per_day", self.max_trades_var, 9)

        self.interval_var = tk.StringVar(value="10")
        self.state_file_var = tk.StringVar(value="okx_state.json")
        self._add_entry(loop_frame, "轮询间隔 interval_seconds", self.interval_var, 0)
        self._add_entry(loop_frame, "状态文件 state_file", self.state_file_var, 1)

        btn_frame = tk.Frame(self)
        btn_frame.grid(row=5, column=0, sticky="ew", padx=10, pady=8)
        btn_frame.columnconfigure(5, weight=1)

        tk.Button(btn_frame, text="加载配置", command=self.load_config).grid(row=0, column=0, padx=4)
        tk.Button(btn_frame, text="保存配置", command=self.save_config).grid(row=0, column=1, padx=4)
        tk.Button(btn_frame, text="单次运行", command=self.run_once).grid(row=0, column=2, padx=4)
        tk.Button(btn_frame, text="开始循环", command=self.start_loop).grid(row=0, column=3, padx=4)
        tk.Button(btn_frame, text="停止循环", command=self.stop_loop).grid(row=0, column=4, padx=4)

        log_frame = tk.LabelFrame(self, text="日志")
        log_frame.grid(row=6, column=0, sticky="nsew", padx=10, pady=8)
        self.rowconfigure(6, weight=1)
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)

        self.log_text = scrolledtext.ScrolledText(log_frame, height=12, state="disabled")
        self.log_text.grid(row=0, column=0, sticky="nsew")

    def _add_entry(self, frame: tk.Misc, label: str, var: tk.StringVar, row: int, show: str | None = None) -> None:
        tk.Label(frame, text=label).grid(row=row, column=0, sticky="w", padx=6, pady=4)
        entry = tk.Entry(frame, textvariable=var, show=show or "")
        entry.grid(row=row, column=1, sticky="ew", padx=6, pady=4)

    def _log(self, msg: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", msg)
        if not msg.endswith("\n"):
            self.log_text.insert("end", "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _poll_log_queue(self) -> None:
        while True:
            try:
                msg = self.log_queue.get_nowait()
            except queue.Empty:
                break
            self._log(msg)
        self.after(200, self._poll_log_queue)

    def _read_float(self, value: str, default: float | None) -> float | None:
        value = value.strip()
        if value == "":
            return default
        return float(value)

    def _read_int(self, value: str, default: int) -> int:
        value = value.strip()
        if value == "":
            return default
        return int(float(value))

    def _build_configs(self) -> tuple[okx_bot.ApiConfig, okx_bot.TradeConfig,
                                      okx_bot.StrategyConfig, okx_bot.RiskConfig, okx_bot.LoopConfig]:
        inst_id = self.inst_id_var.get().strip()
        if not inst_id:
            raise ValueError("inst_id 不能为空")

        api_cfg = okx_bot.ApiConfig(
            api_key=self.api_key_var.get().strip(),
            api_secret=self.api_secret_var.get().strip(),
            passphrase=self.passphrase_var.get().strip(),
            base_url=self.base_url_var.get().strip() or "https://www.okx.com",
        )
        if not api_cfg.api_key or not api_cfg.api_secret or not api_cfg.passphrase:
            raise ValueError("API Key/Secret/Passphrase 不能为空")

        trade_cfg = okx_bot.TradeConfig(
            inst_id=inst_id,
            td_mode=self.td_mode_var.get().strip() or "cash",
            dry_run=bool(self.dry_run_var.get()),
        )

        strat_cfg = okx_bot.StrategyConfig(
            type=self.strategy_type_var.get().strip() or "threshold",
            bar=self.strategy_bar_var.get().strip() or "1m",
            buy_below=self._read_float(self.buy_below_var.get(), None),
            sell_above=self._read_float(self.sell_above_var.get(), None),
            ma_short_window=self._read_int(self.ma_short_var.get(), 7),
            ma_long_window=self._read_int(self.ma_long_var.get(), 25),
            rsi_period=self._read_int(self.rsi_period_var.get(), 14),
            rsi_buy=self._read_float(self.rsi_buy_var.get(), 30.0) or 30.0,
            rsi_sell=self._read_float(self.rsi_sell_var.get(), 70.0) or 70.0,
            breakout_window=self._read_int(self.breakout_window_var.get(), 20),
        )

        risk_cfg = okx_bot.RiskConfig(
            max_order_usdt=self._read_float(self.max_order_var.get(), 20.0) or 20.0,
            max_position_usdt=self._read_float(self.max_position_var.get(), 100.0) or 100.0,
            min_order_usdt=self._read_float(self.min_order_var.get(), 5.0) or 5.0,
            min_balance_usdt=self._read_float(self.min_balance_var.get(), 5.0) or 5.0,
            stop_loss_pct=self._read_float(self.stop_loss_var.get(), None),
            take_profit_pct=self._read_float(self.take_profit_var.get(), None),
            cooldown_seconds=self._read_int(self.cooldown_var.get(), 30),
            max_daily_loss_pct=self._read_float(self.max_daily_loss_var.get(), None),
            max_drawdown_pct=self._read_float(self.max_drawdown_var.get(), None),
            max_trades_per_day=self._read_int(self.max_trades_var.get(), 20),
        )

        loop_cfg = okx_bot.LoopConfig(
            interval_seconds=self._read_int(self.interval_var.get(), 10),
            state_file=self.state_file_var.get().strip() or "okx_state.json",
        )
        return api_cfg, trade_cfg, strat_cfg, risk_cfg, loop_cfg

    def load_config(self) -> None:
        path = filedialog.askopenfilename(
            title="选择配置文件", filetypes=[("JSON", "*.json"), ("All", "*.*")]
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception as exc:
            messagebox.showerror("加载失败", str(exc))
            return

        api = cfg.get("api", {})
        trade = cfg.get("trade", {})
        strategy = cfg.get("strategy", {})
        risk = cfg.get("risk", {})
        loop = cfg.get("loop", {})

        self.api_key_var.set(api.get("api_key", ""))
        self.api_secret_var.set(api.get("api_secret", ""))
        self.passphrase_var.set(api.get("passphrase", ""))
        self.base_url_var.set(api.get("base_url", "https://www.okx.com"))

        self.inst_id_var.set(trade.get("inst_id", "BTC-USDT"))
        self.td_mode_var.set(trade.get("td_mode", "cash"))
        self.dry_run_var.set(bool(trade.get("dry_run", True)))

        self.buy_below_var.set("" if strategy.get("buy_below") is None else str(strategy.get("buy_below")))
        self.sell_above_var.set("" if strategy.get("sell_above") is None else str(strategy.get("sell_above")))
        self.strategy_type_var.set(strategy.get("type", "threshold"))
        self.strategy_bar_var.set(strategy.get("bar", "1m"))
        self.ma_short_var.set(str(strategy.get("ma_short_window", 7)))
        self.ma_long_var.set(str(strategy.get("ma_long_window", 25)))
        self.rsi_period_var.set(str(strategy.get("rsi_period", 14)))
        self.rsi_buy_var.set(str(strategy.get("rsi_buy", 30)))
        self.rsi_sell_var.set(str(strategy.get("rsi_sell", 70)))
        self.breakout_window_var.set(str(strategy.get("breakout_window", 20)))

        self.max_order_var.set(str(risk.get("max_order_usdt", 20)))
        self.max_position_var.set(str(risk.get("max_position_usdt", 100)))
        self.min_order_var.set(str(risk.get("min_order_usdt", 5)))
        self.min_balance_var.set(str(risk.get("min_balance_usdt", 5)))
        self.stop_loss_var.set("" if risk.get("stop_loss_pct") is None else str(risk.get("stop_loss_pct")))
        self.take_profit_var.set("" if risk.get("take_profit_pct") is None else str(risk.get("take_profit_pct")))
        self.cooldown_var.set(str(risk.get("cooldown_seconds", 30)))
        self.max_daily_loss_var.set("" if risk.get("max_daily_loss_pct") is None else str(risk.get("max_daily_loss_pct")))
        self.max_drawdown_var.set("" if risk.get("max_drawdown_pct") is None else str(risk.get("max_drawdown_pct")))
        self.max_trades_var.set(str(risk.get("max_trades_per_day", 20)))

        self.interval_var.set(str(loop.get("interval_seconds", 10)))
        self.state_file_var.set(loop.get("state_file", "okx_state.json"))

        self.current_config_path = path
        self._log(f"已加载配置: {path}")

    def save_config(self) -> None:
        path = filedialog.asksaveasfilename(
            title="保存配置文件",
            defaultextension=".json",
            initialfile=self.current_config_path,
            filetypes=[("JSON", "*.json"), ("All", "*.*")],
        )
        if not path:
            return
        try:
            cfg = self._build_config_dict()
            with open(path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
        except Exception as exc:
            messagebox.showerror("保存失败", str(exc))
            return
        self.current_config_path = path
        self._log(f"已保存配置: {path}")

    def _build_config_dict(self) -> dict:
        cfg = {
            "api": {
                "api_key": self.api_key_var.get().strip(),
                "api_secret": self.api_secret_var.get().strip(),
                "passphrase": self.passphrase_var.get().strip(),
                "base_url": self.base_url_var.get().strip() or "https://www.okx.com",
            },
            "trade": {
                "inst_id": self.inst_id_var.get().strip(),
                "td_mode": self.td_mode_var.get().strip() or "cash",
                "dry_run": bool(self.dry_run_var.get()),
            },
            "strategy": {
                "type": self.strategy_type_var.get().strip() or "threshold",
                "bar": self.strategy_bar_var.get().strip() or "1m",
                "buy_below": self._read_float(self.buy_below_var.get(), None),
                "sell_above": self._read_float(self.sell_above_var.get(), None),
                "ma_short_window": self._read_int(self.ma_short_var.get(), 7),
                "ma_long_window": self._read_int(self.ma_long_var.get(), 25),
                "rsi_period": self._read_int(self.rsi_period_var.get(), 14),
                "rsi_buy": self._read_float(self.rsi_buy_var.get(), 30.0),
                "rsi_sell": self._read_float(self.rsi_sell_var.get(), 70.0),
                "breakout_window": self._read_int(self.breakout_window_var.get(), 20),
            },
            "risk": {
                "max_order_usdt": self._read_float(self.max_order_var.get(), 20.0),
                "max_position_usdt": self._read_float(self.max_position_var.get(), 100.0),
                "min_order_usdt": self._read_float(self.min_order_var.get(), 5.0),
                "min_balance_usdt": self._read_float(self.min_balance_var.get(), 5.0),
                "stop_loss_pct": self._read_float(self.stop_loss_var.get(), None),
                "take_profit_pct": self._read_float(self.take_profit_var.get(), None),
                "cooldown_seconds": self._read_int(self.cooldown_var.get(), 30),
                "max_daily_loss_pct": self._read_float(self.max_daily_loss_var.get(), None),
                "max_drawdown_pct": self._read_float(self.max_drawdown_var.get(), None),
                "max_trades_per_day": self._read_int(self.max_trades_var.get(), 20),
            },
            "loop": {
                "interval_seconds": self._read_int(self.interval_var.get(), 10),
                "state_file": self.state_file_var.get().strip() or "okx_state.json",
            },
        }
        return cfg

    def run_once(self) -> None:
        if self.worker and self.worker.is_alive():
            self._log("已有任务在运行")
            return
        self.stop_event.set()
        self.worker = threading.Thread(target=self._run_once_worker, daemon=True)
        self.worker.start()

    def start_loop(self) -> None:
        if self.worker and self.worker.is_alive():
            self._log("已有任务在运行")
            return
        self.stop_event.clear()
        self.worker = threading.Thread(target=self._loop_worker, daemon=True)
        self.worker.start()
        self._log("开始循环...")

    def stop_loop(self) -> None:
        self.stop_event.set()
        self._log("已请求停止循环")

    def _run_once_worker(self) -> None:
        writer = QueueWriter(self.log_queue)
        with redirect_stdout(writer), redirect_stderr(writer):
            try:
                api_cfg, trade_cfg, strat_cfg, risk_cfg, loop_cfg = self._build_configs()
                client = okx_bot.OKXClient(api_cfg)
                okx_bot.run_once(client, trade_cfg, strat_cfg, risk_cfg, loop_cfg)
            except Exception as exc:
                self.log_queue.put(f"error: {exc}")

    def _loop_worker(self) -> None:
        writer = QueueWriter(self.log_queue)
        with redirect_stdout(writer), redirect_stderr(writer):
            try:
                api_cfg, trade_cfg, strat_cfg, risk_cfg, loop_cfg = self._build_configs()
            except Exception as exc:
                self.log_queue.put(f"error: {exc}")
                return
            client = okx_bot.OKXClient(api_cfg)
            while not self.stop_event.is_set():
                try:
                    okx_bot.run_once(client, trade_cfg, strat_cfg, risk_cfg, loop_cfg)
                except Exception as exc:
                    self.log_queue.put(f"error: {exc}")
                time.sleep(loop_cfg.interval_seconds)
            self.log_queue.put("循环已停止")


if __name__ == "__main__":
    app = OKXTraderUI()
    app.mainloop()
