@echo off
chcp 65001 >nul
cd /d %~dp0
echo ============================================================
echo   智客服 AI-CS-Agent  Build single-file EXE (PyInstaller)
echo ============================================================

echo [1/4] Check frontend build output...
if not exist "frontend\dist\index.html" (
  echo   [ERROR] frontend\dist\index.html not found.
  echo   Build it first:  cd frontend  ^&^&  npm install  ^&^&  npm run build
  if not "%AICS_NOPAUSE%"=="1" pause
  exit /b 1
)
echo   OK - frontend dist ready.

echo [2/4] Check PyInstaller...
python -m pip show pyinstaller >nul 2>&1
if errorlevel 1 (
  echo   Installing PyInstaller...
  python -m pip install pyinstaller -q
  if errorlevel 1 goto :fail
)
echo   OK - PyInstaller ready.

echo [3/4] Packaging (1-3 minutes)...
set "ROOT=%~dp0"
rem 干净副本：agent 目录只打代码与配置，排除运行时 logs 与缓存
if exist "%ROOT%build_tmp\agent" rmdir /s /q "%ROOT%build_tmp\agent"
robocopy "%ROOT%agent" "%ROOT%build_tmp\agent" /E /XD __pycache__ logs >nul
python -m PyInstaller --noconfirm --clean --onefile --console ^
  --distpath "%ROOT%release" --workpath "%ROOT%build_tmp" --specpath "%ROOT%build_tmp" ^
  --add-data "%ROOT%frontend\dist;frontend\dist" ^
  --add-data "%ROOT%legacy;legacy" ^
  --add-data "%ROOT%build_tmp\agent;agent" ^
  --add-data "%ROOT%backend\data\kb.json;backend\data" ^
  --hidden-import uvicorn.logging ^
  --hidden-import uvicorn.loops.auto ^
  --hidden-import uvicorn.loops.asyncio ^
  --hidden-import uvicorn.protocols.http.auto ^
  --hidden-import uvicorn.protocols.http.h11_impl ^
  --hidden-import uvicorn.protocols.websockets.auto ^
  --hidden-import uvicorn.protocols.websockets.wsproto_impl ^
  --hidden-import uvicorn.lifespan.on ^
  --hidden-import uvicorn.lifespan.off ^
  --hidden-import websocket ^
  --name "AiCSAgent" ^
  run_server.py
if errorlevel 1 goto :fail

echo [4/5] Build one-click launcher...
rem 启动器只依赖标准库，单独打一个小 exe；先打 ASCII 名再改名，避免 PyInstaller 处理中文 --name
python -m PyInstaller --noconfirm --clean --onefile --console ^
  --distpath "%ROOT%release" --workpath "%ROOT%build_tmp\launcher" --specpath "%ROOT%build_tmp\launcher" ^
  --icon "%ROOT%assets\app.ico" ^
  --name "AiCSAgent-OneClick" ^
  oneclick.py
if errorlevel 1 goto :fail
if exist "%ROOT%release\一键启动.exe" del /q "%ROOT%release\一键启动.exe"
move /y "%ROOT%release\AiCSAgent-OneClick.exe" "%ROOT%release\一键启动.exe" >nul
if not exist "%ROOT%release\一键启动.exe" (
  echo   [ERROR] one-click launcher missing after build.
  goto :fail
)

echo [5/5] Done!
echo   Output: release\AiCSAgent.exe        (main program)
echo   Output: release\一键启动.exe         (one-click launcher)
echo   Double-click to start, browser opens http://127.0.0.1:8000
echo   DeepSeek API key: click "API Config" in the web UI,
echo   or edit config.json next to the exe.
if not "%AICS_NOPAUSE%"=="1" pause
exit /b 0

:fail
echo [ERROR] Build failed. See messages above.
if not "%AICS_NOPAUSE%"=="1" pause
exit /b 1
