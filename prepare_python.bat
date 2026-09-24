@echo off
chcp 65001 >nul
cd /d %~dp0
echo ============================================================
echo   智客服 AI-CS-Agent  Prepare bundled Python (portable)
echo   准备内置便携版 Python 3.12（首次打包前执行一次）
echo ============================================================

set "PYDIR=tools\python"
set "VER=3.12.10"
set "ZIPURL=https://www.python.org/ftp/python/%VER%/python-%VER%-embed-amd64.zip"
set "ZIPFILE=%TEMP%\python-%VER%-embed-amd64.zip"

echo [1/5] Download Python %VER% embeddable ...
powershell -NoProfile -Command "Invoke-WebRequest -Uri '%ZIPURL%' -OutFile '%ZIPFILE%' -TimeoutSec 120"
if errorlevel 1 goto :fail

echo [2/5] Extract to %PYDIR% ...
if exist "%PYDIR%" rmdir /s /q "%PYDIR%"
mkdir "%PYDIR%"
powershell -NoProfile -Command "Expand-Archive -Path '%ZIPFILE%' -DestinationPath '%PYDIR%' -Force"
if errorlevel 1 goto :fail

echo [3/5] Enable site-packages ...
set "VERN=%VER:.=%"
(
  echo python%VERN:~0,3%.zip
  echo .
  echo Lib\site-packages
  echo.
  echo # Uncomment to run site.main() automatically
  echo import site
) > "%PYDIR%\python%VERN:~0,3%._pth"

echo [4/5] Install pip ...
powershell -NoProfile -Command "Invoke-WebRequest -Uri 'https://bootstrap.pypa.io/get-pip.py' -OutFile '%TEMP%\get-pip.py' -TimeoutSec 60"
"%PYDIR%\python.exe" "%TEMP%\get-pip.py" --no-warn-script-location -q
if errorlevel 1 goto :fail

echo [5/5] Install dependencies ...
"%PYDIR%\python.exe" -m pip install -r requirements.txt --no-warn-script-location -q
if errorlevel 1 goto :fail

echo.
echo   Done! Bundled Python ready at %PYDIR%
echo   Next: run package.bat to build the green ZIP.
pause
exit /b 0

:fail
echo [ERROR] Prepare failed. Check network / messages above.
pause
exit /b 1
