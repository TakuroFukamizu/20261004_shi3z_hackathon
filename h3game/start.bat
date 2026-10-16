@echo off
rem ダブルクリックで起動(Windows)。H3 の箱を USB でつなぎ、電源を入れてから。
cd /d "%~dp0"
where uv >nul 2>nul && (uv run --python 3.12 --with pyserial --with pygame python -u bridge.py & goto :eof)
python -c "import serial, pygame" 2>nul || python -m pip install --user pyserial pygame
python -u bridge.py
pause
