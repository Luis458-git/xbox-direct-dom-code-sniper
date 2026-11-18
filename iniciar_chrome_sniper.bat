@echo off
title Lanzador Chrome CDP - Xbox Code Sniper
echo ==========================================================
echo   Iniciando Google Chrome con Remote Debugging (Puerto 9222)
echo ==========================================================
echo.

set "CHROME_PATH=C:\Program Files\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME_PATH%" (
    set "CHROME_PATH=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
)

if not exist "%CHROME_PATH%" (
    echo [ERROR] No se encontro Google Chrome en las rutas estandar.
    echo Edita este archivo .bat y ajusta la variable CHROME_PATH.
    pause
    exit /b 1
)

if not exist "C:\chrome_sniper_profile" (
    mkdir "C:\chrome_sniper_profile"
)

echo Lanzando Chrome en modo depuracion (CDP)...
echo IMPORTANTE: Inicia sesion en tu cuenta de Microsoft en la ventana que se abrira.
start "" "%CHROME_PATH%" --remote-debugging-port=9222 --user-data-dir="C:\chrome_sniper_profile" "https://www.xbox.com/redeem" "https://www.twitch.tv"

echo.
echo [OK] Chrome lanzado en el puerto 9222. Ya puedes ejecutar sniper_xbox_cdp.py
timeout /t 4 >nul
