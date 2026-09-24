# -*- coding: utf-8 -*-
"""记忆库：从客服回复记录中学习问答对，检索复用，数据落在程序数据目录。

- 学习源：sessions.json（演示/模拟会话）、agent_events.jsonl（真实引擎事件流）
- 实时记录：引擎每次成功回复后调用 remember() 增量学习
- 检索：中文 bigram 关键词覆盖率评分，命中阈值可调，宁缺毋滥
- 数据文件：<数据目录>/data/memory/memory.json（用户自己的数据文件夹）
"""
import json
import os
import re
import threading
import time

from . import paths

DATA_DIR = paths.ensure_dir(os.path.join(paths.data_root(), "data"))
MEMORY_DIR = paths.ensure_dir(os.path.join(DATA_DIR, "memory"))
MEMORY_FILE = os.path.join(MEMORY_DIR, "memory.json")
SESSIONS_FILE = os.path.join(DATA_DIR, "sessions.json")
EVENTS_FILE = os.path.join(DATA_DIR, "agent_events.jsonl")

_lock = threading.RLock()  # RLock：_load/_save 与调用方共用同一把锁，需可重入
_cache = None
_cache_mtime = None

# 检索命中阈值（0~1）：覆盖率足够高才复用历史回复，避免答错
HIT_MIN = 0.62

# 学习时不收录的渠道（兜底话术 / 静默 / 人工介入没有学习价值）
SKIP_CHANNELS = {"fallback", "silent", "guardrail", "none", "human", "ack"}

_RE_REPLY = re.compile(r"话术=([^｜|]+)")
_RE_DIRTY = re.compile(r"[?？?]{2,}")          # 编码损坏的乱码（如 "??????"）


def _sessions_candidates():
    """学习源 sessions.json 候选：可写数据区优先，其次打包自带的演示样本。"""
    cands = [SESSIONS_FILE]
    try:
        cands.append(os.path.join(paths.resource_root(), "backend", "data", "sessions.json"))
    except Exception:  # pragma: no cover
        pass
    return cands


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _load():
    global _cache, _cache_mtime
    try:
        m = os.path.getmtime(MEMORY_FILE)
    except OSError:
        m = None
    with _lock:
        if _cache is not None and _cache_mtime == m:
            return _cache
        try:
            with open(MEMORY_FILE, encoding="utf-8") as f:
                _cache = json.load(f)
        except Exception:
            _cache = {"enabled": True, "items": []}
        _cache_mtime = m
        return _cache


def _save(data):
    with _lock:
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        _cache_mtime = None  # 强制下次重读


def _grams(text):
    """中文 bigram：'怎么安装脚踏' → {怎么, 么安, 安装, 装脚, 脚踏}"""
    s = re.sub(r"[\s\W_]+", "", str(text or ""))
    if len(s) < 2:
        return set()
    return {s[i:i + 2] for i in range(len(s) - 1)}


def _valid_text(text):
    t = str(text or "").strip()
    if len(t) < 3 or len(t) > 200:
        return False
    if _RE_DIRTY.search(t):
        return False
    if re.fullmatch(r"[0-9\W_]+", t):
        return False
    return True


def _score(q_grams, m_grams, q_len, m_len):
    if not q_grams or not m_grams:
        return 0.0
    inter = len(q_grams & m_grams)
    if not inter:
        return 0.0
    denom = min(len(q_grams), len(m_grams))
    if not denom:
        return 0.0
    score = inter / denom
    # 长度差惩罚：差异越大越可能是不同语境，最多打 7 折
    mx = max(q_len, m_len)
    if mx > 0:
        score *= 1 - 0.3 * abs(q_len - m_len) / mx
    return score


def _extract_reply(result):
    """从引擎发送结果描述里提取实际回复话术（'…｜话术=xxx｜…'）"""
    m = _RE_REPLY.search(str(result or ""))
    return m.group(1).strip() if m else ""


def remember(question, reply, source, channel=None, reply_full=None):
    """记录一条问答记忆。与已有条目高度相似时只累计命中，不重复入库。
    返回 True 表示新增，False 表示已存在/无效。
    """
    q = str(question or "").strip()
    r = str(reply or reply_full or "").strip()
    if not _valid_text(q) or not _valid_text(r):
        return False
    ch = str(channel or "kb")
    if ch in SKIP_CHANNELS:
        return False
    with _lock:
        data = _load()
        items = data.setdefault("items", [])
        q_grams, q_len = _grams(q), len(q)
        for it in items:
            if it.get("disabled"):
                continue
            m_len = len(it.get("question", ""))
            if _score(q_grams, _grams(it.get("question")), q_len, m_len) >= 0.85:
                it["updated_at"] = _now()
                it["channel"] = ch
                return False
        items.append({
            "id": "mem_%d" % (int(time.time() * 1000)),
            "question": q,
            "reply": r,
            "topic": sorted(_grams(q)),
            "source": source,
            "channel": ch,
            "hits": 0,
            "last_used": None,
            "created_at": _now(),
            "updated_at": _now(),
            "disabled": False,
        })
        _save(data)
        return True


def search(text, top_k=3, threshold=HIT_MIN):
    """按关键词覆盖率检索记忆。返回 [(item, score), ...] 降序。"""
    if not _load().get("enabled", True):
        return []
    q = str(text or "").strip()
    if not _valid_text(q):
        return []
    q_grams, q_len = _grams(q), len(q)
    scored = []
    for it in _load().get("items", []):
        if it.get("disabled"):
            continue
        s = _score(q_grams, _grams(it.get("question")), q_len, len(it.get("question", "")))
        if s >= threshold:
            scored.append((it, s))
    scored.sort(key=lambda x: (-x[1], -x[0].get("hits", 0)))
    return scored[:top_k]


def learn_from_sources():
    """全量学习：扫描 sessions.json + agent_events.jsonl，抽取问答对入库。"""
    learned = {"sessions": 0, "events": 0, "skipped": 0}
    # 1) sessions.json：user → assistant 相邻对（数据区优先，包内演示样本兜底）
    for sfile in _sessions_candidates():
        try:
            with open(sfile, encoding="utf-8") as f:
                sess = json.load(f) or {}
        except Exception:
            continue
        for sid, msgs in sess.items():
            for i in range(len(msgs) - 1):
                u, a = msgs[i], msgs[i + 1]
                if u.get("role") != "user" or a.get("role") != "assistant":
                    continue
                ch = (a.get("meta") or {}).get("channel", "")
                if ch in SKIP_CHANNELS:
                    learned["skipped"] += 1
                    continue
                if remember(u.get("text"), a.get("text"), "sessions", ch):
                    learned["sessions"] += 1
                else:
                    learned["skipped"] += 1
        break  # 只在第一个可读的源里学习（数据区优先）
    # 2) agent_events.jsonl：decision(客户消息) → send(回复) 配对
    pending = {}
    try:
        with open(EVENTS_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except Exception:
                    continue
                t = ev.get("t")
                if t == "decision":
                    txt = ev.get("text", "")
                    action = ev.get("action", "")
                    if _valid_text(txt) and action not in SKIP_CHANNELS:
                        pending[ev.get("session", "")] = (txt, action, ev.get("dry", False))
                elif t == "send":
                    sess = ev.get("session", "")
                    if sess in pending:
                        q, action, dry = pending.pop(sess)
                        if dry:
                            continue
                        reply = _extract_reply(ev.get("result", ""))
                        if not reply:
                            learned["skipped"] += 1
                            continue
                        if remember(q, reply, "events", action or ev.get("action", "")):
                            learned["events"] += 1
                        else:
                            learned["skipped"] += 1
    except Exception:
        pass
    return learned


def stats():
    data = _load()
    items = data.get("items", [])
    by_source, by_channel = {}, {}
    hits_total = 0
    for it in items:
        by_source[it.get("source", "?")] = by_source.get(it.get("source", "?"), 0) + 1
        by_channel[it.get("channel", "?")] = by_channel.get(it.get("channel", "?"), 0) + 1
        hits_total += it.get("hits", 0)
    return {
        "enabled": bool(data.get("enabled", True)),
        "total": len(items),
        "by_source": by_source,
        "by_channel": by_channel,
        "hits_total": hits_total,
        "memory_file": MEMORY_FILE,
        "last_learn": _now(),
    }


def all_items(query="", limit=100):
    items = _load().get("items", [])
    q = str(query or "").strip()
    if q:
        items = [it for it in items if q in it.get("question", "") or q in it.get("reply", "")]
    items = sorted(items, key=lambda x: x.get("updated_at", ""), reverse=True)
    return items[:limit]


def record_hit(item):
    """命中一次记忆回复时调用，累计使用次数。"""
    with _lock:
        data = _load()
        for it in data.get("items", []):
            if it.get("id") == item.get("id"):
                it["hits"] = it.get("hits", 0) + 1
                it["last_used"] = _now()
                _save(data)
                return


def set_enabled(enabled):
    with _lock:
        data = _load()
        data["enabled"] = bool(enabled)
        _save(data)
    return {"enabled": bool(enabled), "ok": True}


def remove(item_id):
    """删除一条记忆（学错了可手动删）。"""
    with _lock:
        data = _load()
        items = data.get("items", [])
        n0 = len(items)
        data["items"] = [it for it in items if it.get("id") != item_id]
        if len(data["items"]) != n0:
            _save(data)
            return {"ok": True, "removed": 1}
    return {"ok": False, "removed": 0}


def test(text, top_k=5):
    """检索测试（供驾驶舱面板调试记忆效果）。"""
    hits = search(text, top_k=top_k)
    return [{
        "id": it["id"],
        "question": it["question"],
        "reply": it["reply"],
        "score": round(s, 3),
        "hits": it.get("hits", 0),
    } for it, s in hits]
