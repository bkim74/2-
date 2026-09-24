@echo off
title OnMoment Morning - install
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install\install_windows.ps1"
echo.
pause
