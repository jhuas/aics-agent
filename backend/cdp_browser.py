# -*- coding: utf-8 -*-
"""调试浏览器（CDP 9222）管理：检测与自动拉起。

供两处复用：
- run_server.py 启动入口：双击 exe 时若 9222 未就绪自动拉起调试浏览器
- agentctl.start()：「启动引擎」时兜底确保 CDP 就绪（引擎内部仍会重试）
"""
import os
import subprocess
import time
import urllib.request

CDP_PORT = 9222
CDP_PROFILE = r"C:\chrome-debug-profile"
_BROWSER_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def cdp_ready():
    try:
        with urllib.request.urlopen("http://127.0.0.1:%s/json/version" % CDP_PORT, timeout=1.5) as r:
            return r.status == 200
    except Exception:
        return False


def find_browser():
    for p in _BROWSER_CANDIDATES:
        if os.path.isfile(p):
            return p
    return None


def ensure_debug_browser(timeout=12.0):
    """CDP 未就绪时自动拉起调试浏览器（沿用登录 Profile）。返回 (ok, msg)。"""
    if cdp_ready():
        return True, "CDP 调试端口 %s 已就绪" % CDP_PORT
    if os.environ.get("AICS_NO_CHROME"):
        return False, "已跳过自动启动调试浏览器（AICS_NO_CHROME）"
    browser = find_browser()
    if not browser:
        return False, "未找到 Chrome/Edge，请手动运行 start_chrome_debug.bat"
    try:
        subprocess.Popen(
            [browser,
             "--remote-debugging-port=%s" % CDP_PORT,
             "--user-data-dir=%s" % CDP_PROFILE,
             "--no-first-run", "--no-default-browser-check",
             "https://mms.pinduoduo.com"],
        )
    except Exception as e:
        return False, "启动调试浏览器失败: %s" % e
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(0.5)
        if cdp_ready():
            return True, "CDP 调试端口 %s 已就绪" % CDP_PORT
    return False, "调试浏览器启动中（若未弹出窗口，请手动双击 start_chrome_debug.bat）"
