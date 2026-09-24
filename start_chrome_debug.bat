@echo off
REM ============================================================
REM  Launch Chrome with remote debugging port 9222 (isolated profile)
REM  For Pinduoduo customer-service automation
REM  Made by WorkBuddy - double-click to run
REM ============================================================
setlocal enabledelayedexpansion

set "CHROME="
REM --- Try common Chrome install paths ---
if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" set "CHROME=C:\Program Files\Google\Chrome\Application\chrome.exe"
if not defined CHROME if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" set "CHROME=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
if not defined CHROME if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" set "CHROME=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"

REM --- Fallback to Edge (also supports remote debugging) ---
if not defined CHROME if exist "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" set "CHROME=C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
if not defined CHROME if exist "C:\Program Files\Microsoft\Edge\Application\msedge.exe" set "CHROME=C:\Program Files\Microsoft\Edge\Application\msedge.exe"

if not defined CHROME (
    echo [ERROR] Could not find Chrome or Edge. Please edit this file and set CHROME manually.
    pause
    exit /b 1
)

echo [OK] Using browser: %CHROME%
echo [..] Launching with remote debugging on port 9222...
start "" "%CHROME%" --remote-debugging-port=9222 --user-data-dir=C:\chrome-debug-profile --no-first-run --no-default-browser-check

echo [..] Waiting 4 seconds for port to bind...
timeout /t 4 /nobreak >nul

echo [..] Checking port 9222 ...
echo ------------------------------------------------------------
netstat -ano | findstr ":9222"
echo ------------------------------------------------------------
echo.
echo If you see a line with "LISTENING" above, the debug port is READY.
echo Next: in the Chrome window that just opened, log in to Pinduoduo chat.
echo Leave this window open. Do NOT close it.
echo.
echo If you see NOTHING above, press Enter and look at the [ERROR] tips.
echo ------------------------------------------------------------
pause
