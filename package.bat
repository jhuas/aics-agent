@echo off
chcp 65001 >nul
cd /d %~dp0
echo ============================================================
echo    Zhi-Ke-Fu AI-CS-Agent  Package portable ZIP (green version)
echo   ============================================================
echo   Green version: bundled Python, unzip and run, email-ready.
echo ============================================================

rem ---- pre-checks ----
if not exist "frontend\dist\index.html" (
  echo   [ERROR] frontend\dist\index.html not found.
  echo   Build it first:  cd frontend  ^&^&  npm install  ^&^&  npm run build
  if not "%AICS_NOPAUSE%"=="1" pause
  exit /b 1
)
if not exist "tools\python\python.exe" (
  echo   [ERROR] tools\python\python.exe not found.
  echo   Run prepare_python.bat first.
  if not "%AICS_NOPAUSE%"=="1" pause
  exit /b 1
)

set OUT=release\_green
echo [1/7] Clean old output...
if exist "release\AiCSAgent-Green.zip" del /q "release\AiCSAgent-Green.zip"
if exist "%OUT%" rmdir /s /q "%OUT%"
if not exist release mkdir release

echo [2/7] Copy app code...
mkdir "%OUT%"
robocopy backend "%OUT%\backend" /E /XD __pycache__ data >nul
if exist backend\data\kb.json mkdir "%OUT%\backend\data"
if exist backend\data\kb.json copy /y backend\data\kb.json "%OUT%\backend\data\" >nul
robocopy agent "%OUT%\agent" /E /XD __pycache__ logs >nul
mkdir "%OUT%\agent\logs" 2>nul
robocopy frontend\dist "%OUT%\frontend\dist" /E >nul
robocopy legacy "%OUT%\legacy" /E >nul
if exist assets robocopy assets "%OUT%\assets" /E >nul

echo [3/7] Copy bundled Python...
robocopy tools\python "%OUT%\tools\python" /E /XD __pycache__ >nul

echo [4/7] Copy launcher, docs ^& videos...
copy /y run.bat "%OUT%\" >nul
copy /y 创建桌面快捷方式.bat "%OUT%\" >nul
copy /y start_chrome_debug.bat "%OUT%\" >nul
copy /y run_server.py "%OUT%\" >nul
copy /y requirements.txt "%OUT%\" >nul
copy /y 使用说明.md "%OUT%\" >nul
if exist "release\应用方案和使用教程.pdf" copy /y "release\应用方案和使用教程.pdf" "%OUT%\" >nul
if exist "release\一键启动.exe" copy /y "release\一键启动.exe" "%OUT%\" >nul
if not exist "%OUT%\使用说明.md" (
  echo   [ERROR] 使用说明.md copy failed - check package.bat encoding.
  goto :fail
)
if not exist "%OUT%\应用方案和使用教程.pdf" (
  echo   [ERROR] 应用方案和使用教程.pdf missing - run: python _gen_usage_pdf.py
  goto :fail
)
if not exist "%OUT%\一键启动.exe" (
  echo   [ERROR] 一键启动.exe missing - run build.bat first.
  goto :fail
)
if exist 视频教程 robocopy 视频教程 "%OUT%\视频教程" /E >nul
if not exist "%OUT%\backend\config.json" (
  echo { "store_name": "魔克摩托改装", "deepseek_api_key": "", "deepseek_model": "deepseek-chat", "enable_llm": true } > "%OUT%\backend\config.json"
)

echo [5/7] Create startup shortcut...
if not exist "%OUT%\run.bat" (
  echo   [ERROR] run.bat missing in staging dir.
  goto :fail
)
rem 「创建桌面快捷方式.bat」运行时要调用这个脚本，必须随包一起发出
mkdir "%OUT%\tools" 2>nul
copy /y tools\make_desktop_shortcut.ps1 "%OUT%\tools\" >nul
if not exist "%OUT%\tools\make_desktop_shortcut.ps1" (
  echo   [ERROR] tools\make_desktop_shortcut.ps1 missing in staging dir.
  goto :fail
)
powershell -NoProfile -ExecutionPolicy Bypass -File "tools\make_shortcut.ps1" -Dir "%OUT%"
if errorlevel 1 goto :fail

echo [6/7] Strip caches...
for /d /r "%OUT%" %%d in (__pycache__ .pytest_cache) do if exist "%%d" rmdir /s /q "%%d"
del /s /q "%OUT%\*.pyc" >nul 2>nul

echo [7/7] Compress...
rem 含视频教程时体积近 200MB，Compress-Archive 过慢，改用 .NET ZipFile（快数倍）
set "ROOT=%~dp0"
powershell -NoProfile -Command "Add-Type -AssemblyName System.IO.Compression.FileSystem; [System.IO.Compression.ZipFile]::CreateFromDirectory('%ROOT%%OUT%', '%ROOT%release\AiCSAgent-Green.zip', [System.IO.Compression.CompressionLevel]::Optimal, $false)"
if errorlevel 1 goto :fail

rmdir /s /q "%OUT%"

echo.
echo   Done: release\AiCSAgent-Green.zip
powershell -NoProfile -Command "(Get-Item 'release\AiCSAgent-Green.zip').Length / 1MB | ForEach-Object { '{0:N1} MB' -f $_ }"
echo.
echo   Unzip anywhere (no Python needed), double-click run.bat.
if not "%AICS_NOPAUSE%"=="1" pause
exit /b 0

:fail
echo [ERROR] Package failed.
if not "%AICS_NOPAUSE%"=="1" pause
exit /b 1
