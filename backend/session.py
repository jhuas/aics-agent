# -*- coding: utf-8 -*-
"""会话存储：sessions.json（模拟演示 + 统计用）"""
import json
import os
import threading
import time

from . import paths

DATA_DIR = paths.ensure_dir(os.path.join(paths.data_root(), "data"))
SESSIONS_FILE = os.path.join(DATA_DIR, "sessions.json")

_lock = threading.Lock()


def _load():
    try:
        with open(SESSIONS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save(data):
    with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def get_history(session_id):
    with _lock:
        return _load().get(session_id, [])


def append_message(session_id, role, text, meta=None):
    with _lock:
        data = _load()
        data.setdefault(session_id, []).append({
            "role": role,
            "text": text,
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "meta": meta or {},
        })
        _save(data)


def clear_session(session_id):
    with _lock:
        data = _load()
        data.pop(session_id, None)
        _save(data)


def all_sessions():
    return _load()


def stats():
    """运行统计：会话数、消息数、按渠道/动作聚合"""
    data = _load()
    total_sessions = len(data)
    total_msgs = 0
    channels = {}
    actions = {}
    for sid, msgs in data.items():
        for m in msgs:
            total_msgs += 1
            meta = m.get("meta", {})
            ch = meta.get("channel", "unknown")
            channels[ch] = channels.get(ch, 0) + 1
            ac = meta.get("action", "unknown")
            actions[ac] = actions.get(ac, 0) + 1
    return {
        "total_sessions": total_sessions,
        "total_messages": total_msgs,
        "channels": channels,
        "actions": actions,
    }
