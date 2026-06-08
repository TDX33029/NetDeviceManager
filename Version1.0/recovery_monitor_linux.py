#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
云电脑自动恢复监控
- 每10秒检查 Telegram 指令
- 每2分钟检测云电脑在线状态（tailscale ping）
- 离线时自动关机→开机重启，最多重试3次
- 多设备并行：依次发关机，一起等待关机完成，一起开机
- 连续正常每30分钟发送一次状态
"""
import time
import json
import subprocess
import requests
import os
import sys

# ==================== 日志 ====================
class Log:
    @staticmethod
    def ts():
        return time.strftime('%Y-%m-%d %H:%M:%S')
    @staticmethod
    def info(msg):
        print(f"[{Log.ts()}] [+]INFO {msg}", flush=True)
    @staticmethod
    def error(msg):
        print(f"[{Log.ts()}] [-]ERROR {msg}", flush=True)
    @staticmethod
    def notice(msg):
        print(f"[{Log.ts()}] [+]NOTICE {msg}", flush=True)
    @staticmethod
    def cmd(msg):
        print(f"[{Log.ts()}] [+]CMD {msg}", flush=True)
# ===============================================

# ==================== 配置区 ====================
TELEGRAM_TOKEN = "8938811502:AAHSMmrELHYz8OrFmlD8YeaogjmZ7X7-7NE"
TELEGRAM_CHAT_ID = 7775553661

CMD_CHECK_INTERVAL = 10
STATUS_CHECK_INTERVAL = 120
PING_TIMEOUT = 5
POWER_CYCLE = True
POST_BOOT_WAIT = 60
NORMAL_SEND_EVERY = 15
SHOW_BROWSER = True    # True=显示浏览器窗口, False=隐藏(无头模式)
PING_RETRY = 3          # ping 失败后重试次数
MAX_RETRY = 3

INI_PATH = os.path.join(os.path.dirname(__file__), "info.ini")
# ===============================================


def send_telegram(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
        resp = requests.post(url, json=data, timeout=10)
        if resp.status_code == 200 and resp.json().get('ok'):
            Log.notice(f"发送Telegram消息: {message[:60]}...")
            return True
        else:
            Log.error(f"发送失败: {resp.status_code}")
            return False
    except Exception as e:
        Log.error(f"发送异常: {e}")
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
            if chat_id == TELEGRAM_CHAT_ID and text:
                return text
    except:
        pass
    return None
check_telegram_commands.last_update_id = 0


def load_machines():
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
        loc = parts.get("loc", "")
        if ip and cid:
            name = f"云电脑{i+1}"
            machines[name] = {"ip": ip, "cloud_id": cid, "loc": loc}
    return machines


def tailscale_ping(host):
    try:
        result = subprocess.run(
            ["tailscale", "ping", "--c", "1", "--timeout", f"{PING_TIMEOUT}s", host],
            capture_output=True, timeout=PING_TIMEOUT + 3
        )
        output = result.stdout.decode("utf-8", errors="ignore").lower()
        return "pong from" in output
    except:
        return False


def retry_ping(host):
    """带重试的 ping，连续失败 PING_RETRY 次才判定离线"""
    for i in range(PING_RETRY):
        if tailscale_ping(host):
            if i > 0:
                Log.info(f"{host} 第{i+1}次重试成功")
            return True
        if i < PING_RETRY - 1:
            Log.info(f"{host} 第{i+1}次ping失败，重试...")
            time.sleep(2)
    return False


def login_and_navigate(driver):
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    BASE_URL = "https://yun.6ka.cn"
    driver.get(f"{BASE_URL}/login.php")
    time.sleep(2)
    WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "username"))).send_keys("h431972")
    driver.find_element(By.ID, "password").send_keys("dl.431972")
    driver.find_element(By.CSS_SELECTOR, "button.btn-login").click()
    time.sleep(5)
    driver.get(f"{BASE_URL}/yundiannao")
    time.sleep(5)


def navigate_to_yundiannao(driver):
    BASE_URL = "https://yun.6ka.cn"
    driver.get(f"{BASE_URL}/yundiannao")
    time.sleep(5)


def get_cloud_info(driver, cloud_id):
    info = driver.execute_script(f"""
        var rows = document.querySelectorAll('.table tbody tr');
        for (var i = 0; i < rows.length; i++) {{
            var cells = rows[i].querySelectorAll('td');
            if (cells.length >= 8) {{
                var cid = cells[4]?.textContent?.trim() || '';
                if (cid === '{cloud_id}') {{
                    var container = rows[i].querySelector('.cloud-more-actions');
                    var meta = container ? container.getAttribute('data-card-meta') : null;
                    var cardId = null;
                    if (meta) {{
                        try {{ cardId = JSON.parse(meta).card_id; }} catch(e) {{}}
                    }}
                    if (!cardId) {{
                        var stopBtn = rows[i].querySelector('[onclick*="stopCloud"]');
                        if (stopBtn) {{
                            var m = stopBtn.getAttribute('onclick').match(/\\d+/);
                            if (m) cardId = parseInt(m[0]);
                        }}
                    }}
                    return {{rowIdx: i, cardId: cardId}};
                }}
            }}
        }}
        return null;
    """)
    if info:
        return info["rowIdx"], info["cardId"]
    return None, None


def send_shutdown(driver, row_idx, card_id, machine_name):
    from selenium.webdriver.common.by import By
    Log.cmd(f"[{machine_name}] 发送关机指令")
    driver.execute_script(f"stopCloud({card_id});")
    time.sleep(2)
    confirm_btn = driver.find_element(By.ID, "uiConfirmOk")
    driver.execute_script("arguments[0].click();", confirm_btn)
    time.sleep(1)
    try:
        ok_btn = driver.find_element(By.XPATH, "//button[contains(text(), '知道了')]")
        driver.execute_script("arguments[0].click();", ok_btn)
        time.sleep(0.5)
    except:
        pass


def send_poweron(driver, row_idx, card_id, machine_name):
    from selenium.webdriver.common.by import By
    Log.cmd(f"[{machine_name}] 发送开机指令")
    driver.execute_script(f"startCloud({card_id});")
    time.sleep(2)
    confirm_btn = driver.find_element(By.ID, "uiConfirmOk")
    driver.execute_script("arguments[0].click();", confirm_btn)
    time.sleep(1)
    try:
        ok_btn = driver.find_element(By.XPATH, "//button[contains(text(), '知道了')]")
        driver.execute_script("arguments[0].click();", ok_btn)
        time.sleep(0.5)
    except:
        pass


def wait_for_status(driver, row_idx, machine_name, target_status, max_wait=60):
    for wait in range(max_wait):
        time.sleep(3)
        status = driver.execute_script(f"""
            var row = document.querySelectorAll('.table tbody tr')[{row_idx}];
            if (row) {{
                var cells = row.querySelectorAll('td');
                if (cells.length >= 8) {{
                    var s = cells[7]?.querySelector('.badge')?.textContent?.trim()
                        || cells[7]?.textContent?.trim() || '';
                    return s;
                }}
            }}
            return '';
        """)
        if status == target_status:
            Log.info(f"[{machine_name}] 状态已变为 {target_status}")
            return status
    return status


def check_status(driver, row_idx):
    return driver.execute_script(f"""
        var row = document.querySelectorAll('.table tbody tr')[{row_idx}];
        if (row) {{
            var cells = row.querySelectorAll('td');
            if (cells.length >= 8) {{
                return cells[7]?.querySelector('.badge')?.textContent?.trim()
                    || cells[7]?.textContent?.trim() || '';
            }}
        }}
        return '';
    """)


def recover_batch(driver, offline_list, machines, total_machines):
    from selenium.webdriver.common.by import By

    send_telegram(f"开始批量恢复 {len(offline_list)} 台: {', '.join(offline_list)}")

    # === 第一步：登录并获取所有离线设备的 card_id ===
    login_and_navigate(driver)
    devices = []
    for name in offline_list:
        info = machines[name]
        row_idx, card_id = get_cloud_info(driver, info["cloud_id"])
        if row_idx is None:
            send_telegram(f"[{name}] 未在控制台找到")
            continue
        devices.append({"name": name, "ip": info["ip"], "row_idx": row_idx, "card_id": card_id})

    if not devices:
        return []

    recovered = []
    remaining = devices[:]

    for attempt in range(1, MAX_RETRY + 1):
        if not remaining:
            break

        Log.cmd(f"恢复批次第 {attempt} 次尝试 ({len(remaining)} 台)")
        send_telegram(f"第{attempt}次尝试恢复 {len(remaining)} 台...")

        # == 依次关机 ==
        navigate_to_yundiannao(driver)
        for dev in remaining:
            send_shutdown(driver, dev["row_idx"], dev["card_id"], dev["name"])

        # == 等待关机完成 ==
        navigate_to_yundiannao(driver)
        send_telegram("等待关机完成...")
        for dev in remaining:
            status = wait_for_status(driver, dev["row_idx"], dev["name"], "已关机", max_wait=60)
            if status != "已关机":
                Log.error(f"[{dev['name']}] 关机异常，当前状态: {status}")

        Log.cmd("等待10秒确保完全关机")
        time.sleep(10)

        # == 依次开机 ==
        navigate_to_yundiannao(driver)
        for dev in remaining:
            send_poweron(driver, dev["row_idx"], dev["card_id"], dev["name"])

        # == 等待开机完成 ==
        navigate_to_yundiannao(driver)
        send_telegram("等待开机完成...")
        boot_failed = []
        for dev in remaining:
            status = wait_for_status(driver, dev["row_idx"], dev["name"], "正常", max_wait=120)
            if status == "正常":
                Log.info(f"[{dev['name']}] 开机成功")
            else:
                Log.error(f"[{dev['name']}] 开机异常，当前状态: {status}")
                boot_failed.append(dev)

        # == ping 验证 ==
        Log.cmd(f"等待{POST_BOOT_WAIT}秒后 ping 验证")
        time.sleep(POST_BOOT_WAIT)

        for dev in remaining:
            if dev in boot_failed:
                continue
            alive = retry_ping(dev["ip"])
            if alive:
                Log.info(f"[{dev['name']}] ping 成功，已恢复")
                send_telegram(f"[{dev['name']}] 恢复成功！")
                recovered.append(dev["name"])
            else:
                Log.error(f"[{dev['name']}] ping 不通，需重试")
                boot_failed.append(dev)

        remaining = boot_failed

    if remaining:
        failed_names = [d["name"] for d in remaining]
        send_telegram(f"以下设备恢复失败（已重试{MAX_RETRY}次）: {', '.join(failed_names)}，需人工检查")

    return recovered



def get_console_status(driver, machines):
    """模式2/3：查询所有云电脑状态。卡死时关闭浏览器等待2分钟重启。"""
    stuck_count = get_console_status.__dict__.get("stuck_count", 0)
    if stuck_count > 0:
        Log.cmd(f"等待恢复中({stuck_count}个周期)...")
        get_console_status.stuck_count -= 1
        return {name: "未知" for name in machines}

    navigate_to_yundiannao(driver)
    result = {}
    status_parts = []
    stuck = False
    for name, info in machines.items():
        row_idx, card_id = get_cloud_info(driver, info["cloud_id"])
        if row_idx is None:
            stuck = True
            break
        status = check_status(driver, row_idx)
        result[name] = status
        status_parts.append(f"{name}:{status}")

    if stuck:
        Log.cmd("页面异常，关闭浏览器2分钟后重试...")
        try:
            driver.quit()
        except:
            pass
        get_console_status.stuck_count = 1  # 等1个周期（2分钟）
        return {name: "未知" for name in machines}
    
    Log.info(f"控制台状态: {' | '.join(status_parts)}")
    return result
get_console_status.stuck_count = 0


def power_on_if_needed(driver, machines, offline_names, ping_results=None):
    """模式2：只查控制台状态，已关机的就开机，ping仅报告不参与决策"""
    navigate_to_yundiannao(driver)
    devices = []
    for name in offline_names:
        info = machines[name]
        row_idx, card_id = get_cloud_info(driver, info["cloud_id"])
        if row_idx is None or not card_id:
            continue
        st = check_status(driver, row_idx)
        if st == "已关机":
            devices.append({"name": name, "row_idx": row_idx, "card_id": card_id})
        else:
            pass
    
    if not devices:
        Log.cmd("没有需要开机的设备")
        return

    names = [d["name"] for d in devices]
    Log.cmd(f"模式2: 对 {len(devices)} 台执行开机: {', '.join(names)}")
    send_telegram(f"执行开机: {', '.join(names)}")
    navigate_to_yundiannao(driver)
    for dev in devices:
        send_poweron(driver, dev["row_idx"], dev["card_id"], dev["name"])
    navigate_to_yundiannao(driver)
    send_telegram("等待开机完成...")
    for dev in devices:
        status = wait_for_status(driver, dev["row_idx"], dev["name"], "正常", max_wait=120)
        if status == "正常":
            Log.info(f"[{dev['name']}] 开机成功")
            send_telegram(f"[{dev['name']}] 已恢复正常")
        else:
            Log.error(f"[{dev['name']}] 开机后状态: {status}")
            send_telegram(f"[{dev['name']}] 开机后状态异常: {status}")


def select_mode():
    """启动时选择工作模式"""
    print()
    Log.info("=" * 40)
    Log.info("请选择工作模式:")
    Log.info("  1 - 严格模式: tailscale ping + 异常关机重启")
    Log.info("  2 - 控制台模式: 查控制台状态, 已关机则开机(无ping)")
    Log.info("  3 - 混合模式: 查控制台状态 + ping仅报告, 已关机则开机")
    Log.info("=" * 40)
    try:
        mode = input("  [选择] 输入 1/2/3: ").strip()
    except:
        mode = "1"
    return mode if mode in ("2", "3") else "1"


def main():
    machines = load_machines()
    total = len(machines)
    mode = select_mode()
    if mode == "1":
        mode_label = "严格模式(ping)"
    elif mode in ("2", "3"):
        mode_label = "控制台模式(仅状态)"
    else:
        mode_label = "混合模式(状态+ping报告)"

    print()
    Log.info(f"云电脑自动恢复监控启动 | 模式: {mode_label} | 检查指令每{CMD_CHECK_INTERVAL}s | 检测状态每{STATUS_CHECK_INTERVAL}s | 正常推送每{NORMAL_SEND_EVERY}次")
    for name, info in machines.items():
        loc_tag = info.get("loc", "")
        loc_str = f" [{loc_tag}]" if loc_tag else ""
        Log.info(f"  {name}: {info['ip']}{loc_str} ({info['cloud_id'][:16]}...)")
    print()

    # 模式2：一次性打开浏览器，后续只刷新
    mode2_driver = None
    if mode in ("2", "3"):
        Log.cmd("模式2: 启动浏览器(常驻)")
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        import subprocess as sp
        try:
            sp.run("pkill -f chromedriver 2>/dev/null", shell=True)
            time.sleep(1)
        except:
            pass
        CHROME_PATH = "/usr/bin/google-chrome"
        opts = Options()
        opts.binary_location = CHROME_PATH
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-gpu")
        if not SHOW_BROWSER:
            opts.add_argument("--headless=new")
        opts.add_argument("--window-size=1920,1080")
        for d_attempt in range(3):
            try:
                mode2_driver = webdriver.Chrome(options=opts)
                break
            except Exception as e:
                Log.error(f"浏览器启动失败(第{d_attempt+1}次): {e}")
                time.sleep(3)
        if mode2_driver:
            Log.cmd("模式2: 浏览器已就绪")
            # 先登录一次
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
            BASE_URL = "https://yun.6ka.cn"
            mode2_driver.get(f"{BASE_URL}/login.php")
            time.sleep(2)
            WebDriverWait(mode2_driver, 10).until(EC.presence_of_element_located((By.ID, "username"))).send_keys("h431972")
            mode2_driver.find_element(By.ID, "password").send_keys("dl.431972")
            mode2_driver.find_element(By.CSS_SELECTOR, "button.btn-login").click()
            time.sleep(5)
        else:
            Log.error("模式2: 浏览器启动失败，回退到模式1")
            mode = "1"

    last_status = {}
    normal_count = 0
    last_status_check = 0

    while True:
        try:
            now_ts = time.time()
            now_str = time.strftime('%Y-%m-%d %H:%M:%S')

            # ===== 检查指令 =====
            cmd = check_telegram_commands()
            if cmd == "check":
                parts = [f"[{time.strftime('%Y-%m-%d %H:%M:%S')}]"]
                online_count = 0
                for name, info in machines.items():
                    if mode == "1":
                        alive = retry_ping(info["ip"])
                    else:
                        alive = True  # 模式2下check不启浏览器
                    parts.append(f"{name}: {'ON' if alive else 'OFF'}")
                    if alive:
                        online_count += 1
                parts.insert(1, f"{online_count}/{total}")
                if mode in ("2", "3"):
                    parts.append("(查状态需等周期检测)")
                send_telegram(" | ".join(parts))
                last_status_check = now_ts

            # ===== 每2分钟检测状态 =====
            if now_ts - last_status_check >= STATUS_CHECK_INTERVAL:
                last_status_check = now_ts

                # 模式2/3：检查浏览器是否还活着
                if mode in ("2", "3") and (getattr(get_console_status, "stuck_count", 0) > 0 or mode2_driver is None):
                    # 浏览器已关闭正在等待，开一个全新的
                    Log.cmd("正在重启浏览器...")
                    from selenium import webdriver
                    from selenium.webdriver.chrome.options import Options
                    import subprocess as sp
                    try:
                        sp.run("pkill -f chromedriver 2>/dev/null", shell=True)
                        time.sleep(1)
                    except:
                        pass
                    CHROME_PATH = "/usr/bin/google-chrome"
                    opts = Options()
                    opts.binary_location = CHROME_PATH
                    opts.add_argument("--no-sandbox")
                    opts.add_argument("--disable-dev-shm-usage")
                    opts.add_argument("--disable-gpu")
                    if not SHOW_BROWSER:
                        opts.add_argument("--headless=new")
                    opts.add_argument("--window-size=1920,1080")
                    for d_attempt in range(3):
                        try:
                            new_driver = webdriver.Chrome(options=opts)
                            mode2_driver = new_driver
                            break
                        except Exception as e:
                            Log.error(f"浏览器重启失败(第{d_attempt+1}次): {e}")
                            time.sleep(3)
                    if mode2_driver:
                        from selenium.webdriver.common.by import By
                        from selenium.webdriver.support.ui import WebDriverWait
                        from selenium.webdriver.support import expected_conditions as EC
                        BASE_URL = "https://yun.6ka.cn"
                        mode2_driver.get(f"{BASE_URL}/login.php")
                        time.sleep(2)
                        WebDriverWait(mode2_driver, 10).until(EC.presence_of_element_located((By.ID, "username"))).send_keys("h431972")
                        mode2_driver.find_element(By.ID, "password").send_keys("dl.431972")
                        mode2_driver.find_element(By.CSS_SELECTOR, "button.btn-login").click()
                        time.sleep(5)
                    Log.cmd("浏览器已重启")
                    
                status = {}
                offline_list = []
                status_strs = []

                if mode == "1":
                    for name, info in machines.items():
                        alive = retry_ping(info["ip"])
                        status[name] = alive
                        mark = "ON" if alive else "OFF"
                        status_strs.append(f"{name}:{mark}")
                        if not alive:
                            offline_list.append(name)
                elif mode == "2":
                    # 模式2：仅控制台状态，无ping
                    navigate_to_yundiannao(mode2_driver)
                    console_status = get_console_status(mode2_driver, machines)
                    for name, info in machines.items():
                        st = console_status.get(name, "未知")
                        status[name] = True if st == "正常" else False
                        mark = "ON" if status[name] else f"OFF({st})"
                        status_strs.append(f"{name}:{mark}")
                        if st == "已关机":
                            offline_list.append(name)
                else:
                    # 模式3：控制台状态 + ping仅报告
                    navigate_to_yundiannao(mode2_driver)
                    console_status = get_console_status(mode2_driver, machines)
                    ping_results = {}
                    Log.cmd("模式3: ping 检测(仅报告)")
                    for name, info in machines.items():
                        ping_alive = retry_ping(info["ip"])
                        ping_results[name] = ping_alive
                    for name, info in machines.items():
                        st = console_status.get(name, "未知")
                        status[name] = True if st == "正常" else False
                        ping_ok = ping_results.get(name, False)
                        mark = "ON" if status[name] else f"OFF({st})"
                        status_strs.append(f"{name}:{mark}")
                        if st == "已关机":
                            offline_list.append(name)
                        if not ping_ok and status[name]:
                            Log.info(f"[{name}] 控制台正常但ping不通(仅报告)")

                result = " | ".join(status_strs)
                if offline_list:
                    Log.info(f"检测结果: {result} | 异常: {','.join(offline_list)}")
                else:
                    Log.info(f"检测结果: {result}")

                changed = False
                if last_status:
                    for name in machines:
                        if name in last_status and last_status[name] != status[name]:
                            changed = True
                            break
                last_status = status.copy()

                online_count = sum(1 for v in status.values() if v)
                status_line = f"[{now_str}] 在线: {online_count}/{total}"
                for name, alive in status.items():
                    info = machines[name]
                    loc_tag = info.get("loc", "")
                    status_line += f" | {name}: {'ON' if alive else 'OFF'}"
                    if loc_tag:
                        status_line += f"({loc_tag})"

                if offline_list:
                    msg = status_line + "\n\n" + ("离线设备:" if mode == "1" else "异常设备:")
                    for name in offline_list:
                        msg += f"\n  - {name} ({machines[name]['ip']})"
                    send_telegram(msg)
                    normal_count = 0

                    if POWER_CYCLE:
                        Log.cmd(f"检测到异常设备: {offline_list}，启动恢复")
                        if mode == "2":
                            power_on_if_needed(mode2_driver, machines, offline_list)
                        elif mode == "3":
                            power_on_if_needed(mode2_driver, machines, offline_list, ping_results)
                        else:
                            # 模式1：新开浏览器执行关机重启
                            from selenium import webdriver
                            from selenium.webdriver.chrome.options import Options
                            import subprocess as sp
                            try:
                                sp.run("pkill -f chromedriver 2>/dev/null", shell=True)
                                time.sleep(1)
                            except:
                                pass
                            CHROME_PATH = "/usr/bin/google-chrome"
                            opts = Options()
                            opts.binary_location = CHROME_PATH
                            opts.add_argument("--no-sandbox")
                            opts.add_argument("--disable-dev-shm-usage")
                            opts.add_argument("--disable-gpu")
                            opts.add_argument("--window-size=1920,1080")
                            Log.cmd("启动浏览器")
                            temp_driver = None
                            for d_attempt in range(3):
                                try:
                                    temp_driver = webdriver.Chrome(options=opts)
                                    break
                                except Exception as e:
                                    Log.error(f"浏览器启动失败(第{d_attempt+1}次): {e}")
                                    time.sleep(3)
                                    try:
                                        sp.run("pkill -f chromedriver 2>/dev/null", shell=True)
                                        time.sleep(1)
                                    except:
                                        pass
                            if temp_driver:
                                try:
                                    recovered = recover_batch(temp_driver, offline_list, machines, total)
                                    if recovered:
                                        send_telegram(f"恢复完成: {', '.join(recovered)}")
                                finally:
                                    Log.cmd("关闭浏览器")
                                    try:
                                        temp_driver.quit()
                                    except:
                                        pass
                            else:
                                send_telegram("无法启动浏览器，恢复流程中断")
                else:
                    normal_count += 1
                    if normal_count >= NORMAL_SEND_EVERY or changed:
                        send_telegram(status_line)
                        normal_count = 0

        except Exception as e:
            Log.error(f"主循环异常: {e}")
            # 模式2/3：关闭浏览器，下一周期自动重启
            if mode in ("2", "3"):
                Log.cmd("异常发生，关闭浏览器等待恢复...")
                try:
                    mode2_driver.quit()
                except:
                    pass
                mode2_driver = None
                get_console_status.stuck_count = 1

        time.sleep(CMD_CHECK_INTERVAL)

    # 循环结束后清理
    if mode2_driver:
        try:
            mode2_driver.quit()
        except:
            pass


if __name__ == "__main__":
    main()
