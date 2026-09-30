@echo off
setlocal
cd /d "%~dp0"
python install_plugin.py %*
pause
