@echo off
title BNBMonitor - BTC/USDT
cd /d "D:\Document\tempPrj\NetDeviceManager\BNBServices"

echo BNBMonitor - BTC/USDT starting...
echo.

:: 直接用绝对路径，不走 PATH，避免 CMD 从 bash 继承环境找不到 python
C:\Users\Lenovo\AppData\Local\Programs\Python\Python314\python.exe bnb_monitor.py

echo.
echo ========== BNBMonitor exited ==========
pause
