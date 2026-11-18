@echo off
title Xbox Direct DOM Code Sniper
set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"

if exist "%PYTHON_EXE%" (
    "%PYTHON_EXE%" "%~dp0sniper_xbox_cdp.py"
) else (
    python "%~dp0sniper_xbox_cdp.py"
)
pause
