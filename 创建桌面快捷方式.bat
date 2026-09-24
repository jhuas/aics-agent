@echo off
chcp 65001 >nul
cd /d %~dp0
title 创建桌面快捷方式 · 智客服

echo ============================================
echo   智客服 · AI 电商客服 Agent 平台
echo   正在创建桌面快捷方式...
echo ============================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "tools\make_desktop_shortcut.ps1" -Dir "%~dp0."
if errorlevel 1 (
  echo.
  echo [错误] 创建失败。可直接双击本目录下的 run.bat 启动。
  echo.
  pause
  exit /b 1
)

echo.
echo   完成！桌面上已生成「启动智客服」快捷方式，双击即可启动程序。
echo   提示：请勿删除本文件夹，快捷方式依赖它运行。
echo.
pause
