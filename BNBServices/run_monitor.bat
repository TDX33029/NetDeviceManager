@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -c "import requests; from urllib3.util import Retry" 2>nul
if %errorlevel% neq 0 (
    echo 正在安装依赖...
    pip install requests
)
set PYTHONIOENCODING=utf-8
python bnb_monitor.py
pause
