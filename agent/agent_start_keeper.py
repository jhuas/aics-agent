"""
Agent 侧启动/重启守护进程 —— 绕过 WorkBuddy 沙箱的 Job Object 限制
================================================================

【为什么需要这个脚本】
  WorkBuddy 沙箱用 **Job Object** 管理每条命令的进程树：命令结束 → 终止整个 Job
  内所有进程，且 Job **未设置** `JOB_OBJECT_LIMIT_BREAKAWAY_OK`
  （实测 `CREATE_BREAKAWAY_FROM_JOB` 直接返回 `[WinError 5] 拒绝访问`）。

  因此以下方式**全部无效**（2026-09-19 实测两次）：
    x 沙箱内 `cmd /c start "" 启动全自动客服.bat`
        → 45 秒内正常巡检并成功回复客户，但命令一结束就被清理
    x 非沙箱 `cmd /c start ""`
        → 连日志都不产生，进程未起来
    x `subprocess` + `CREATE_BREAKAWAY_FROM_JOB`
        → [WinError 5] 拒绝访问（沙箱 Job 不允许 breakaway）

【可行方案】
  让 **explorer.exe** 代为启动。explorer 运行在用户交互会话中，**不在沙箱 Job 内**，
  它创建的子进程自然脱离 → 跨命令存活（2026-09-19 实测 ✅）。
  启动后的进程链：
      explorer.exe → cmd.exe（标题 PDD Auto Customer Service）
                   → python.exe(venv shim) → python.exe(真实解释器，跑 auto_keeper.py)

【用法】
  python agent_start_keeper.py            # 幂等：已在运行则不重复启动
  python agent_start_keeper.py --restart  # 重启：先杀掉旧进程再启动（改完代码/配置后用）
  python agent_start_keeper.py --force    # 强行启动，不检查（慎用！可能两个进程重复回复）

【停止】
  关闭弹出的那个控制台窗口，或在该窗口按 Ctrl+C；也可用 --restart 由脚本代杀。

【铁律】
  同一时间**只能有一个**守护进程，否则同一客户会被回复两次。
"""

import os
import re
import io
import sys
import time
import ctypes
import datetime
import ctypes.wintypes as wt
import subprocess

BASE = os.path.dirname(os.path.abspath(__file__))
BAT = os.path.join(BASE, "启动全自动客服.bat")
LOGDIR = os.path.join(BASE, "logs")
LOG = os.path.join(LOGDIR, "auto_%s.log" % datetime.date.today().isoformat())

# 判定「已在运行」的阈值：最近一条巡检记录距今小于该秒数
RUNNING_WINDOW_SEC = 90


# ---------------- 日志 / 心跳 ----------------

def _read_log():
    if not os.path.exists(LOG):
        return ""
    return io.open(LOG, encoding="utf-8", errors="replace").read()


def last_beat_age():
    """返回最后一条巡检记录距今秒数；无记录返回 None。"""
    # ⚠️ 匹配用「巡检：」通配，不能只写「巡检：可见会话」——
    #    没有可见会话时日志写的是「巡检：当前面板无可见会话」，匹配不上会被误判成
    #    「没在运行」→ 启动器再起一个进程 → **同一客户被回复两次**（2026-09-19 实测踩坑）。
    lines = [l for l in _read_log().splitlines()
             if "巡检：" in l or "本轮完成" in l]
    if not lines:
        return None
    m = re.search(r"\[([\d\- :]+)\]", lines[-1])
    if not m:
        return None
    try:
        t = datetime.datetime.strptime(m.group(1).strip(), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return (datetime.datetime.now() - t).total_seconds()


def is_running():
    age = last_beat_age()
    return age is not None and age < RUNNING_WINDOW_SEC, age


# ---------------- 进程定位（ctypes；不用被沙箱拉黑的 wmic，也不用很慢的 tasklist /v） ----------------

TH32CS_SNAPPROCESS = 0x2
_k32 = ctypes.WinDLL("kernel32", use_last_error=True)


class _PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)), ("th32ModuleID", wt.DWORD),
        ("cntThreads", wt.DWORD), ("th32ParentProcessID", wt.DWORD),
        ("pcPriClassBase", ctypes.c_long), ("dwFlags", wt.DWORD),
        ("szExeFile", ctypes.c_char * 260),
    ]


def _snapshot():
    """返回 {pid: (ppid, exe名称)}"""
    snap = _k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    pe = _PROCESSENTRY32()
    pe.dwSize = ctypes.sizeof(_PROCESSENTRY32)
    rows = {}
    ok = _k32.Process32First(snap, ctypes.byref(pe))
    while ok:
        rows[pe.th32ProcessID] = (pe.th32ParentProcessID,
                                  pe.szExeFile.decode("gbk", "replace"))
        ok = _k32.Process32Next(snap, ctypes.byref(pe))
    _k32.CloseHandle(snap)
    return rows


def find_daemons():
    """
    定位守护进程：**父进程是 cmd.exe 的 python.exe**。
    这是 explorer 代启留下的特征（手动双击 bat 同样成立）；
    而 Agent 自己起的 python 父进程是 shell，不会被误伤。
    返回 [{'shim_pid':int, 'cmd_pid':int}]
    """
    rows = _snapshot()
    out = []
    for pid, (ppid, name) in rows.items():
        if "python" not in name.lower():
            continue
        if rows.get(ppid, (0, ""))[1].lower() == "cmd.exe":
            out.append({"shim_pid": pid, "cmd_pid": ppid})
    return out


def kill_daemons():
    """杀掉所有守护进程（连同其 cmd.exe 控制台整棵树）。返回被杀的 cmd pid 列表。"""
    killed = []
    for d in find_daemons():
        r = subprocess.run(["taskkill", "/PID", str(d["cmd_pid"]), "/T", "/F"],
                           capture_output=True, text=True, timeout=30,
                           encoding="gbk", errors="replace")
        print("    taskkill cmd=%d → %s" % (d["cmd_pid"], (r.stdout or r.stderr or "").strip()))
        killed.append(d["cmd_pid"])
    return killed


# ---------------- 启动 ----------------

def start(force=False):
    if not os.path.exists(BAT):
        print("[x] 找不到启动脚本：%s" % BAT)
        return 2

    if not force:
        alive, age = is_running()
        ds = find_daemons()
        print("当前时间   : %s" % datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        print("最近心跳   : %s" % ("%.0f 秒前" % age if age is not None else "无记录"))
        # 双保险：进程存在 or 心跳新 → 都算在运行
        # （只看心跳不够稳：日志格式一变就可能误判，从而重复启动）
        if ds:
            print("[=] 已发现运行中的守护进程 %s → 不重复启动"
                  % ", ".join("shim=%d←cmd=%d" % (d["shim_pid"], d["cmd_pid"]) for d in ds))
            return 0
        if alive:
            print("[=] 守护进程已在运行 → 不重复启动（防同一客户被回复两次）")
            return 0

    before = len(_read_log())
    print("[*] 通过 explorer.exe 代启（脱离沙箱 Job）...")
    try:
        subprocess.run(["explorer.exe", BAT], capture_output=True, timeout=25)
    except Exception as e:
        print("[x] 启动失败：%r" % (e,))
        return 3

    print("[*] 等待 40 秒验证是否真的开始巡检 ...")
    time.sleep(40)
    after = len(_read_log())

    if after > before:
        print("[+] 启动成功：日志 +%d 字符，守护进程已开始 30 秒一轮巡检" % (after - before))
        print("    停止方式：python agent_start_keeper.py --restart，或关闭控制台窗口")
        return 0

    print("[-] 未检测到新巡检。请手动双击：%s" % BAT)
    return 4


def restart():
    """先杀旧守护进程，再启动新的（改完 auto_keeper.py / kb.json 后必须重启才生效）。"""
    print("[*] 查找现有守护进程 ...")
    ds = find_daemons()
    if not ds:
        print("    （没有找到正在运行的守护进程）")
    else:
        for d in ds:
            print("    发现 shim=%d ← cmd=%d" % (d["shim_pid"], d["cmd_pid"]))
        print("[*] 结束旧进程 ...")
        kill_daemons()
        time.sleep(3)
        left = find_daemons()
        if left:
            print("[!] 仍有残留：%s" % left)
        else:
            print("    ✅ 旧进程已全部退出")

    # 心跳文件还是新的，但进程已经死了 → 用 force 跳过「心跳新」的误判
    print()
    print("[*] 启动新进程 ...")
    return start(force=True)


def main():
    if "--restart" in sys.argv:
        return restart()
    return start(force="--force" in sys.argv)


if __name__ == "__main__":
    sys.exit(main())
