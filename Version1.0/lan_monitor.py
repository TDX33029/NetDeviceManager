#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
局域网机器状态监控 - 通过 ping 检测各机器在线状态
从 info.ini 读取 IP 和云电脑 ID 的对应关系
"""
import time
import json
import subprocess
import requests
import os

# ==================== 配置区 ====================
TELEGRAM_TOKEN = "8938811502:AAHSMmrELHYz8OrFmlD8YeaogjmZ7X7-7NE"
TELEGRAM_CHAT_ID = 7775553661

CMD_CHECK_INTERVAL = 10
STATUS_CHECK_INTERVAL = 120
PING_TIMEOUT = 5
NORMAL_SEND_EVERY = 10

INI_PATH = os.path.join(os.path.dirname(__file__), "info.ini")
# ===============================================


def load_machines():
    """从 info.ini 读取机器列表，返回 {名称: IP}"""
    machines = {}
    with open(INI_PATH, "r", encoding="utf-8") as f:
        lines = f.readlines()

    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        parts = {}
        for item in line.split(","):
            if "=" in item:
                k, v = item.split("=", 1)
                parts[k.strip()] = v.strip().rstrip(";")
        ip = parts.get("ip")
        cid = parts.get("id")
        if ip and cid:
            name = f"云电脑{i+1}"
            machines[name] = ip
    return machines


def send_telegram(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
        resp = requests.post(url, json=data, timeout=10)
        if resp.status_code == 200 and resp.json().get('ok'):
            print("  [Telegram] 消息发送成功")
            return True
        else:
            print(f"  [Telegram] 发送失败: {resp.status_code}")
            return False
    except Exception as e:
        print(f"  [Telegram] 异常: {e}")
        return False


def check_telegram_commands():
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
        params = {"offset": check_telegram_commands.last_update_id, "timeout": 0}
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code != 200:
            return None
        data = resp.json()
        if not data.get("ok") or not data.get("result"):
            return None
        for update in data["result"]:
            update_id = update.get("update_id", 0)
            if update_id >= check_telegram_commands.last_update_id:
                check_telegram_commands.last_update_id = update_id + 1
            msg = update.get("message", {})
            text = msg.get("text", "").strip().lower()
            chat_id = msg.get("chat", {}).get("id", 0)
            if text:
                print(f"  [DEBUG] 收到消息: '{text}' chat_id={chat_id}", flush=True)
            if chat_id == TELEGRAM_CHAT_ID and text:
                return text
    except:
        pass
    return None
check_telegram_commands.last_update_id = 0


def ping(host):
    """用 tailscale ping 检测机器是否在线"""
    try:
        result = subprocess.run(
            ["tailscale", "ping", "--c", "1", "--timeout", f"{PING_TIMEOUT}s", host],
            capture_output=True, timeout=PING_TIMEOUT + 3
        )
        output = result.stdout.decode("utf-8", errors="ignore").lower()
        return "pong from" in output
    except:
        return False


def ping_all(machines):
    status = {}
    online_count = 0
    offline = []
    for name, ip in machines.items():
        alive = ping(ip)
        status[name] = alive
        if alive:
            online_count += 1
        else:
            offline.append(name)
        print(f"  {name} ({ip}): {'在线' if alive else '离线'}", flush=True)
    return status, online_count, offline


def build_status_line(now_str, status, online_count, total):
    line = f"[{now_str}] 在线: {online_count}/{total}"
    for name, alive in status.items():
        line += f" | {name}: {'ON' if alive else 'OFF'}"
    return line


def main():
    machines = load_machines()
    total = len(machines)

    print("=" * 50, flush=True)
    print("  局域网机器状态监控", flush=True)
    print(f"  指令检查: 每{CMD_CHECK_INTERVAL}秒", flush=True)
    print(f"  状态检测: 每{STATUS_CHECK_INTERVAL}秒", flush=True)
    for name, ip in machines.items():
        print(f"    {name}: {ip}")
    print("=" * 50, flush=True)

    last_status = {}
    normal_count = 0
    last_status_check = 0

    while True:
        try:
            now_ts = time.time()
            now_str = time.strftime('%Y-%m-%d %H:%M:%S')

            # ===== 每10秒检查 Telegram 指令 =====
            cmd = check_telegram_commands()
            if cmd == "check":
                status, online_count, offline = ping_all(machines)
                reply = build_status_line(
                    time.strftime('%Y-%m-%d %H:%M:%S'),
                    status, online_count, total
                )
                if offline:
                    reply += "\n\n离线机器:"
                    for name in offline:
                        reply += f"\n  - {name} ({machines[name]})"
                send_telegram(reply)

            # ===== 每2分钟检测状态 =====
            if now_ts - last_status_check >= STATUS_CHECK_INTERVAL:
                last_status_check = now_ts
                print(f"\n[{now_str}] 检测中...", flush=True)

                status, online_count, offline = ping_all(machines)

                changed = False
                if last_status:
                    for name in machines:
                        if name in last_status and last_status[name] != status[name]:
                            changed = True
                            break
                last_status = status.copy()

                status_line = build_status_line(now_str, status, online_count, total)

                if offline:
                    msg = status_line
                    msg += "\n\n离线机器:"
                    for name in offline:
                        msg += f"\n  - {name} ({machines[name]})"
                    send_telegram(msg)
                    normal_count = 0
                else:
                    normal_count += 1
                    if normal_count >= NORMAL_SEND_EVERY or changed:
                        send_telegram(status_line)
                        normal_count = 0 if not changed else normal_count

        except Exception as e:
            print(f"  [!] 检测异常: {e}", flush=True)

        time.sleep(CMD_CHECK_INTERVAL)


if __name__ == "__main__":
    main()
