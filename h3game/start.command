#!/bin/bash
# ダブルクリックで起動(Mac)。H3 の箱を USB でつなぎ、電源を入れてから。
# 席に触れずに画面だけ試すときは: H3_DRY=1 ./start.command
cd "$(dirname "$0")"
if command -v uv >/dev/null; then
  exec uv run --python 3.12 --with pyserial --with pygame python -u bridge.py
fi
python3 -c "import serial, pygame" 2>/dev/null || python3 -m pip install --user pyserial pygame
python3 -u bridge.py
