#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
好德云(6ka.cn) - 抓取我的云电脑列表和状态
支持 Windows / Linux (Ubuntu 22.04)
"""
import time
import json
import platform
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options

BASE_URL = "https://yun.6ka.cn"
USERNAME = "h431972"
PASSWORD = "dl.431972"

if platform.system() == "Windows":
    CHROME_PATH = "C:/Program Files/Google/Chrome/Application/chrome.exe"
else:
    CHROME_PATH = None  # Linux 自动发现


def create_driver(headless=True):
    options = Options()
    if CHROME_PATH:
        options.binary_location = CHROME_PATH
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    if headless:
        options.add_argument("--headless=new")
    driver = webdriver.Chrome(options=options)
    return driver


def login(driver):
    print("[*] 登录中...")
    driver.get(f"{BASE_URL}/login.php")
    time.sleep(2)
    WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "username"))).send_keys(USERNAME)
    driver.find_element(By.ID, "password").send_keys(PASSWORD)
    driver.find_element(By.CSS_SELECTOR, "button.btn-login").click()
    time.sleep(5)
    print(f"[*] 当前URL: {driver.current_url}")


def fetch_computers(driver):
    """抓取我的云电脑列表"""
    print("\n[*] 进入「我的云电脑」页面...")
    driver.get(f"{BASE_URL}/yundiannao")
    time.sleep(5)

    data = driver.execute_script("""
        var rows = document.querySelectorAll('.table tbody tr');
        var result = [];
        rows.forEach(function(row) {
            var cells = row.querySelectorAll('td');
            if (cells.length >= 8) {
                var spec = cells[1]?.textContent?.trim() || '';
                var os = cells[2]?.textContent?.trim() || '';
                var instanceId = cells[3]?.textContent?.trim() || '';
                var cloudId = cells[4]?.textContent?.trim() || '';
                var account = cells[5]?.textContent?.trim() || '';
                var expire = cells[6]?.textContent?.trim() || '';
                var status = cells[7]?.querySelector('.badge')?.textContent?.trim()
                    || cells[7]?.textContent?.trim() || '';
                if (instanceId && instanceId.startsWith('CCA-')) {
                    result.push({
                        '规格': spec,
                        '系统': os,
                        '实例ID': instanceId,
                        '云电脑ID': cloudId,
                        '分配账号': account,
                        '到期时间': expire,
                        '状态': status
                    });
                }
            }
        });
        return result;
    """)

    if data and len(data) > 0:
        print(f"\n[[OK]] 找到 {len(data)} 台云电脑:")
        print("-" * 140)
        header = f"{'#':<3} {'规格':<12} {'系统':<12} {'状态':<8} {'到期时间':<20} {'实例ID'}"
        print(header)
        print("-" * 140)
        for i, pc in enumerate(data, 1):
            spec = pc.get('规格', '')
            os_name = pc.get('系统', '')
            status = pc.get('状态', '')
            expire = pc.get('到期时间', '')
            inst_id = pc.get('实例ID', '')
            print(f"{i:<3} {spec:<12} {os_name:<12} {status:<8} {expire:<20} {inst_id}")
        print("-" * 140)

        # 状态统计
        status_count = {}
        for pc in data:
            s = pc.get('状态', '未知')
            status_count[s] = status_count.get(s, 0) + 1
        print(f"\n[*] 状态统计: {status_count}")

        # 保存JSON
        json_path = os.path.join(os.path.dirname(__file__), "computers.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"[*] 数据已保存到: {json_path}")
    else:
        print("[!] 未获取到数据，保存页面源码分析...")
        html_path = os.path.join(os.path.dirname(__file__), "debug_page.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        print(f"[*] 页面已保存: {html_path}")

    return data


def save_screenshot(driver, name="screenshot"):
    path = os.path.join(os.path.dirname(__file__), f"{name}_{int(time.time())}.png")
    driver.save_screenshot(path)
    print(f"[*] 截图已保存: {path}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="好德云电脑抓取")
    parser.add_argument("--headless", action="store_true", help="无头模式")
    parser.add_argument("--once", action="store_true", help="抓取一次后退出")
    args = parser.parse_args()

    print("[*] 启动浏览器...")
    driver = create_driver(headless=args.headless)
    try:
        login(driver)
        computers = fetch_computers(driver)

        if args.once:
            print("[*] 抓取完成，退出。")
            return

        print("\n[*] 完成! 输入命令: refresh/screen/quit")
        while True:
            try:
                cmd = input(">>> ").strip().lower()
            except (EOFError, OSError):
                break
            if cmd in ("quit", "exit", "q"):
                break
            elif cmd == "screen":
                save_screenshot(driver)
            elif cmd == "refresh":
                computers = fetch_computers(driver)
    except KeyboardInterrupt:
        pass
    finally:
        print("[*] 关闭浏览器")
        driver.quit()


if __name__ == "__main__":
    main()
