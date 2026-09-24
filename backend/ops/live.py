# -*- coding: utf-8 -*-
"""运营数据实时同步：常驻后台线程，周期自动采样「交易数据页权威日统计 + 订单明细 +
多周期交易数据（自动点击实时/昨日/7日/30日）」等，让驾驶舱指标实时跟随平台变化。

- 由 run_server 启动时自动拉起，默认每 30 分钟采集一轮（含自动点击多周期），
  也可通过 /ops/live/* API 随时开关、调间隔、手动触发多周期采集。
- 一轮同步失败（如调试浏览器离线 / 未登录商家后台）只跳过，不影响程序。
"""
import threading
import time

from . import pdd_ops_crawler as crawler

_lock = threading.Lock()
_state = {"thread": None, "stop": None, "interval": 1800}


def running():
    t = _state.get("thread")
    return bool(t and t.is_alive())


def interval():
    return _state.get("interval", 1800)


def last_result():
    return _state.get("last", None)


def _loop():
    while not _state["stop"].is_set():
        try:
            base = crawler.live_refresh(orders_too=True)
            per = crawler.collect_trade_periods()
            _state["last"] = {**base,
                              "daily_days": base.get("daily_days", 0),
                              "orders": base.get("orders", 0),
                              "periods": per}
        except Exception:  # noqa: BLE001
            _state["last"] = {"ok": False, "reason": "loop_error"}
        _state["stop"].wait(max(60, _state.get("interval", 1800)))


def start(interval=1800):
    with _lock:
        if running():
            return False, "实时同步已在运行"
        _state["interval"] = max(60, int(interval or 1800))
        _state["stop"] = threading.Event()
        t = threading.Thread(target=_loop, daemon=True)
        _state["thread"] = t
        t.start()
        return True, "实时同步已启动（间隔 %d 秒）" % _state["interval"]


def stop():
    with _lock:
        if not running():
            return False, "实时同步未运行"
        _state["stop"].set()
        try:
            _state["thread"].join(timeout=12)
        except Exception:  # noqa: BLE001
            pass
        _state["thread"] = None
        _state["last"] = None
        return True, "实时同步已停止"


def trigger_periods():
    """手动立即执行一轮多周期交易数据采集（无需等定时）。"""
    return crawler.collect_trade_periods()


def control(action, interval=None):
    if action == "start":
        return start(interval)
    if action == "stop":
        return stop()
    if action == "trigger_periods":
        return trigger_periods()
    return False, "未知动作"