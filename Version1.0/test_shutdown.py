#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试关机流程：点击关机 → 确认 → 知道了
"""
import os, time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options

BASE_URL = "https://yun.6ka.cn"
USERNAME = "h431972"
PASSWORD = "dl.431972"
CHROME_PATH = "C:/Program Files/Google/Chrome/Application/chrome.exe"

options = Options()
options.binary_location = CHROME_PATH
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")
options.add_argument("--window-size=1920,1080")
driver = webdriver.Chrome(options=options)

try:
    # 登录
    print("[*] 登录中...")
    driver.get(f"{BASE_URL}/login.php")
    time.sleep(2)
    WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "username"))).send_keys(USERNAME)
    driver.find_element(By.ID, "password").send_keys(PASSWORD)
    driver.find_element(By.CSS_SELECTOR, "button.btn-login").click()
    time.sleep(5)

    # 进入我的云电脑
    print("[*] 进入我的云电脑...")
    driver.get(f"{BASE_URL}/yundiannao")
    time.sleep(5)

    # 找 088fb04b 这台的 card_id
    info = driver.execute_script("""
        var rows = document.querySelectorAll('.table tbody tr');
        for (var i = 0; i < rows.length; i++) {
            var cells = rows[i].querySelectorAll('td');
            if (cells.length >= 8) {
                var cid = cells[4]?.textContent?.trim() || '';
                if (cid.indexOf('088fb04b') !== -1) {
                    var container = rows[i].querySelector('.cloud-more-actions');
                    var meta = container ? container.getAttribute('data-card-meta') : null;
                    var cardId = null;
                    if (meta) {
                        try { cardId = JSON.parse(meta).card_id; } catch(e) {}
                    }
                    if (!cardId) {
                        var stopBtn = rows[i].querySelector('[onclick*="stopCloud"]');
                        if (stopBtn) {
                            var m = stopBtn.getAttribute('onclick').match(/\\d+/);
                            if (m) cardId = parseInt(m[0]);
                        }
                    }
                    return {rowIdx: i, cardId: cardId, cloudId: cid};
                }
            }
        }
        return null;
    """)

    if not info:
        print("[!] 未找到云电脑 088fb04b")
        driver.quit()
        exit()

    print(f"[*] 找到云电脑: card_id={info['cardId']}, cloudId={info['cloudId']}, 行索引={info['rowIdx']}")

    # 点击关机
    print(f"\n[*] 调用 stopCloud({info['cardId']})...")
    driver.execute_script(f"stopCloud({info['cardId']});")
    time.sleep(2)

    # 看页面上有哪些弹窗
    print("\n[*] 检查页面上所有可见弹窗...")
    dialogs = driver.execute_script("""
        var all = document.querySelectorAll('.modal, .modal-dialog, .modal-content, .alert, .confirm, [class*=\"modal\"], [role=\"dialog\"]');
        var result = [];
        all.forEach(function(el) {
            if (el.offsetParent !== null) {
                result.push({
                    id: el.id,
                    class: el.className.substring(0, 80),
                    text: el.textContent.replace(/\\s+/g, ' ').trim().substring(0, 200),
                });
            }
        });
        return JSON.stringify(result, null, 2);
    """)
    print(dialogs)

    # 找所有可见按钮
    print("\n[*] 页面上所有可见按钮:")
    btns = driver.execute_script("""
        var btns = document.querySelectorAll('button');
        var result = [];
        btns.forEach(function(b) {
            if (b.offsetParent !== null) {
                result.push({
                    text: b.textContent.trim().substring(0, 50),
                    id: b.id,
                    class: b.className.substring(0, 40),
                    onclick: (b.getAttribute('onclick') || '').substring(0, 80),
                });
            }
        });
        return JSON.stringify(result, null, 2);
    """)
    print(btns)

    # 手动：先点确认
    print("\n[*] 点击「确认」按钮...")
    try:
        confirm = driver.find_element(By.XPATH, "//button[contains(text(), '确认')]")
        driver.execute_script("arguments[0].click();", confirm)
        time.sleep(1)
        print("[*] 已点击确认")
    except:
        print("[!] 未找到确认按钮")

    # 再点"知道了"
    print("\n[*] 点击「知道了」按钮...")
    try:
        ok_btn = driver.find_element(By.XPATH, "//button[contains(text(), '知道了')]")
        driver.execute_script("arguments[0].click();", ok_btn)
        time.sleep(1)
        print("[*] 已点击知道了")
    except:
        print("[!] 未找到知道了按钮")

    # 看看状态变了没
    status = driver.execute_script(f"""
        var row = document.querySelectorAll('.table tbody tr')[{info['rowIdx']}];
        if (row) {{
            var cells = row.querySelectorAll('td');
            if (cells.length >= 8) {{
                return cells[7]?.querySelector('.badge')?.textContent?.trim()
                    || cells[7]?.textContent?.trim() || '';
            }}
        }}
        return '';
    """)
    print(f"\n[*] 当前状态: {status}")

except Exception as e:
    print(f"[!] 错误: {e}")
    import traceback
    traceback.print_exc()

finally:
    input("\n按回车关闭浏览器...")
    driver.quit()
