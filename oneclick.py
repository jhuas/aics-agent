# -*- coding: utf-8 -*-
"""智客服 · 一键启动（绿色版启动器）

双击本 exe：拉起 CDP 调试浏览器 → 启动后端服务 → 服务就绪后打开驾驶舱。
客服引擎仍需在驾驶舱页面手动点「启动引擎」，避免误自动回复真实客户。

只依赖标准库，不引入后端包，因此可以单独打成很小的 exe。
"""
import os
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser

HOST = "127.0.0.1"
PORT = 8000
BASE = "http://%s:%s" % (HOST, PORT)
READY_TIMEOUT = 120


def root_dir():
    """程序根目录：exe 所在目录（源码运行时为脚本所在目录）"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def port_busy():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((HOST, PORT)) == 0


def is_ours():
    """端口有服务时确认是否本程序：/api/config 返回 store_name 即为指纹"""
    try:
        with urllib.request.urlopen(BASE + "/api/config", timeout=3) as r:
            return "store_name" in r.read(4096).decode("utf-8", "replace")
    except Exception:
        return False


def wait_ready(timeout=READY_TIMEOUT):
    end = time.time() + timeout
    while time.time() < end:
        if is_ours():
            return True
        time.sleep(1)
    return False


def open_cockpit():
    try:
        webbrowser.open(BASE)
    except Exception:
        pass


def _pause(msg="按回车键退出 ..."):
    try:
        input(msg)
    except (EOFError, KeyboardInterrupt):
        pass


def main():
    for stream in (sys.stdout, sys.stderr):
        if stream and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace",
                                   line_buffering=True)
            except Exception:
                pass

    root = root_dir()
    python = os.path.join(root, "tools", "python", "python.exe")
    server = os.path.join(root, "run_server.py")

    print("=" * 52)
    print("  智客服 · AI 电商客服 Agent 平台")
    print("  一键启动")
    print("=" * 52)

    for label, path in (("内置 Python", python), ("后端入口 run_server.py", server)):
        if not os.path.exists(path):
            print("[错误] 未找到%s：%s" % (label, path))
            print("       请把本 exe 放在绿色版解压目录内（与 run.bat 同级），")
            print("       并保持文件夹完整，不要单独挪动里面的文件。")
            _pause()
            return 1

    if port_busy():
        if is_ours():
            print("[提示] 检测到「智客服」已在运行，正在为你打开驾驶舱 ...")
            open_cockpit()
            time.sleep(1)
            return 0
        print("[错误] 端口 %s 已被其他程序占用，无法启动。" % PORT)
        print("       请先在任务管理器结束占用该端口的进程后再试。")
        _pause()
        return 1

    env = dict(os.environ)
    # 由本启动器在服务真正就绪后再开浏览器，避免出现「无法访问」的空白页
    env["AICS_NO_BROWSER"] = "1"

    print("[1/2] 启动后端服务（会自动拉起 CDP 调试浏览器）...")
    try:
        proc = subprocess.Popen([python, server], cwd=root, env=env)
    except Exception as e:  # noqa: BLE001
        print("[错误] 启动后端失败：%s" % e)
        _pause()
        return 1

    print("[2/2] 等待服务就绪（首次启动约 10-30 秒）...")
    if wait_ready():
        print("  服务已就绪，正在打开驾驶舱：%s" % BASE)
        open_cockpit()
    else:
        print("  [警告] 等待超时，请手动在浏览器访问 %s" % BASE)

    print()
    print("  驾驶舱里点「启动引擎」即可开始自动客服。")
    print("  关闭本窗口即停止服务。")
    print()

    try:
        return proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        return 0


if __name__ == "__main__":
    sys.exit(main())
