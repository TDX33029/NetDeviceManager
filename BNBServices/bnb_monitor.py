#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BNBMonitor — BTC/USDT 汇率实时监测脚本
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


# --- 配置 ---
def load_config(config_path: str = None) -> ConfigParser:
    cfg = ConfigParser()
    files = [config_path,
             Path(__file__).resolve().parent / "config.ini",
             Path("config.ini")]
    for f in files:
        if f and Path(f).exists():
            cfg.read(f, encoding="utf-8")
            log.info(f"已加载配置: {f}")
            break
    else:
        log.error("未找到 config.ini")
        sys.exit(1)

    for s, k in [("telegram", "bot_token"), ("telegram", "chat_id")]:
        if not cfg.get(s, k, fallback="").strip():
            log.error(f"配置缺失: [{s}] {k}")
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
        log.error(f"获取价格失败: {e}")
    except (KeyError, ValueError, json.JSONDecodeError) as e:
        log.error(f"解析价格失败: {e}")
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
            log.error(f"Telegram 返回错误: {resp.json()}")
            return False
        log.info("TG 已发送")
        return True
    except requests.RequestException as e:
        log.error(f"TG 发送失败: {type(e).__name__}")
    except json.JSONDecodeError as e:
        log.error(f"TG 解析失败: {e}")
    return False


# --- 价格历史 ---
def _cleanup_history(now: float, window: float = 86400) -> None:
    cutoff = now - window
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
    pct = (price / high24h - 1) * 100
    return (
        f"🚀 <b>BTC/USDT 接近24h最高价!</b>\n\n"
        f"当前: <b>${price:,.2f}</b>\n"
        f"24h最高: <b>${high24h:,.2f}</b>\n"
        f"距最高: +{pct:.2f}% (>{99.5 - (price/high24h*100):.2f}%)\n\n"
        f"⏰ {now_utc}"
    )


# --- 终端输出 ---
def print_line(price: float | None, high15: float | None, high3h: float | None,
               high24h: float | None, near_high_count: int = 0) -> None:
    ts = datetime.fromtimestamp(time.time()).strftime("%Y.%m.%d %H:%M:%S")

    def fmt_val(v: float | None) -> str:
        return f"{v:,.2f}" if v is not None else "--"

    def fmt_pct(high: float | None) -> str:
        if high is not None and price is not None and high > 0:
            pct = (price - high) / high * 100
            sign = "+" if pct >= 0 else ""
            return f"{sign}{pct:.4f}%"
        return "--"

    extra = f"  [接近:{near_high_count}]" if near_high_count >= 3 else ""
    line = (f"[{ts}]-> {fmt_val(price)}    "
            f"15min->{fmt_val(high15)}({fmt_pct(high15)})  "
            f"3h->{fmt_val(high3h)}({fmt_pct(high3h)})  "
            f"24h->{fmt_val(high24h)}({fmt_pct(high24h)}){extra}")
    print(line, flush=True)


def print_header() -> None:
    print("BNBMonitor — BTC/USDT")


# --- 主循环 ---
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

    # 最小间隔 3s（Binance API 权重限制约 1200/min，3s 完全安全）
    if check_interval < 3:
        check_interval = 3

    # 接近24h最高价触发参数
    NEAR_RATIO = 0.995       # 99.5%
    NEAR_CONSECUTIVE = 5     # 连续 N 次在 99.5% 以上才发通知

    log.info(f"启动监控 | 上限:{upper_threshold} 下限:{lower_threshold} "
             f"间隔:{check_interval}s 冷却:{alert_cooldown}s")
    log.info(f"API: {base_url} | 接近阈值: {NEAR_RATIO*100}%连续{NEAR_CONSECUTIVE}次")

    session = create_http_session()

    send_telegram(session, bot_token, chat_id,
                  f"🟢 <b>BNBMonitor 已启动</b>\n\n"
                  f"币对: BTC/USDT\n间隔: {check_interval}s\n"
                  f"通知条件: 连续{NEAR_CONSECUTIVE}次超过24h最高价的{NEAR_RATIO*100:.1f}%",
                  timeout=timeout)

    start_time = time.time()
    check_count = 0
    consecutive_failures = 0
    last_breakout_alert = 0.0
    near_high_streak = 0   # 连续接近 99.5% 的计数

    print_header()

    try:
        while True:
            price = fetch_btc_usdt_price(session, base_url, timeout=timeout)

            if price is None:
                consecutive_failures += 1
                if consecutive_failures >= 10:
                    send_telegram(session, bot_token, chat_id,
                                  "⚠️ 连续10次获取价格失败", timeout=timeout)
                    consecutive_failures = 0
                near_high_streak = 0
                time.sleep(check_interval)
                continue

            consecutive_failures = 0
            now = time.time()
            check_count += 1

            price_history.append((now, price))
            _cleanup_history(now)

            high15 = get_highest_since(now - 900)
            high3h = get_highest_since(now - 10800)
            high24h = get_highest_since(now - 86400)

            # --- 接近24h最高价检测 ---
            if high24h is not None and high24h > 0:
                if price >= high24h * NEAR_RATIO:
                    near_high_streak += 1
                else:
                    near_high_streak = 0

                # 连续 NEAR_CONSECUTIVE 次在 99.5% 以上 → 发送 TG
                if near_high_streak >= NEAR_CONSECUTIVE:
                    if now - last_breakout_alert >= alert_cooldown:
                        send_telegram(session, bot_token, chat_id,
                                      format_price_alert(price, high24h),
                                      timeout=timeout)
                        last_breakout_alert = now
                    near_high_streak = 0
            else:
                near_high_streak = 0

            # 终端输出
            print_line(price, high15, high3h, high24h, near_high_streak)

            # 固定阈值警报
            if upper_threshold > 0 and price > upper_threshold:
                if now - last_breakout_alert >= alert_cooldown:
                    send_telegram(session, bot_token, chat_id,
                                  f"⚠️ 超过上限 ${upper_threshold:,.2f} | 当前 ${price:,.2f}",
                                  timeout=timeout)
                    last_breakout_alert = now
            if lower_threshold > 0 and price < lower_threshold:
                if now - last_breakout_alert >= alert_cooldown:
                    send_telegram(session, bot_token, chat_id,
                                  f"⚠️ 跌破下限 ${lower_threshold:,.2f} | 当前 ${price:,.2f}",
                                  timeout=timeout)
                    last_breakout_alert = now

            time.sleep(check_interval)

    except KeyboardInterrupt:
        log.info("手动停止")
        send_telegram(session, bot_token, chat_id, "🔴 BNBMonitor 已停止", timeout=10)
    except Exception:
        log.exception("异常退出")
        send_telegram(session, bot_token, chat_id, "❌ BNBMonitor 异常退出", timeout=10)
    finally:
        session.close()
        log.info("退出")


if __name__ == "__main__":
    main()
