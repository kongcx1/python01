import argparse
import base64
import dataclasses
import datetime as dt
import hashlib
import hmac
import json
import os
import time
from typing import Any, Dict, Optional, Tuple

import requests


@dataclasses.dataclass
class ApiConfig:
    api_key: str
    api_secret: str
    passphrase: str
    base_url: str = "https://www.okx.com"


@dataclasses.dataclass
class StrategyConfig:
    type: str = "threshold"
    bar: str = "1m"
    buy_below: Optional[float] = None
    sell_above: Optional[float] = None
    ma_short_window: int = 7
    ma_long_window: int = 25
    rsi_period: int = 14
    rsi_buy: float = 30.0
    rsi_sell: float = 70.0
    breakout_window: int = 20


@dataclasses.dataclass
class RiskConfig:
    max_order_usdt: float = 20.0
    max_position_usdt: float = 100.0
    min_order_usdt: float = 5.0
    min_balance_usdt: float = 5.0
    stop_loss_pct: Optional[float] = None
    take_profit_pct: Optional[float] = None
    cooldown_seconds: int = 30
    max_daily_loss_pct: Optional[float] = None
    max_drawdown_pct: Optional[float] = None
    max_trades_per_day: Optional[int] = None


@dataclasses.dataclass
class LoopConfig:
    interval_seconds: int = 10
    state_file: str = "okx_state.json"


@dataclasses.dataclass
class TradeConfig:
    inst_id: str
    td_mode: str = "cash"
    dry_run: bool = True


class OKXClient:
    def __init__(self, api_cfg: ApiConfig):
        self.api_cfg = api_cfg

    def _timestamp(self) -> str:
        return dt.datetime.utcnow().isoformat(timespec="milliseconds") + "Z"

    def _sign(self, timestamp: str, method: str, path: str, body: str) -> str:
        message = f"{timestamp}{method}{path}{body}"
        mac = hmac.new(
            self.api_cfg.api_secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        )
        return base64.b64encode(mac.digest()).decode("utf-8")

    def _headers(self, timestamp: str, sign: str) -> Dict[str, str]:
        return {
            "OK-ACCESS-KEY": self.api_cfg.api_key,
            "OK-ACCESS-SIGN": sign,
            "OK-ACCESS-TIMESTAMP": timestamp,
            "OK-ACCESS-PASSPHRASE": self.api_cfg.passphrase,
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, params: Optional[Dict[str, Any]] = None,
                 body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = f"{self.api_cfg.base_url}{path}"
        body_str = json.dumps(body) if body else ""
        timestamp = self._timestamp()
        sign = self._sign(timestamp, method, path + ("" if not params else "?" + _query_string(params)), body_str)
        headers = self._headers(timestamp, sign)
        resp = requests.request(method, url, params=params, data=body_str, headers=headers, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def get_ticker(self, inst_id: str) -> float:
        data = self._request("GET", "/api/v5/market/ticker", params={"instId": inst_id})
        last = data["data"][0]["last"]
        return float(last)

    def get_candles(self, inst_id: str, bar: str, limit: int) -> list[float]:
        data = self._request(
            "GET",
            "/api/v5/market/candles",
            params={"instId": inst_id, "bar": bar, "limit": str(limit)},
        )
        candles = data.get("data", [])
        closes = [float(item[4]) for item in candles]
        closes.reverse()
        return closes

    def get_balance(self, ccy: str) -> float:
        data = self._request("GET", "/api/v5/account/balance", params={"ccy": ccy})
        if not data["data"]:
            return 0.0
        details = data["data"][0].get("details", [])
        for item in details:
            if item.get("ccy") == ccy:
                return float(item.get("cashBal", "0"))
        return 0.0

    def place_market_buy(self, inst_id: str, td_mode: str, quote_amount: float) -> Dict[str, Any]:
        body = {
            "instId": inst_id,
            "tdMode": td_mode,
            "side": "buy",
            "ordType": "market",
            "sz": f"{quote_amount:.8f}",
            "tgtCcy": "quote_ccy",
        }
        return self._request("POST", "/api/v5/trade/order", body=body)

    def place_market_sell(self, inst_id: str, td_mode: str, base_amount: float) -> Dict[str, Any]:
        body = {
            "instId": inst_id,
            "tdMode": td_mode,
            "side": "sell",
            "ordType": "market",
            "sz": f"{base_amount:.8f}",
        }
        return self._request("POST", "/api/v5/trade/order", body=body)


def _query_string(params: Dict[str, Any]) -> str:
    return "&".join(f"{k}={params[k]}" for k in sorted(params.keys()))


def _split_inst_id(inst_id: str) -> Tuple[str, str]:
    parts = inst_id.split("-")
    if len(parts) != 2:
        raise ValueError("inst_id must look like BTC-USDT")
    return parts[0], parts[1]


def load_config(path: str) -> Tuple[ApiConfig, TradeConfig, StrategyConfig, RiskConfig, LoopConfig]:
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    api = cfg["api"]
    api_cfg = ApiConfig(
        api_key=api["api_key"],
        api_secret=api["api_secret"],
        passphrase=api["passphrase"],
        base_url=api.get("base_url", "https://www.okx.com"),
    )

    trade_cfg = TradeConfig(
        inst_id=cfg["trade"]["inst_id"],
        td_mode=cfg["trade"].get("td_mode", "cash"),
        dry_run=cfg["trade"].get("dry_run", True),
    )

    strat_cfg = StrategyConfig(**cfg.get("strategy", {}))

    risk_cfg = RiskConfig(**cfg.get("risk", {}))
    loop_cfg = LoopConfig(**cfg.get("loop", {}))
    return api_cfg, trade_cfg, strat_cfg, risk_cfg, loop_cfg


def load_state(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {
            "avg_price": None,
            "last_action_ts": 0,
            "equity_start_day": None,
            "peak_equity": None,
            "day": None,
            "trades_today": 0,
        }
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(path: str, state: Dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def should_cooldown(last_action_ts: float, cooldown_seconds: int) -> bool:
    return time.time() - last_action_ts < cooldown_seconds


def _calc_sma(closes: list[float], window: int) -> Optional[float]:
    if window <= 0 or len(closes) < window:
        return None
    return sum(closes[-window:]) / window


def _calc_rsi(closes: list[float], period: int) -> Optional[float]:
    if period <= 0 or len(closes) < period + 1:
        return None
    gains = 0.0
    losses = 0.0
    for i in range(-period, 0):
        diff = closes[i] - closes[i - 1]
        if diff >= 0:
            gains += diff
        else:
            losses -= diff
    if losses == 0:
        return 100.0
    rs = gains / losses
    return 100 - (100 / (1 + rs))


def _signal_from_strategy(client: OKXClient, inst_id: str, strat_cfg: StrategyConfig) -> Optional[str]:
    if strat_cfg.type == "threshold":
        return None

    if strat_cfg.type == "ma_cross":
        limit = max(strat_cfg.ma_long_window + 2, 30)
        closes = client.get_candles(inst_id, strat_cfg.bar, limit)
        if len(closes) < strat_cfg.ma_long_window + 2:
            return None
        short_prev = _calc_sma(closes[:-1], strat_cfg.ma_short_window)
        long_prev = _calc_sma(closes[:-1], strat_cfg.ma_long_window)
        short_now = _calc_sma(closes, strat_cfg.ma_short_window)
        long_now = _calc_sma(closes, strat_cfg.ma_long_window)
        if None in (short_prev, long_prev, short_now, long_now):
            return None
        if short_prev <= long_prev and short_now > long_now:
            return "buy"
        if short_prev >= long_prev and short_now < long_now:
            return "sell"
        return None

    if strat_cfg.type == "rsi_reversion":
        limit = max(strat_cfg.rsi_period + 2, 30)
        closes = client.get_candles(inst_id, strat_cfg.bar, limit)
        rsi = _calc_rsi(closes, strat_cfg.rsi_period)
        if rsi is None:
            return None
        if rsi <= strat_cfg.rsi_buy:
            return "buy"
        if rsi >= strat_cfg.rsi_sell:
            return "sell"
        return None

    if strat_cfg.type == "breakout":
        limit = max(strat_cfg.breakout_window + 2, 30)
        closes = client.get_candles(inst_id, strat_cfg.bar, limit)
        if len(closes) < strat_cfg.breakout_window + 1:
            return None
        last_close = closes[-1]
        window = closes[-(strat_cfg.breakout_window + 1):-1]
        if last_close > max(window):
            return "buy"
        if last_close < min(window):
            return "sell"
        return None

    return None


def run_once(client: OKXClient, trade_cfg: TradeConfig, strat_cfg: StrategyConfig,
             risk_cfg: RiskConfig, loop_cfg: LoopConfig) -> None:
    base_ccy, quote_ccy = _split_inst_id(trade_cfg.inst_id)
    state = load_state(loop_cfg.state_file)

    last_price = client.get_ticker(trade_cfg.inst_id)
    base_balance = client.get_balance(base_ccy)
    quote_balance = client.get_balance(quote_ccy)

    avg_price = state.get("avg_price")
    if base_balance <= 0:
        avg_price = None
    elif avg_price is None:
        avg_price = last_price

    if should_cooldown(state.get("last_action_ts", 0), risk_cfg.cooldown_seconds):
        print("cooldown active, skip")
        save_state(loop_cfg.state_file, {"avg_price": avg_price, "last_action_ts": state.get("last_action_ts", 0)})
        return

    base_value = base_balance * last_price
    equity = quote_balance + base_value

    today = dt.date.today().isoformat()
    if state.get("day") != today:
        state["day"] = today
        state["equity_start_day"] = equity
        state["peak_equity"] = equity
        state["trades_today"] = 0
    else:
        if state.get("peak_equity") is None or equity > state["peak_equity"]:
            state["peak_equity"] = equity

    if risk_cfg.max_trades_per_day is not None and state.get("trades_today", 0) >= risk_cfg.max_trades_per_day:
        print("risk: max trades per day reached")
        save_state(loop_cfg.state_file, state)
        return

    if risk_cfg.max_daily_loss_pct is not None and state.get("equity_start_day"):
        daily_loss = (state["equity_start_day"] - equity) / state["equity_start_day"]
        if daily_loss >= risk_cfg.max_daily_loss_pct:
            print("risk: max daily loss reached")
            save_state(loop_cfg.state_file, state)
            return

    if risk_cfg.max_drawdown_pct is not None and state.get("peak_equity"):
        drawdown = (state["peak_equity"] - equity) / state["peak_equity"]
        if drawdown >= risk_cfg.max_drawdown_pct:
            print("risk: max drawdown reached")
            save_state(loop_cfg.state_file, state)
            return

    stop_loss_hit = avg_price is not None and risk_cfg.stop_loss_pct is not None and (
        last_price <= avg_price * (1 - risk_cfg.stop_loss_pct)
    )
    take_profit_hit = avg_price is not None and risk_cfg.take_profit_pct is not None and (
        last_price >= avg_price * (1 + risk_cfg.take_profit_pct)
    )
    sell_signal = (
        (strat_cfg.sell_above is not None and last_price >= strat_cfg.sell_above)
        or stop_loss_hit
        or take_profit_hit
    )

    strategy_signal = _signal_from_strategy(client, trade_cfg.inst_id, strat_cfg)
    if strategy_signal == "sell":
        sell_signal = True

    if base_balance > 0 and sell_signal:
        if trade_cfg.dry_run:
            print(f"[DRY_RUN] sell {base_balance:.8f} {base_ccy} at ~{last_price}")
        else:
            client.place_market_sell(trade_cfg.inst_id, trade_cfg.td_mode, base_balance)
            print(f"sold {base_balance:.8f} {base_ccy} at ~{last_price}")
        state["avg_price"] = None
        state["last_action_ts"] = time.time()
        state["trades_today"] = state.get("trades_today", 0) + 1
        save_state(loop_cfg.state_file, state)
        return

    buy_signal = strat_cfg.buy_below is not None and last_price <= strat_cfg.buy_below
    if strategy_signal == "buy":
        buy_signal = True
    if buy_signal:
        remaining_capacity = max(risk_cfg.max_position_usdt - base_value, 0.0)
        spendable = max(quote_balance - risk_cfg.min_balance_usdt, 0.0)
        buy_usdt = min(risk_cfg.max_order_usdt, remaining_capacity, spendable)
        if buy_usdt >= risk_cfg.min_order_usdt:
            if trade_cfg.dry_run:
                print(f"[DRY_RUN] buy {buy_usdt:.2f} {quote_ccy} at ~{last_price}")
            else:
                client.place_market_buy(trade_cfg.inst_id, trade_cfg.td_mode, buy_usdt)
                print(f"bought {buy_usdt:.2f} {quote_ccy} at ~{last_price}")
            est_base = buy_usdt / last_price
            new_base = base_balance + est_base
            if new_base > 0:
                avg_price = (
                    (avg_price or last_price) * base_balance + last_price * est_base
                ) / new_base
            state["avg_price"] = avg_price
            state["last_action_ts"] = time.time()
            state["trades_today"] = state.get("trades_today", 0) + 1
            save_state(loop_cfg.state_file, state)
            return
        print("buy signal but not enough balance/capacity")

    save_state(loop_cfg.state_file, {"avg_price": avg_price, "last_action_ts": state.get("last_action_ts", 0)})


def main() -> None:
    parser = argparse.ArgumentParser(description="OKX spot auto trader")
    parser.add_argument("--config", required=True, help="path to okx_config.json")
    parser.add_argument("--once", action="store_true", help="run one loop then exit")
    args = parser.parse_args()

    api_cfg, trade_cfg, strat_cfg, risk_cfg, loop_cfg = load_config(args.config)
    client = OKXClient(api_cfg)

    while True:
        try:
            run_once(client, trade_cfg, strat_cfg, risk_cfg, loop_cfg)
        except Exception as exc:
            print(f"error: {exc}")
        if args.once:
            break
        time.sleep(loop_cfg.interval_seconds)


if __name__ == "__main__":
    main()
