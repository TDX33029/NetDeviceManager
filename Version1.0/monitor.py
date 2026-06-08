#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
好德云电脑状态监控 - 每2分钟检测一次，异常时发送 ntfy 通知
支持 Windows / Linux (Ubuntu 22.04)
"""
import time
import json
import platform
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options

# ==================== 配置区 ====================
BASE_URL = "https://yun.6ka.cn"
USERNAME = "h431972"
PASSWORD = "dl.431972"
TELEGRAM_TOKEN = "8938811502:AAHSMmrELHYz8OrFmlD8YeaogjmZ7X7-7NE"
TELEGRAM_CHAT_ID = 7775553661
CMD_CHECK_INTERVAL = 10     # 每10秒检查指令
STATUS_CHECK_INTERVAL = 120  # 每2分钟检查云电脑状态
NORMAL_SEND_EVERY = 10       # 连续正常时每10次状态检查发送一次

# 跨平台 Chrome 路径
if platform.system() == "Windows":
    CHROME_PATH = "C:/Program Files/Google/Chrome/Application/chrome.exe"
else:
    CHROME_PATH = None  # Linux 让 Selenium 自动发现
# ===============================================


def send_telegram(message):
    """发送 Telegram 消息"""
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
    """检查是否有新的 Telegram 指令"""
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
            # 只要有 text 就处理，不限制 chat_id（方便调试）
            if text:
                print(f"  [DEBUG] 收到消息: '{text}' chat_id={chat_id} (期望={TELEGRAM_CHAT_ID})", flush=True)
            if chat_id == TELEGRAM_CHAT_ID and text:
                return text
    except Exception as e:
        print(f"  [DEBUG] check_telegram error: {e}", flush=True)
    return None
check_telegram_commands.last_update_id = 0


def create_driver():
    options = Options()
    if CHROME_PATH:
        options.binary_location = CHROME_PATH
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    # 注释掉 headless，让浏览器界面可见
    # options.add_argument("--headless=new")
    driver = webdriver.Chrome(options=options)
    return driver


def fetch_computers(driver, first_run=False):
    """获取云电脑列表（首次需登录）"""
    if first_run:
        driver.get(f"{BASE_URL}/login.php")
        time.sleep(2)
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "username"))).send_keys(USERNAME)
        driver.find_element(By.ID, "password").send_keys(PASSWORD)
        driver.find_element(By.CSS_SELECTOR, "button.btn-login").click()
        time.sleep(5)

    driver.get(f"{BASE_URL}/yundiannao")
    time.sleep(5)

    data = driver.execute_script("""
        var rows = document.querySelectorAll('.table tbody tr');
        var result = [];
        rows.forEach(function(row) {
            var cells = row.querySelectorAll('td');
            if (cells.length >= 8) {
                var instanceId = cells[3]?.textContent?.trim() || '';
                var status = cells[7]?.querySelector('.badge')?.textContent?.trim()
                    || cells[7]?.textContent?.trim() || '';
                if (instanceId && instanceId.startsWith('CCA-')) {
                    result.push({
                        'spec': (cells[1]?.textContent?.trim() || ''),
                        'os': (cells[2]?.textContent?.trim() || ''),
                        'id': instanceId,
                        'expire': (cells[6]?.textContent?.trim() || ''),
                        'status': status
                    });
                }
            }
        });
        return result;
    """)
    return data


def main():
    NORMAL_STATUS = "正常"

    print("=" * 50, flush=True)
    print("  好德云电脑状态监控", flush=True)
    print(f"  指令检查: 每{CMD_CHECK_INTERVAL}秒", flush=True)
    print(f"  状态检查: 每{STATUS_CHECK_INTERVAL}秒", flush=True)
    print(f"  系统: {platform.system()} {platform.release()}", flush=True)
    print("=" * 50, flush=True)

    driver = create_driver()
    last_alert = ""
    normal_count = 0   # 连续正常未发送次数
    last_status_check = 0
    first_run = True

    while True:
        try:
            now_ts = time.time()
            now_str = time.strftime('%Y-%m-%d %H:%M:%S')

            # ===== 每10秒检查 Telegram 指令 =====
            cmd = check_telegram_commands()
            if cmd == "check":
                # 收到 check 指令 -> 立即刷新状态并返回
                computers = fetch_computers(driver, first_run)
                first_run = False
                total = len(computers)
                status_count = {}
                for pc in computers:
                    s = pc.get('status', '未知')
                    status_count[s] = status_count.get(s, 0) + 1
                reply = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 总计: {total}台"
                for k, v in status_count.items():
                    reply += f" | {k}: {v}台"
                send_telegram(reply)

            # ===== 每2分钟检查一次状态 =====
            if now_ts - last_status_check >= STATUS_CHECK_INTERVAL:
                last_status_check = now_ts
                print(f"\n[{now_str}] 检测中...", flush=True)
                computers = fetch_computers(driver, first_run)
                first_run = False

                if not computers:
                    print("  [!] 未获取到数据", flush=True)
                    time.sleep(CMD_CHECK_INTERVAL)
                    continue

                total = len(computers)
                status_count = {}
                abnormal = []
                for pc in computers:
                    s = pc.get('status', '未知')
                    status_count[s] = status_count.get(s, 0) + 1
                    if s != NORMAL_STATUS:
                        abnormal.append(pc)

                # 终端输出
                parts = [f"总计: {total}台"]
                for k, v in status_count.items():
                    parts.append(f"{k}: {v}台")
                print("  " + " | ".join(parts), flush=True)

                status_line = f"[{now_str}] 总计: {total}台"
                for k, v in status_count.items():
                    status_line += f" | {k}: {v}台"

                if abnormal:
                    msg = status_line
                    for pc in abnormal:
                        msg += f"\n  - {pc['id']} | {pc['status']} | 到期: {pc['expire']}"
                    send_telegram(msg)
                    last_alert = json.dumps({pc['id']: pc['status'] for pc in abnormal}, sort_keys=True)
                    normal_count = 0
                else:
                    last_alert = ""
                    normal_count += 1
                    if normal_count >= NORMAL_SEND_EVERY:
                        send_telegram(status_line)
                        normal_count = 0

        except Exception as e:
            print(f"  [!] 检测异常: {e}", flush=True)
            try:
                driver.quit()
            except:
                pass
            time.sleep(10)
            driver = create_driver()

        time.sleep(CMD_CHECK_INTERVAL)


if __name__ == "__main__":
    main()
