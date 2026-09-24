# -*- coding: utf-8 -*-
"""智客服 · AI 电商客服 Agent 平台 - 启动入口（源码模式 / PyInstaller 单 exe 通用）

双击防冲突：若 8000 端口已是本程序实例，直接打开驾驶舱并退出，不重复启动。
"""
import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser

import uvicorn

# 便携版 Python（_pth 模式）不会自动把脚本目录加入 sys.path，这里显式注入
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 确保 PyInstaller 静态追踪整个后端包（backend.main -> engine.* / session 等）
from backend.main import app  # noqa: E402,F401
from backend import cdp_browser  # noqa: E402

HOST = "127.0.0.1"
PORT = 8000


def _port_busy(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((HOST, port)) == 0


def _probe_already_running():
    """端口有服务时确认是否本程序：/api/config 返回 store_name 即为指纹"""
    try:
        with urllib.request.urlopen("http://%s:%s/api/config" % (HOST, PORT), timeout=3) as r:
            return "store_name" in r.read(4096).decode("utf-8", "replace")
    except Exception:
        return False


def _open_browser():
    time.sleep(1.2)
    try:
        webbrowser.open("http://%s:%s" % (HOST, PORT))
    except Exception:
        pass


def main():
    for stream in (sys.stdout, sys.stderr):
        if stream and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
    print("=" * 52)
    print("  智客服 · AI 电商客服 Agent 平台")
    print("  浏览器访问: http://%s:%s" % (HOST, PORT))
    print("  （关闭本窗口即停止服务）")
    print("=" * 52)
    if _port_busy(PORT):
        if _probe_already_running():
            ok_cdp, msg_cdp = cdp_browser.ensure_debug_browser()
            print("[CDP] %s" % msg_cdp)
            print("检测到「智客服」已在运行，正在为你打开驾驶舱……")
            if not os.environ.get("AICS_NO_BROWSER"):
                try:
                    webbrowser.open("http://%s:%s" % (HOST, PORT))
                except Exception:
                    pass
            return 0
        print("[ERROR] 端口 %s 已被其他程序占用，无法启动。" % PORT)
        print("       请先在任务管理器结束占用该端口的进程后再试。")
        return 1
    ok_cdp, msg_cdp = cdp_browser.ensure_debug_browser()
    print("[CDP] %s" % msg_cdp)
    # 实时运营数据跟随平台：常驻后台周期同步交易数据页权威日统计 + 订单明细
    try:
        from backend.ops import live as _live
        _ok, _msg = _live.start(_live.interval())
        print("[LIVE] %s" % _msg)
    except Exception as e:  # noqa: BLE001
        print("[LIVE] 自动启动失败：%s" % str(e)[:120])
    if not os.environ.get("AICS_NO_BROWSER"):
        threading.Thread(target=_open_browser, daemon=True).start()
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
    return 0


if __name__ == "__main__":
    sys.exit(main())
