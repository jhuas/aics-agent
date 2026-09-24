# -*- coding: utf-8 -*-
"""自动化引擎进程管理 + 事件流读取（驾驶舱后端）"""
import json
import os
import subprocess
import sys
import threading
import time

from . import cdp_browser, paths

AGENT_DIR = os.path.join(paths.resource_root(), "agent")
EVENTS_FILE = os.path.join(paths.data_root(), "data", "agent_events.jsonl")

_lock = threading.Lock()
_proc = None
_started_at = None
_interval = 30
_dry = False
# exe（frozen）模式：单文件 exe 无法再用子进程跑 auto_keeper，改为进程内线程
_thread = None
_stop_ev = None


def events_path():
    return EVENTS_FILE


def _start_subprocess(interval, dry):
    """源码 / 绿色版：启动 agent 子进程（auto_keeper.py --event-file）。"""
    global _proc, _started_at, _interval, _dry
    with _lock:
        if _proc and _proc.poll() is None:
            return False, "自动化已在运行"
        paths.ensure_dir(os.path.dirname(EVENTS_FILE))
        _interval = max(5, int(interval))
        _dry = bool(dry)
        cmd = [
            sys.executable, "auto_keeper.py",
            "--interval", str(_interval),
            "--event-file", EVENTS_FILE,
        ]
        if _dry:
            cmd.append("--dry")
        _proc = subprocess.Popen(
            cmd, cwd=AGENT_DIR,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        _started_at = time.time()
        return True, "已启动"


def _frozen_agent_dir():
    """exe 解包目录里的 agent 资源目录（--add-data 打进 exe 的 agent/*）"""
    return os.path.join(getattr(sys, "_MEIPASS", ""), "agent")


def _prepare_frozen_import():
    """提前导入 auto_keeper，失败立即抛出（让 start 返回明确错误）。"""
    d = _frozen_agent_dir()
    if d not in sys.path:
        sys.path.insert(0, d)
    import auto_keeper  # noqa: F401


def _run_agent_thread(interval, dry):
    """exe 模式：进程内线程跑 auto_keeper 主循环，等价于其 main() 的 while True。"""
    global _thread
    try:
        import auto_keeper as ak
        ak.EVENT_FILE = EVENTS_FILE
        ak.STATS["start"] = ak.now()
        ak._event("status", state="running", interval=interval, dry=dry)
        ak.log("=" * 56)
        ak.log("🤖 全自动客服已启动｜间隔 %d 秒%s" % (interval, "｜预演模式" if dry else ""))
        ak.log("   敏感词过滤：已启用（极限词自动替换 / 高危词拦截）")
        ak.log("   定期汇报：每整点生成 logs/report_YYYY-MM-DD.md")
        ak.log("=" * 56)
        while not _stop_ev.is_set():
            round_start = time.time()
            try:
                n = ak.run_once(dry=dry)
                if n:
                    ak.log("本轮完成，已自动回复 %d 个会话" % n)
            except Exception as e:  # noqa: BLE001
                ak.STATS["errors"] += 1
                ak.log("⚠️ 本轮异常（将自动重试）：%s" % str(e)[:200])
            try:
                ak.maybe_hourly_report()
            except Exception:  # noqa: BLE001
                pass
            wait = max(5.0, interval - (time.time() - round_start))
            if _stop_ev.wait(wait):
                break
        ak._event("status", state="stopped")
    except Exception as e:  # noqa: BLE001
        try:
            with open(EVENTS_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "t": "log", "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "msg": "⚠️ 引擎线程异常：%s" % str(e)[:300],
                }, ensure_ascii=False) + "\n")
        except Exception:  # noqa: BLE001
            pass
    finally:
        _thread = None


def _start_threaded(interval, dry):
    global _thread, _started_at, _interval, _dry, _stop_ev
    with _lock:
        if _thread and _thread.is_alive():
            return False, "自动化已在运行"
        paths.ensure_dir(os.path.dirname(EVENTS_FILE))
        _interval = max(5, int(interval))
        _dry = bool(dry)
        try:
            _prepare_frozen_import()
        except Exception as e:  # noqa: BLE001
            return False, "引擎加载失败：%s" % e
        _stop_ev = threading.Event()
        _thread = threading.Thread(
            target=_run_agent_thread, args=(_interval, _dry), daemon=True)
        _thread.start()
        _started_at = time.time()
        return True, "已启动"


def _stop_threaded():
    global _thread, _started_at, _stop_ev
    with _lock:
        if not _thread or not _thread.is_alive():
            _thread = None
            return False, "自动化未在运行"
        _stop_ev.set()
        _thread.join(timeout=8)
        _thread = None
        _started_at = None
        return True, "已停止"


def _frozen():
    return bool(getattr(sys, "frozen", False))


def start(interval=30, dry=False):
    """启动自动化引擎。启动前先确保 CDP 调试浏览器就绪（未就绪自动拉起，引擎内部仍会重试）。"""
    ok_cdp, msg_cdp = cdp_browser.ensure_debug_browser()
    if _frozen():
        ok, msg = _start_threaded(interval, dry)
    else:
        ok, msg = _start_subprocess(interval, dry)
    if ok:
        return True, "%s｜%s" % (msg, msg_cdp)
    return False, "%s（%s）" % (msg, msg_cdp)


def stop():
    """停止自动化引擎。"""
    if _frozen():
        return _stop_threaded()
    global _proc, _started_at
    with _lock:
        if not _proc or _proc.poll() is not None:
            _proc = None
            return False, "自动化未在运行"
        try:
            _proc.terminate()
        except Exception:
            pass
        try:
            _proc.wait(timeout=6)
        except Exception:
            try:
                _proc.kill()
            except Exception:
                pass
        _proc = None
        _started_at = None
        return True, "已停止"


def running():
    if _frozen():
        with _lock:
            return bool(_thread and _thread.is_alive())
    with _lock:
        return bool(_proc and _proc.poll() is None)


def status():
    """运行状态 + 事件流聚合统计。"""
    evs = _read_events()
    stats = _aggregate(evs)
    last = evs[-1] if evs else None
    return {
        "running": running(),
        "pid": _proc.pid if (_proc and _proc.poll() is None) else None,
        "started_at": _started_at,
        "interval": _interval,
        "dry": _dry,
        "event_count": len(evs),
        "last_event": last,
        "stats": stats,
    }


def events(after=0):
    """增量拉取事件（after = 已读条数）。返回 (cursor, events)。"""
    evs = _read_events()
    tail = evs[after:]
    return len(evs), tail


def replay(limit=200):
    """回放历史事件（从 JSONL 读取，含已停止的旧记录）。"""
    evs = _read_events()
    return evs[-limit:]


def _read_events():
    if not os.path.exists(EVENTS_FILE):
        return []
    out = []
    try:
        with open(EVENTS_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        return []
    return out


def _aggregate(evs):
    stats = {
        "rounds": 0, "handled": 0, "human": 0, "refund": 0,
        "unknown": 0, "ack": 0, "send": 0, "errors": 0,
    }
    for e in evs:
        t = e.get("t")
        if t == "round":
            stats["rounds"] += 1
        elif t == "human":
            stats["human"] += 1
            if e.get("refund"):
                stats["refund"] += 1
        elif t == "unknown":
            stats["unknown"] += 1
        elif t == "ack":
            stats["ack"] += 1
        elif t == "send":
            stats["send"] += 1
            stats["handled"] += 1
        elif t == "log" and (
            "⚠️" in e.get("msg", "") or "❌" in e.get("msg", "")
            or "✗" in e.get("msg", "") or "处理异常" in e.get("msg", "")
        ):
            stats["errors"] += 1
    return stats
