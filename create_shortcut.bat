@echo off
setlocal
cd /d "%~dp0"
python create_shortcut.py %*
pause
