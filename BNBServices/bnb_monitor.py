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

# 强制 UTF-8 输出
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

# --- 日志配置（仅文件，终端用 print 管理） ---
LOG_FILE = Path(__file__).resolve().parent / "bnb_monitor.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8")],
)
log = logging.getLogger("BNBMonitor")

# 价格历史
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


def fetch_btc_usdt_price(session: requests.Session, base_url: str, timeout: int = 15) -> float | None:
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
                  message: str, timeout: int = 15) -> bool:
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


def format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    elif seconds < 3600:
        return f"{int(seconds//60)}m{int(seconds%60)}s"
    else:
        return f"{int(seconds//3600)}h{int((seconds%3600)//60)}m"


def format_price_alert(price: float, prev_24h_high: float) -> str:
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    change = price - prev_24h_high
    pct = (change / prev_24h_high * 100) if prev_24h_high > 0 else 0
    return (
        f"🚀 <b>BTC/USDT 突破24小时最高价!</b>\n\n"
        f"当前价格: <b>${price:,.2f}</b>\n"
        f"此前24h最高: <b>${prev_24h_high:,.2f}</b>\n"
        f"涨幅: +${change:,.2f} (+{pct:.2f}%)\n\n"
        f"⏰ {now_utc}"
    )


# --- 终端输出 ---
def print_line(price: float | None, high15: float | None, high3h: float | None,
               high24h: float | None, check_count: int, elapsed: float) -> None:
    """单行输出：时间 | 当前价 | 15min最高 | 3h最高 | 24h最高 | 检查次数"""
    ts = datetime.fromtimestamp(time.time()).strftime("%H:%M:%S")

    def fmt(v):
        return f"${v:>10,.2f}" if v is not None else "       --"

    price_str = f"${price:>10,.2f}" if price is not None else "     获取中"

    print(f"{ts} | 当前 {price_str} | "
          f"15m最高 {fmt(high15)} | 3h最高 {fmt(high3h)} | "
          f"24h最高 {fmt(high24h)} | "
          f"运行 {format_duration(elapsed)} | 第{check_count}次",
          flush=True)


def print_header() -> None:
    print()
    print("  BTC/USDT 实时汇率监测")
    print("  " + "-" * 72)
    print(f"  {'时间':<8} | {'当前价格':>10} | {'15min最高':>10} | "
          f"{'3h最高':>10} | {'24h最高':>10} | {'运行时间':<10} | 检查")
    print("  " + "-" * 72)


# --- 主循环 ---
def main():
    cfg = load_config()

    bot_token = cfg.get("telegram", "bot_token").strip()
    chat_id = cfg.get("telegram", "chat_id").strip()
    upper_threshold = cfg.getfloat("monitor", "upper_threshold", fallback=0)
    lower_threshold = cfg.getfloat("monitor", "lower_threshold", fallback=0)
    check_interval = cfg.getfloat("monitor", "check_interval", fallback=60)
    alert_cooldown = cfg.getint("monitor", "alert_cooldown", fallback=3600)
    base_url = cfg.get("api", "base_url", fallback="https://api.binance.com").strip()
    timeout = cfg.getint("api", "timeout", fallback=15)

    if check_interval < 10:
        check_interval = 10

    log.info(f"启动监控 | 上限:{upper_threshold} 下限:{lower_threshold} "
             f"间隔:{check_interval}s 冷却:{alert_cooldown}s")
    log.info(f"API: {base_url}")

    session = create_http_session()

    # 启动通知
    send_telegram(session, bot_token, chat_id,
                  f"🟢 <b>BNBMonitor 已启动</b>\n\n"
                  f"币对: BTC/USDT\n间隔: {check_interval}s\n"
                  + (f"上限: ${upper_threshold:,.2f}\n" if upper_threshold > 0 else "")
                  + (f"下限: ${lower_threshold:,.2f}\n" if lower_threshold > 0 else ""),
                  timeout=timeout)

    start_time = time.time()
    check_count = 0
    consecutive_failures = 0

    # 追踪 24h 最高价（用于突破通知）
    last_24h_high = None
    last_breakout_alert = 0.0  # 上次突破通知时间

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
                time.sleep(check_interval)
                continue

            consecutive_failures = 0
            now = time.time()
            check_count += 1

            # 更新历史
            price_history.append((now, price))
            _cleanup_history(now)

            # 计算各时段最高
            high15 = get_highest_since(now - 900)
            high3h = get_highest_since(now - 10800)
            high24h = get_highest_since(now - 86400)

            # 终端单行输出
            elapsed = now - start_time
            print_line(price, high15, high3h, high24h, check_count, elapsed)

            # --- 警报逻辑：仅当突破 24h 最高价时发送 TG ---
            if high24h is not None:
                # 追踪启动以来的 24h 最高价变化
                if last_24h_high is None or high24h > last_24h_high:
                    # 24h 最高价被刷新了
                    if last_24h_high is not None:
                        # 不是第一次，确实是"突破"
                        if now - last_breakout_alert >= alert_cooldown:
                            msg = format_price_alert(price, last_24h_high)
                            send_telegram(session, bot_token, chat_id, msg, timeout=timeout)
                            last_breakout_alert = now
                    last_24h_high = high24h

            # 固定阈值警报（保留原有功能）
            if upper_threshold > 0 and price > upper_threshold:
                log.info(f"触发上限警报: ${price:,.2f} > ${upper_threshold:,.2f}")
            if lower_threshold > 0 and price < lower_threshold:
                log.info(f"触发下限警报: ${price:,.2f} < ${lower_threshold:,.2f}")

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
