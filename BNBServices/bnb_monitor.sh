#!/bin/bash
# BNBMonitor — BTC/USDT real-time price monitor (Linux launcher)
# Usage: ./bnb_monitor.sh [path/to/config.ini]

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="${PYTHON:-python3}"
CFG="${1:-$SCRIPT_DIR/config.ini}"

if ! $PYTHON -c "import requests" 2>/dev/null; then
    echo "Installing requests..."
    pip3 install requests
fi

export PYTHONIOENCODING=utf-8
exec $PYTHON "$SCRIPT_DIR/bnb_monitor.py" "$CFG"
