# -*- coding: utf-8 -*-
"""kb.json 知识库加载与规则匹配"""
import json
import os
import threading

from .. import paths

DATA_DIR = os.path.join(paths.resource_root(), "backend", "data")
KB_FILE = os.path.join(DATA_DIR, "kb.json")

_lock = threading.Lock()
_cache = None
_mtime = None


def kb_path():
    return KB_FILE


def load_kb(force=False):
    """加载 kb.json（带 mtime 缓存，网页端改配置后自动重载）"""
    global _cache, _mtime
    try:
        m = os.path.getmtime(KB_FILE)
    except OSError:
        m = None
    with _lock:
        if not force and _cache is not None and _mtime == m:
            return _cache
        with open(KB_FILE, encoding="utf-8") as f:
            _cache = json.load(f)
        _mtime = m
        return _cache


def split_match(v):
    """规则的 match 字段：可能是 list 或 '|' 分隔的字符串"""
    if isinstance(v, list):
        return [str(x) for x in v]
    if isinstance(v, str):
        return [x for x in v.split("|") if x]
    return []


def match_rule(text, rule):
    for kw in split_match(rule.get("match")):
        if kw and kw in text:
            return True
    return False


def detect_category(text, kb=None):
    """按文本关键词识别商品品类（仅 ready 品类参与隔离）。
    返回品类名或 None。用于防止跨品类发错素材（如定风翼会话绝不收脚踏视频）。
    """
    kb = kb or load_kb()
    routes = kb.get("_商品类目路由", {})
    for name, cfg in routes.items():
        if name.startswith("_"):
            continue
        if cfg.get("状态") != "ready":
            continue
        for kw in split_match(cfg.get("关键词")):
            if kw and kw in text:
                return name
    return None


def match_kb(text, kb=None, category=None):
    """按 priority 降序 + 原顺序匹配 rules；install_ask 是内部规则，由护栏单独处理。
    category 非空时，跳过标注了其它品类的规则（品类隔离，防发错货）。
    """
    kb = kb or load_kb()
    rules = sorted(kb.get("rules", []), key=lambda r: -int(r.get("priority", 0)))
    for r in rules:
        if r.get("id") == "install_ask":
            continue
        rcat = r.get("_category")
        if category and rcat and rcat != category:
            continue
        if match_rule(text, r):
            return r
    return None
