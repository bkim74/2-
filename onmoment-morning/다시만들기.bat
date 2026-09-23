@echo off
title OnMoment Morning
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (py -3 onmoment_morning.py --force) else (python onmoment_morning.py --force)
if errorlevel 1 pause
