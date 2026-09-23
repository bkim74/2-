@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install\install_windows.ps1" -Uninstall
pause
