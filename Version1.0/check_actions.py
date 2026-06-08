#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
检查云电脑控制台 - 获取每台设备的状态和操作选项
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
    driver.save_screenshot("debug_console.png")

    # ===== 1. 获取表格数据 =====
    rows = driver.execute_script("""
        var rows = document.querySelectorAll('.table tbody tr');
        var result = [];
        rows.forEach(function(row) {
            var cells = row.querySelectorAll('td');
            if (cells.length >= 8) {
                var instanceId = cells[3]?.textContent?.trim() || '';
                var cloudId = cells[4]?.textContent?.trim() || '';
                var status = cells[7]?.querySelector('.badge')?.textContent?.trim()
                    || cells[7]?.textContent?.trim() || '';
                var spec = cells[1]?.textContent?.trim() || '';
                var os = cells[2]?.textContent?.trim() || '';
                var expire = cells[6]?.textContent?.trim() || '';

                // 操作列所有按钮文本
                var actionCell = cells[8];
                var buttons = [];
                if (actionCell) {
                    actionCell.querySelectorAll('button, a, .btn, .dropdown-item, span').forEach(function(b) {
                        var t = b.textContent.trim();
                        if (t) buttons.push(t);
                    });
                }
                result.push({
                    'spec': spec,
                    'os': os,
                    'instanceId': instanceId,
                    'cloudId': cloudId,
                    'expire': expire,
                    'status': status,
                    'buttons': buttons
                });
            }
        });
        return result;
    """)

    print(f"\n[*] 找到 {len(rows)} 台云电脑:\n")
    for pc in rows:
        print(f"  实例ID: {pc['instanceId']}")
        print(f"  云电脑ID: {pc['cloudId']}")
        print(f"  状态: {pc['status']}")
        print(f"  操作按钮: {pc['buttons']}")
        print(f"  {'='*60}")

    # ===== 2. 尝试点击展开更多操作 =====
    print("\n[*] 尝试展开每行的操作菜单...\n")

    # 找所有可能的展开按钮
    expand_btns = driver.execute_script("""
        var btns = [];
        // 找 action-cell 里的按钮
        document.querySelectorAll('td.action-cell button, td.action-cell .btn, td:last-child button, td:last-child .btn').forEach(function(b) {
            var t = b.textContent.trim().toLowerCase();
            if (t && b.offsetParent !== null) {
                btns.push({text: b.textContent.trim(), html: b.outerHTML.substring(0,200)});
            }
        });
        return btns;
    """)

    print(f"  找到 {len(expand_btns)} 个可点击按钮:")
    for b in expand_btns:
        print(f"    文本: '{b['text']}'")
        print(f"    HTML: {b['html']}")
        print(f"    {'---'}")

    # 如果有按钮，尝试点击第一个非主要按钮（可能是"更多"）
    for i in range(len(rows)):
        try:
            # 找到这一行最后一个按钮（通常是"更多"或下拉）
            btn = driver.find_element(By.XPATH, f"(//table/tbody/tr)[{i+1}]//td[last()]//button[last()] | (//table/tbody/tr)[{i+1}]//td[last()]//a[last()]")
            if btn.is_displayed():
                txt = btn.text.strip()
                print(f"\n  [行{i+1}] 尝试点击: '{txt}'")
                driver.execute_script("arguments[0].scrollIntoView(true);", btn)
                time.sleep(0.3)
                driver.execute_script("arguments[0].click();", btn)
                time.sleep(0.5)

                # 检查是否有下拉菜单弹出
                menu = driver.execute_script("""
                    var items = [];
                    document.querySelectorAll('.dropdown-menu.show a, .dropdown-menu.show button, [class*=\"visible\"] a, [class*=\"visible\"] button').forEach(function(m) {
                        var t = m.textContent.trim();
                        if (t) items.push(t);
                    });
                    // 也找所有刚出现的元素
                    document.querySelectorAll('.dropdown-item').forEach(function(m) {
                        if (m.offsetParent !== null) {
                            var t = m.textContent.trim();
                            if (t && !items.includes(t)) items.push(t);
                        }
                    });
                    return items;
                """)
                if menu:
                    print(f"  [行{i+1}] 展开菜单选项: {menu}")
                else:
                    print(f"  [行{i+1}] 点击后未检测到下拉菜单")
        except Exception as e:
            print(f"  [行{i+1}] 点击失败: {e}")

    # 保存页面HTML以便分析
    with open("debug_actions.html", "w", encoding="utf-8") as f:
        f.write(driver.page_source)
    print("\n[*] 页面已保存到 debug_actions.html")
    print("[*] 截图已保存到 debug_console.png")

except Exception as e:
    print(f"[!] 错误: {e}")
    import traceback
    traceback.print_exc()

finally:
    print("\n[*] 关闭浏览器")
    driver.quit()
