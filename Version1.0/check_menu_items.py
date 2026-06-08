#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
深入检查：点击"更多"后，全页面搜索所有可见按钮
"""
import os, time, json
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
    driver.get(f"{BASE_URL}/login.php")
    time.sleep(2)
    WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "username"))).send_keys(USERNAME)
    driver.find_element(By.ID, "password").send_keys(PASSWORD)
    driver.find_element(By.CSS_SELECTOR, "button.btn-login").click()
    time.sleep(5)

    driver.get(f"{BASE_URL}/yundiannao")
    time.sleep(5)

    # 1. 先看操作列原始HTML（不看样式）
    print("="*60)
    print("[1] 操作列完整 HTML（第一行）:")
    print("="*60)
    html = driver.execute_script("""
        var cell = document.querySelector('td.action-cell, td:last-child');
        if (!cell) {
            cell = document.querySelector('.table tbody tr td:last-of-type');
        }
        return cell ? cell.innerHTML : 'not found';
    """)
    print(html[:3000])

    # 2. 获取所有按钮（包括display:none的）
    print("\n" + "="*60)
    print("[2] 该行所有 button/a 元素（含隐藏）:")
    print("="*60)
    btns = driver.execute_script("""
        var row = document.querySelector('.table tbody tr');
        var all = row.querySelectorAll('button, a');
        var result = [];
        all.forEach(function(b) {
            var style = window.getComputedStyle(b);
            result.push({
                text: b.textContent.trim().replace(/\\s+/g, ' '),
                tag: b.tagName,
                display: style.display,
                visibility: style.visibility,
                hidden: b.hidden,
                class: b.className.substring(0,60),
                onclick: b.getAttribute('onclick') || '',
            });
        });
        return JSON.stringify(result, null, 2);
    """)
    print(btns)

    # 3. 点击更多展开
    print("\n" + "="*60)
    print("[3] 点击「更多」按钮...")
    print("="*60)
    more_btn = driver.find_element(By.XPATH, "//button[contains(@class, 'cloud-more-toggle')]")
    driver.execute_script("arguments[0].scrollIntoView(true);", more_btn)
    time.sleep(0.3)
    driver.execute_script("arguments[0].click();", more_btn)
    time.sleep(1)

    # 4. 点击后再次检查
    print("\n" + "="*60)
    print("[4] 点击更多后，按钮状态变化:")
    print("="*60)
    btns2 = driver.execute_script("""
        var row = document.querySelector('.table tbody tr');
        var all = row.querySelectorAll('button, a');
        var result = [];
        all.forEach(function(b) {
            var style = window.getComputedStyle(b);
            result.push({
                text: b.textContent.trim().replace(/\\s+/g, ' '),
                display: style.display,
                visibility: style.visibility,
                hidden: b.hidden,
                offsetParent: b.offsetParent !== null,
            });
        });
        return JSON.stringify(result, null, 2);
    """)
    print(btns2)

    # 5. 在全页面搜索"关机"相关可见按钮
    print("\n" + "="*60)
    print("[5] 全页面搜索含「关机」文字的元素:")
    print("="*60)
    shutdown_elms = driver.execute_script("""
        var all = document.querySelectorAll('*');
        var result = [];
        all.forEach(function(el) {
            var text = el.textContent.trim();
            if (text.includes('关机') && el.offsetParent !== null) {
                result.push({
                    tag: el.tagName,
                    text: text.substring(0, 60),
                    class: el.className.substring(0, 60),
                });
            }
        });
        return JSON.stringify(result, null, 2);
    """)
    print(shutdown_elms)

    # 6. 全页面搜索含"开机"文字的元素
    print("\n" + "="*60)
    print("[6] 全页面搜索含「开机」文字的元素:")
    print("="*60)
    poweron_elms = driver.execute_script("""
        var all = document.querySelectorAll('*');
        var result = [];
        all.forEach(function(el) {
            var text = el.textContent.trim();
            if (text.includes('开机') && el.offsetParent !== null) {
                result.push({
                    tag: el.tagName,
                    text: text.substring(0, 60),
                    class: el.className.substring(0, 60),
                });
            }
        });
        return JSON.stringify(result, null, 2);
    """)
    print(poweron_elms)

    # 截图
    driver.save_screenshot("menu_check.png")
    print("\n[截图已保存: menu_check.png]")

except Exception as e:
    print(f"[!] 错误: {e}")
    import traceback
    traceback.print_exc()

finally:
    input("\n按回车关闭浏览器...")
    driver.quit()
