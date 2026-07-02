#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BNBMonitor — BTC/USDT 汇率实时监测脚本

通过 Binance API 实时获取 BTC/USDT 汇率，当价格超过/低于设定阈值时，
通过 Telegram Bot API 发送通知消息。

使用方法:
    1. 复制 config.example.ini 为 config.ini
    2. 填写 Telegram Bot Token 和 Chat ID
    3. 设置监测阈值
    4. 运行: python bnb_monitor.py
    5. (可选) 后台运行: nohup python bnb_monitor.py > monitor.log 2>&1 &
"""
from __future__ import annotations

import time
import json
import logging
import sys
from configparser import ConfigParser
from datetime import datetime, timezone
from pathlib import Path

# --- 强制 UTF-8 输出（解决 Windows 终端中文/Unicode 乱码） ---
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry


# --- 日志配置 ---
LOG_FILE = Path(__file__).resolve().parent / "bnb_monitor.log"
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("BNBMonitor")

# --- 价格历史（用于多时段最高价追踪） ---
# 每个元素为 (timestamp, price)，按时间递增排列
price_history: list[tuple[float, float]] = []


# --- 配置加载 ---
def load_config(config_path: str = None) -> ConfigParser:
    """加载并验证配置文件。"""
    cfg = ConfigParser()
    files_to_try = [
        config_path,
        Path(__file__).resolve().parent / "config.ini",
        Path("config.ini"),
    ]
    loaded = False
    for f in files_to_try:
        if f and Path(f).exists():
            cfg.read(f, encoding="utf-8")
            loaded = True
            log.info(f"已加载配置文件: {f}")
            break

    if not loaded:
        log.error("未找到 config.ini，请从 config.example.ini 复制并填写配置")
        sys.exit(1)

    # 验证必要字段
    for section, key in [("telegram", "bot_token"), ("telegram", "chat_id")]:
        if not cfg.get(section, key, fallback="").strip():
            log.error(f"配置缺失: [{section}] {key}，请填写后重试")
            sys.exit(1)

    if cfg.get("telegram", "bot_token") == "YOUR_BOT_TOKEN_HERE":
        log.error("请先填写 config.ini 中的 Telegram Bot Token 和 Chat ID")
        sys.exit(1)

    return cfg


# --- 汇率获取 ---
def create_http_session(retries: int = 3) -> requests.Session:
    """创建带重试机制的 HTTP 会话。"""
    s = requests.Session()
    retry_strategy = Retry(
        total=retries,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    s.mount("https://", adapter)
    return s


def fetch_btc_usdt_price(session: requests.Session, base_url: str, timeout: int = 15) -> float | None:
    """从 Binance API 获取 BTC/USDT 的最新成交价。

    返回:
        float: 当前价格，失败时返回 None
    """
    url = f"{base_url.rstrip('/')}/api/v3/ticker/price"
    params = {"symbol": "BTCUSDT"}
    try:
        resp = session.get(url, params=params, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        price = float(data["price"])
        log.debug(f"当前 BTC/USDT 价格: ${price:,.2f}")
        return price
    except requests.RequestException as e:
        log.error(f"获取价格失败（网络错误）: {e}")
    except (KeyError, ValueError, json.JSONDecodeError) as e:
        log.error(f"解析价格数据失败: {e}")
    return None


# --- Telegram 通知 ---
def send_telegram_alert(
    session: requests.Session,
    bot_token: str,
    chat_id: str,
    message: str,
    timeout: int = 15,
) -> bool:
    """通过 Telegram Bot API 发送消息。

    返回:
        bool: 发送成功返回 True，否则 False
    """
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
    }
    try:
        resp = session.post(url, json=payload, timeout=timeout)
        resp.raise_for_status()
        result = resp.json()
        if not result.get("ok"):
            log.error(f"Telegram API 返回错误: {result}")
            return False
        log.info("Telegram 通知已发送")
        return True
    except requests.RequestException as e:
        # 避免完整 URL（含 token）泄露到日志
        log.error(f"发送 Telegram 消息失败（网络错误）: {type(e).__name__}")
    except json.JSONDecodeError as e:
        log.error(f"解析 Telegram 响应失败: {e}")
    return False


def format_price_message(
    price: float,
    threshold: float,
    direction: str,
    upper_threshold: float = 0,
    lower_threshold: float = 0,
) -> str:
    """格式化要发送的价格警报消息（HTML 格式）。"""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    emoji = "🚀" if direction == "above" else "📉"
    threshold_label = "上限" if direction == "above" else "下限"

    # 构建阈值信息
    threshold_lines = ""
    if upper_threshold > 0:
        threshold_lines += f"  价格上限: <b>${upper_threshold:,.2f}</b>\n"
    if lower_threshold > 0:
        threshold_lines += f"  价格下限: <b>${lower_threshold:,.2f}</b>\n"

    return (
        f"{emoji} <b>BTC/USDT 价格警报</b> {emoji}\n\n"
        f"当前价格: <b>${price:,.2f}</b>\n"
        f"触发条件: 超过{threshold_label} ${threshold:,.2f}\n\n"
        f"阈值设置:\n"
        f"{threshold_lines}"
        f"\n⏰ 时间: {now}"
    )


# --- 终端状态面板 ---
def _cleanup_history(now: float, window: float = 86400) -> None:
    """清理超过窗口的历史记录（默认24小时）。"""
    cutoff = now - window
    while price_history and price_history[0][0] < cutoff:
        price_history.pop(0)


def get_highest_since(since_ts: float) -> float | None:
    """返回自指定时间戳以来的最高价格。

    参数:
        since_ts: 起始时间戳

    返回:
        float | None: 最高价，若无数据返回 None
    """
    if not price_history:
        return None
    highest = None
    for ts, price in price_history:
        if ts >= since_ts:
            if highest is None or price > highest:
                highest = price
    return highest


def format_duration(seconds: float) -> str:
    """格式化时长显示。"""
    if seconds < 60:
        return f"{seconds:.0f}s"
    elif seconds < 3600:
        m = int(seconds // 60)
        s = int(seconds % 60)
        return f"{m}m {s}s"
    else:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        return f"{h}h {m}m"


def print_status(
    price: float | None,
    upper_threshold: float,
    lower_threshold: float,
    start_time: float,
    check_count: int,
    consecutive_failures: int = 0,
) -> None:
    """在终端打印状态面板。

    每次循环调用，显示当前价格、阈值、多时段最高价和运行统计。
    """
    now = time.time()
    elapsed = now - start_time

    # 清屏（兼容大部分终端）
    print("\033[2J\033[H", end="")

    # 标题栏
    print("╔══════════════════════════════════════════════╗")
    print("║        BTC/USDT 实时汇率监测                  ║")
    print("╠══════════════════════════════════════════════╣")

    # 当前价格
    if price is not None:
        print(f"║  当前价格: ${price:>12,.2f}                    ║")
    else:
        print(f"║  当前价格:       获取中...                    ║")

    # 阈值
    up_str = f"${upper_threshold:,.2f}" if upper_threshold > 0 else "未设置"
    low_str = f"${lower_threshold:,.2f}" if lower_threshold > 0 else "未设置"
    print(f"║  价格上限: {up_str:<14}  下限: {low_str:<14} ║")

    print("╠══════════════════════════════════════════════╣")

    # 多时段最高价（滚动窗口：过去15分钟/3小时/24小时）
    now_ts = time.time()
    windows = [
        ("15min", 900),
        ("  3h", 10800),
        (" 24h", 86400),
    ]
    for label, window in windows:
        since_ts = now_ts - window
        highest = get_highest_since(since_ts)
        if highest is not None:
            print(f"║  最高价格 ({label}): ${highest:>12,.2f}                ║")
        else:
            print(f"║  最高价格 ({label}): 数据收集中...              ║")

    print("╠══════════════════════════════════════════════╣")

    # 运行统计
    run_time = format_duration(elapsed)
    print(f"║  运行时间: {run_time:<20} 检查: {check_count:<6}     ║")

    # 上一次检查时刻
    now_str = datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:%M:%S")
    print(f"║  上次检查: {now_str:<28} ║")

    if consecutive_failures > 0:
        print(f"║  ⚠ 连续失败: {consecutive_failures} 次                          ║")

    print("╚══════════════════════════════════════════════╝")
    sys.stdout.flush()


# --- 主循环 ---
def main():
    log.info("=" * 50)
    log.info("BNBMonitor — BTC/USDT 汇率监测启动")
    log.info("=" * 50)

    cfg = load_config()

    # 读取配置
    bot_token = cfg.get("telegram", "bot_token").strip()
    chat_id = cfg.get("telegram", "chat_id").strip()
    upper_threshold = cfg.getfloat("monitor", "upper_threshold", fallback=0)
    lower_threshold = cfg.getfloat("monitor", "lower_threshold", fallback=0)
    check_interval = cfg.getfloat("monitor", "check_interval", fallback=60)
    alert_cooldown = cfg.getint("monitor", "alert_cooldown", fallback=3600)
    base_url = cfg.get("api", "base_url", fallback="https://api.binance.com").strip()
    timeout = cfg.getint("api", "timeout", fallback=15)

    # 安全检查间隔
    if check_interval < 10:
        log.warning(f"检查间隔 {check_interval}s 过小，已调整为 10s")
        check_interval = 10

    log.info(f"价格上限: ${upper_threshold:,.2f}" if upper_threshold > 0 else "价格上限: 未设置")
    log.info(f"价格下限: ${lower_threshold:,.2f}" if lower_threshold > 0 else "价格下限: 未设置")
    log.info(f"检查间隔: {check_interval}s | 警报冷却: {alert_cooldown}s")
    log.info(f"TG Chat ID: {chat_id}")

    if upper_threshold <= 0 and lower_threshold <= 0:
        log.error("至少需要设置一个阈值（upper_threshold 或 lower_threshold）")
        sys.exit(1)

    # 创建 HTTP 会话（复用连接）
    session = create_http_session()

    # 冷却追踪: 记录每个方向上次发送警报的时间戳
    last_alert_time = {"above": 0.0, "below": 0.0}

    # 启动通知
    startup_msg = (
        f"🟢 <b>BNBMonitor 已启动</b>\n\n"
        f"监测币对: <b>BTC/USDT</b>\n"
        f"检查间隔: {check_interval}s\n"
        + (f"价格上限: ${upper_threshold:,.2f}\n" if upper_threshold > 0 else "")
        + (f"价格下限: ${lower_threshold:,.2f}\n" if lower_threshold > 0 else "")
    )
    send_telegram_alert(session, bot_token, chat_id, startup_msg, timeout=timeout)

    # 追踪变量
    start_time = time.time()
    check_count = 0
    consecutive_failures = 0
    max_failures = 10

    try:
        while True:
            price = fetch_btc_usdt_price(session, base_url, timeout=timeout)

            if price is None:
                consecutive_failures += 1
                log.warning(f"获取价格失败 ({consecutive_failures}/{max_failures})")
                if consecutive_failures >= max_failures:
                    send_telegram_alert(
                        session,
                        bot_token,
                        chat_id,
                        "⚠️ <b>BNBMonitor 警告</b>\n\n连续 10 次获取价格失败，请检查网络或 Binance API 状态。",
                        timeout=timeout,
                    )
                    consecutive_failures = 0
                print_status(None, upper_threshold, lower_threshold, start_time, check_count, consecutive_failures)
                time.sleep(check_interval)
                continue

            consecutive_failures = 0  # 成功后重置
            now = time.time()
            check_count += 1

            # 更新价格历史
            price_history.append((now, price))
            _cleanup_history(now)

            # 终端状态显示
            print_status(price, upper_threshold, lower_threshold, start_time, check_count)

            # 检查上限
            if upper_threshold > 0 and price > upper_threshold:
                if now - last_alert_time["above"] >= alert_cooldown:
                    msg = format_price_message(
                        price, upper_threshold, "above", upper_threshold, lower_threshold
                    )
                    send_telegram_alert(session, bot_token, chat_id, msg, timeout=timeout)
                    last_alert_time["above"] = now
                else:
                    remaining = alert_cooldown - (now - last_alert_time["above"])
                    log.debug(f"上限警报冷却中，{remaining:.0f}s 后可再次发送")

            # 检查下限
            if lower_threshold > 0 and price < lower_threshold:
                if now - last_alert_time["below"] >= alert_cooldown:
                    msg = format_price_message(
                        price, lower_threshold, "below", upper_threshold, lower_threshold
                    )
                    send_telegram_alert(session, bot_token, chat_id, msg, timeout=timeout)
                    last_alert_time["below"] = now
                else:
                    remaining = alert_cooldown - (now - last_alert_time["below"])
                    log.debug(f"下限警报冷却中，{remaining:.0f}s 后可再次发送")

            time.sleep(check_interval)

    except KeyboardInterrupt:
        log.info("收到中断信号，正在退出…")
        send_telegram_alert(
            session,
            bot_token,
            chat_id,
            "🔴 <b>BNBMonitor 已停止</b>\n\n监测程序已手动停止。",
            timeout=10,
        )
    except Exception:
        log.exception("未预期的异常")
        send_telegram_alert(
            session,
            bot_token,
            chat_id,
            "❌ <b>BNBMonitor 异常退出</b>\n\n请检查日志文件获取详细信息。",
            timeout=10,
        )
    finally:
        session.close()
        log.info("BNBMonitor 已退出")


if __name__ == "__main__":
    main()
