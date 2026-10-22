@echo off
title OpenClaw Gateway
echo ============================================
echo   OpenClaw Gateway Launcher
echo   Model: Qwen3.5-9B (LM Studio local)
echo ============================================
echo.

set NODE_PATH=C:\Users\18210\.workbuddy\binaries\node\versions\node-v24.22.0-win-x64
set PATH=%NODE_PATH%;%PATH%

set NO_PROXY=localhost,127.0.0.1
set no_proxy=localhost,127.0.0.1

rem ---- 1. already running? ----
netstat -ano | findstr ":18789" | findstr "LISTENING" >nul 2>&1
if not errorlevel 1 (
    echo [!] Port 18789 is already listening - Gateway seems to be running.
    echo     Open: http://127.0.0.1:18789
    echo     If the page does not load, close the other OpenClaw window first.
    echo.
    pause
    exit /b 0
)

rem ---- 2. is openclaw command available? ----
where openclaw >nul 2>&1
if errorlevel 1 (
    echo [X] "openclaw" not found in PATH.
    echo     Check that this folder exists: %NODE_PATH%
    echo.
    pause
    exit /b 1
)

rem ---- 3. LM Studio check (the model server) ----
netstat -ano | findstr ":1234" | findstr "LISTENING" >nul 2>&1
if errorlevel 1 (
    echo [!] No service on port 1234 - LM Studio may not be running.
    echo     OpenClaw will hang or fail if the model server is down.
    echo.
)

echo Starting OpenClaw Gateway...
echo.
echo Open http://127.0.0.1:18789 after it starts.
echo Keep this window open - closing it stops the service.
echo ============================================
echo.

openclaw gateway run

echo.
echo ============================================
echo Gateway exited with code %errorlevel%
if not "%errorlevel%"=="0" echo Copy the lines above if you need help.
echo ============================================
pause
