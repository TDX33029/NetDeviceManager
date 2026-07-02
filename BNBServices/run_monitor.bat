@echo off
cd /d "%~dp0"

:: 检查依赖
python -c "import requests" 2>nul
if %errorlevel% neq 0 (
    echo 正在安装依赖...
    pip install requests
)

:: 直接启动，不在bat层做chcp，让Python自己处理编码
echo BNBMonitor - BTC/USDT 启动中...
echo.
python bnb_monitor.py
pause
