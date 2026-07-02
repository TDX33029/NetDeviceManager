@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -c "import requests; from urllib3.util import Retry" 2>nul
if %errorlevel% neq 0 (
    echo ⏳ 正在安装依赖...
    pip install requests
    echo.
    echo ✅ 依赖安装完成，按任意键启动监控...
    pause >nul
)
cls
echo.
echo ╔══════════════════════════════════════════════╗
echo ║   BNBMonitor - BTC/USDT 汇率监测             ║
echo ║   按 Ctrl+C 可安全退出                        ║
echo ╚══════════════════════════════════════════════╝
echo.
set PYTHONIOENCODING=utf-8
python bnb_monitor.py
pause
