#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BNBMonitor — BTC/USDT real-time price monitor
"""

from __future__ import annotations

import time
import json
import logging
import sys
from configparser import ConfigParser
from datetime import datetime, timezone
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

LOG_FILE = Path(__file__).resolve().parent / "bnb_monitor.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8")],
)
log = logging.getLogger("BNBMonitor")

price_history: list[tuple[float, float]] = []


# --- Config ---
def load_config(config_path: str = None) -> ConfigParser:
    cfg = ConfigParser()
    files = [config_path,
             Path(__file__).resolve().parent / "config.ini",
             Path("config.ini")]
    # 支持命令行传入配置文件路径
    if len(sys.argv) > 1:
        files.insert(0, sys.argv[1])
    for f in files:
        if f and Path(f).exists():
            cfg.read(f, encoding="utf-8")
            log.info(f"Config loaded: {f}")
            break
    else:
        log.error("config.ini not found")
        sys.exit(1)

    for s, k in [("telegram", "bot_token"), ("telegram", "chat_id")]:
        if not cfg.get(s, k, fallback="").strip():
            log.error(f"Missing config: [{s}] {k}")
            sys.exit(1)
    return cfg


# --- HTTP ---
def create_http_session(retries: int = 3) -> requests.Session:
    s = requests.Session()
    retry_strategy = Retry(total=retries, backoff_factor=1,
                           status_forcelist=[429, 500, 502, 503, 504],
                           allowed_methods=["GET"])
    s.mount("https://", HTTPAdapter(max_retries=retry_strategy))
    return s


def fetch_btc_usdt_price(session: requests.Session, base_url: str, timeout: int = 10) -> float | None:
    url = f"{base_url.rstrip('/')}/api/v3/ticker/price"
    try:
        resp = session.get(url, params={"symbol": "BTCUSDT"}, timeout=timeout)
        resp.raise_for_status()
        return float(resp.json()["price"])
    except requests.RequestException as e:
        log.error(f"Fetch price failed: {e}")
    except (KeyError, ValueError, json.JSONDecodeError) as e:
        log.error(f"Parse price failed: {e}")
    return None


# --- Telegram ---
def send_telegram(session: requests.Session, bot_token: str, chat_id: str,
                  message: str, timeout: int = 10) -> bool:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        resp = session.post(url, json={"chat_id": chat_id, "text": message,
                                       "parse_mode": "HTML"}, timeout=timeout)
        resp.raise_for_status()
        if not resp.json().get("ok"):
            log.error(f"Telegram error: {resp.json()}")
            return False
        log.info("TG sent")
        return True
    except requests.RequestException as e:
        log.error(f"TG send failed: {type(e).__name__}")
    except json.JSONDecodeError as e:
        log.error(f"TG parse failed: {e}")
    return False


# --- Price history ---
def _cleanup_history(now: float) -> None:
    cutoff = now - 604800
    while price_history and price_history[0][0] < cutoff:
        price_history.pop(0)


def get_highest_since(since_ts: float) -> float | None:
    best = None
    for ts, p in price_history:
        if ts >= since_ts and (best is None or p > best):
            best = p
    return best


def format_price_alert(price: float, high24h: float) -> str:
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    pct = (price - high24h) / high24h * 100
    sign = "+" if pct >= 0 else ""
    return (
        f"🚀 <b>BTC/USDT 24h High Alert!</b>\n\n"
        f"Price: <b>${price:,.2f}</b>\n"
        f"24h High: <b>${high24h:,.2f}</b>\n"
        f"Change: {sign}{pct:,.6f}%\n\n"
        f"⏰ {now_utc}"
    )


# --- Terminal output ---
WINDOWS = [
    ("15m", 900),
    ("3h", 10800),
    ("12h", 43200),
    ("1d", 86400),
]


def print_line(price: float | None, highs: list[float | None],
               base_price: float, prev_highs: list[float | None],
               breakout_streak: int = 0,
               new_high_flags: list[bool] | None = None) -> None:
    ts = datetime.fromtimestamp(time.time()).strftime("%Y.%m.%d %H:%M:%S")

    def fmt_val(v: float | None) -> str:
        return f"{v:,.2f}" if v is not None else "--"

    def fmt_pct(base: float) -> str:
        if price is not None and base > 0:
            pct = (price - base) / base * 100
            sign = "+" if pct >= 0 else ""
            return f"{sign}{pct:.6f}%"
        return "--"

    if new_high_flags is None:
        new_high_flags = [False] * len(WINDOWS)
    if prev_highs is None:
        prev_highs = [None] * len(WINDOWS)

    parts = [f"[{ts}]-> {fmt_val(price)}"]
    for i, ((label, _), h) in enumerate(zip(WINDOWS, highs)):
        parts.append(f"{label}->{fmt_val(h)}({fmt_pct(h)})")

    # 与启动基准比较
    parts.append(f"start->{fmt_val(base_price)}({fmt_pct(base_price)})")

    # 刷新历史最高（只取第一个触发的窗口，避免重复）
    if any(new_high_flags) and prev_highs is not None:
        for i in range(len(WINDOWS)):
            if new_high_flags[i] and prev_highs[i] is not None and highs[i] is not None and highs[i] > prev_highs[i]:
                pct = (highs[i] - prev_highs[i]) / prev_highs[i] * 100
                parts.append(f"[new:{fmt_val(prev_highs[i])} -> {fmt_val(highs[i])}(+{pct:.4f}%)]")
                break

    if breakout_streak >= 1:
        parts.append(f"[bk:{breakout_streak}]")

    print("    ".join(parts), flush=True)


def print_header() -> None:
    print("BNBMonitor — BTC/USDT")
    labels = "  ".join(f"{label}->high(%chg)" for label, _ in WINDOWS)
    print(f"[time]-> price    {labels}    start->price(%chg)  [new:windows]")


# --- Main loop ---
def main():
    cfg = load_config()

    bot_token = cfg.get("telegram", "bot_token").strip()
    chat_id = cfg.get("telegram", "chat_id").strip()
    upper_threshold = cfg.getfloat("monitor", "upper_threshold", fallback=0)
    lower_threshold = cfg.getfloat("monitor", "lower_threshold", fallback=0)
    check_interval = cfg.getfloat("monitor", "check_interval", fallback=10)
    alert_cooldown = cfg.getint("monitor", "alert_cooldown", fallback=3600)
    base_url = cfg.get("api", "base_url", fallback="https://data-api.binance.vision").strip()
    timeout = cfg.getint("api", "timeout", fallback=10)

    if check_interval < 3:
        check_interval = 3

    BREAKOUT_CONSECUTIVE = 3
    BREAKOUT_RATIO = 1.0001

    last_24h_high = None
    breakout_streak = 0
    last_breakout_alert = 0.0

    log.info(f"Start | upper:{upper_threshold} lower:{lower_threshold} "
             f"interval:{check_interval}s cooldown:{alert_cooldown}s")
    log.info(f"API: {base_url} | breakout: {BREAKOUT_CONSECUTIVE}x above 24h high +{(BREAKOUT_RATIO-1)*100:.2f}%")

    session = create_http_session()

    send_telegram(session, bot_token, chat_id,
                  f"🟢 <b>BNBMonitor started</b>\n\n"
                  f"Pair: BTC/USDT\nInterval: {check_interval}s\n"
                  f"Alert: {BREAKOUT_CONSECUTIVE}x breakout above 24h high",
                  timeout=timeout)

    start_time = time.time()
    check_count = 0
    consecutive_failures = 0
    base_price = None
    prev_highs = None

    print_header()

    try:
        while True:
            price = fetch_btc_usdt_price(session, base_url, timeout=timeout)

            if price is None:
                consecutive_failures += 1
                if consecutive_failures >= 10:
                    send_telegram(session, bot_token, chat_id,
                                  "⚠️ 10 consecutive fetch failures", timeout=timeout)
                    consecutive_failures = 0
                breakout_streak = 0
                time.sleep(check_interval)
                continue

            consecutive_failures = 0
            now = time.time()
            check_count += 1

            price_history.append((now, price))
            _cleanup_history(now)

            if base_price is None:
                base_price = price

            highs = [get_highest_since(now - w) for _, w in WINDOWS]
            high24h = highs[3]

            # 检测刷新历史最高（用旧的 prev_highs 比较，保留一份给 print_line）
            old_highs = prev_highs
            new_high_flags = [False] * len(WINDOWS)
            if old_highs is not None:
                for i in range(len(WINDOWS)):
                    if highs[i] is not None and old_highs[i] is not None:
                        if highs[i] > old_highs[i]:
                            new_high_flags[i] = True
            prev_highs = highs

            # Breakout detection
            if high24h is not None and high24h > 0:
                if price > high24h * BREAKOUT_RATIO:
                    breakout_streak += 1
                else:
                    breakout_streak = 0

                if breakout_streak >= BREAKOUT_CONSECUTIVE:
                    if now - last_breakout_alert >= alert_cooldown:
                        send_telegram(session, bot_token, chat_id,
                                      format_price_alert(price, high24h),
                                      timeout=timeout)
                        last_breakout_alert = now
                    breakout_streak = 0
            else:
                breakout_streak = 0

            print_line(price, highs, base_price, old_highs, breakout_streak, new_high_flags)

            # Fixed threshold alerts
            if upper_threshold > 0 and price > upper_threshold:
                if now - last_breakout_alert >= alert_cooldown:
                    send_telegram(session, bot_token, chat_id,
                                  f"⚠️ Above upper ${upper_threshold:,.2f} | now ${price:,.2f}",
                                  timeout=timeout)
                    last_breakout_alert = now
            if lower_threshold > 0 and price < lower_threshold:
                if now - last_breakout_alert >= alert_cooldown:
                    send_telegram(session, bot_token, chat_id,
                                  f"⚠️ Below lower ${lower_threshold:,.2f} | now ${price:,.2f}",
                                  timeout=timeout)
                    last_breakout_alert = now

            time.sleep(check_interval)

    except KeyboardInterrupt:
        log.info("Stopped by user")
        send_telegram(session, bot_token, chat_id, "🔴 BNBMonitor stopped", timeout=10)
    except Exception:
        log.exception("Unexpected exit")
        send_telegram(session, bot_token, chat_id, "❌ BNBMonitor crashed", timeout=10)
    finally:
        session.close()
        log.info("Exit")


if __name__ == "__main__":
    main()
