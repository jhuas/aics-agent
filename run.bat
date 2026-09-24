@echo off
chcp 65001 >nul
cd /d %~dp0
title 智客服 · AI 电商客服 Agent 平台

rem ============================================
rem  优先使用内置便携版 Python（绿色版解压即用）
rem  未找到时退回系统 Python（开发者模式）
rem ============================================
set "PY=tools\python\python.exe"
if not exist "%PY%" (
  echo [提示] 未找到内置 Python（tools\python），尝试使用系统 Python ...
  where python >nul 2>nul
  if errorlevel 1 (
    echo.
    echo [错误] 未检测到 Python 环境。
    echo        请安装 Python 3.10+ 后重试，或使用完整绿色版（自带 Python）。
    echo.
    pause
    exit /b 1
  )
  set "PY=python"
  echo [1/3] 安装依赖（首次运行需要，稍等）...
  python -m pip install -r requirements.txt -q
  if errorlevel 1 (
    echo [错误] 依赖安装失败，请检查网络后重试。
    pause
    exit /b 1
  )
)

echo ============================================
echo   智客服 · AI 电商客服 Agent 平台
echo   后端引擎启动中...
echo ============================================

echo [检查配置] ...
"%PY%" -c "import json,os; p=r'backend\config.json'; c=json.load(open(p,encoding='utf-8')) if os.path.exists(p) else {}; k=(c.get('deepseek_api_key') or '').strip(); print('  DeepSeek Key :', '已配置 OK' if k else '未配置（网页右上角「API 配置」可填入）')"

echo [启动服务] http://127.0.0.1:8000 ...
start "" http://127.0.0.1:8000
"%PY%" run_server.py
pause
