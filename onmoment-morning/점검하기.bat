@echo off
title OnMoment Morning
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (py -3 onmoment_morning.py --diagnose) else (python onmoment_morning.py --diagnose)
echo.
echo --- morning.log (last 20 lines) ---
powershell -NoProfile -Command "Get-Content -Path ($env:USERPROFILE + '\OnMoment\morning\morning.log') -Tail 20 -ErrorAction SilentlyContinue"
echo.
pause
