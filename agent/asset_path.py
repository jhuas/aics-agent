# -*- coding: utf-8 -*-
"""
素材路径解析 / 程序目录定位
============================
目的：让这套程序**换台电脑、甚至被别人拷走也能跑**。

两条规则
--------
1) 配置（kb.json / 代码）里写的**绝对路径**（如 `D:/work/客服资料/实拍图/A B混合`）
   如果在本机**存在** → 原样使用（本机行为完全不变）。
2) 不存在 → 把它映射到「**程序目录/素材/<客服资料之后的部分>**」再试一次。
   例：`D:/work/客服资料/实拍图/A B混合` → `<程序目录>/素材/实拍图/A B混合`
3) 仍然没有 → 原样返回（调用方都是 `os.path.isdir()` 先判断的，会自然跳过，不会崩）。

为什么需要 `app_dir()`
----------------------
打包成 exe（PyInstaller onefile）后，`__file__` 指向**临时解包目录**，
用它去找 kb.json / 素材必然找不到。必须用 `sys.executable` 所在目录。

配套的配置（kb.json）
--------------------
    "_路径配置": {
      "客服资料根目录": "D:/work/客服资料",   // 本机素材根目录（不存在则回退）
      "包内素材目录": "素材"                 // 回退时用的相对目录名
    }
`_路径配置` 缺失时，回退读旧的顶层键 `_客服资料根目录`。
"""
import json
import os
import sys

DEFAULT_LOCAL_DIRNAME = "素材"


def app_dir():
    """程序所在目录：打包后 = exe 所在目录；未打包 = 本文件所在目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def bundle_dir():
    """
    打包后 = PyInstaller 解包目录（sys._MEIPASS），里面是**打进 exe 的自带文件**；
    未打包 = 程序目录（等同于 app_dir()）。
    用途：当用户只拷走了 exe、exe 同目录没有 kb.json / 素材 时，仍能从包内找到自带的。
    """
    b = getattr(sys, "_MEIPASS", None)
    return b if b else app_dir()


BASE_DIR = app_dir()


def kb_path():
    """
    kb.json 的实际路径。优先级：
      1) <exe 同目录>/kb.json —— 用户可自行拷贝修改（改话术、改词表）
      2) <包内自带>/kb.json  —— 打包时用 --add-data 塞进 exe 的默认配置
      3) <包内自带>/agent/kb.json —— agent 目录整体打进 exe 时的位置
    都没有时返回第 1 个路径（读不到就自然走代码里的兜底默认值）。
    """
    p = os.path.join(app_dir(), "kb.json")
    if os.path.exists(p):
        return p
    for cand in (bundle_dir(), os.path.join(bundle_dir(), "agent")):
        q = os.path.join(cand, "kb.json")
        if os.path.exists(q):
            return q
    return p


KB_FILE = kb_path()

_cache = [None]


def config():
    """读取 kb.json 的 `_路径配置`（带回退），结果缓存。"""
    if _cache[0] is not None:
        return _cache[0]
    cfg = {}
    try:
        with open(KB_FILE, encoding="utf-8") as f:
            d = json.load(f) or {}
        cfg = dict(d.get("_路径配置") or {})
        if not cfg.get("客服资料根目录"):
            cfg["客服资料根目录"] = d.get("_客服资料根目录") or ""
    except Exception:
        pass
    _cache[0] = cfg
    return cfg


def reload_config():
    """改完 kb.json 想让新路径生效时调用。"""
    _cache[0] = None
    return config()


def local_root():
    """包内素材根目录（<程序目录>/素材）"""
    name = str(config().get("包内素材目录") or DEFAULT_LOCAL_DIRNAME).strip() or DEFAULT_LOCAL_DIRNAME
    return os.path.join(BASE_DIR, name)


def material_roots():
    """
    素材查找根目录（按优先级）：
      1) <程序目录>/素材          —— 用户放在程序旁边、可自行增删
      2) <包内自带>/素材          —— 打包时 --add-data 塞进 exe 的那份
    """
    name = str(config().get("包内素材目录") or DEFAULT_LOCAL_DIRNAME).strip() or DEFAULT_LOCAL_DIRNAME
    roots = [os.path.join(BASE_DIR, name)]
    b = os.path.join(bundle_dir(), name)
    if os.path.normcase(b) not in [os.path.normcase(x) for x in roots]:
        roots.append(b)
    return roots


def data_root():
    """
    当前实际使用的「客服资料根目录」：
      · 本机配置的绝对路径**存在** → 用它（本机原行为）
      · 否则 → 用 包内素材目录（<程序目录>/素材，其次 <包内自带>/素材）
      · 都没有 → 返回配置值（后续 isdir 判断会失败并跳过）
    """
    cfg = config()
    ext = str(cfg.get("客服资料根目录") or "").replace("/", os.sep).rstrip(os.sep)
    if ext and os.path.isdir(ext):
        return ext
    for root in material_roots():
        if os.path.isdir(root):
            return root
    return ext or local_root()


def resolve(path):
    """
    把配置里的素材路径解析成**本机真实可用**的路径。
    绝对路径存在 → 原样返回；否则依次尝试映射到 程序目录/素材、包内自带/素材；再不行 → 原样返回。
    """
    if not path:
        return path
    p = str(path).replace("/", os.sep)
    if os.path.exists(p):
        return p
    ext = str(config().get("客服资料根目录") or "").replace("/", os.sep).rstrip(os.sep)
    if ext and p.lower().startswith(ext.lower()):
        rel = p[len(ext):].lstrip("\\/")
        if rel:
            for root in material_roots():
                cand = os.path.join(root, rel)
                if os.path.exists(cand):
                    return cand
    return p


def exists(path):
    """解析后是否存在"""
    return os.path.exists(resolve(path))


def abs_path(rel):
    """相对「程序目录」取绝对路径（用于包内自带文件，如 素材/说明书）"""
    return os.path.join(BASE_DIR, str(rel).replace("/", os.sep))


if __name__ == "__main__":
    print("程序目录      :", BASE_DIR)
    print("包内自带目录   :", bundle_dir())
    print("kb.json       :", KB_FILE, os.path.exists(KB_FILE))
    print("配置          :", json.dumps(config(), ensure_ascii=False))
    print("客服资料根目录 :", data_root())
    print("素材查找根目录 :")
    for r in material_roots():
        print("    %s  (%s)" % (r, os.path.isdir(r)))
    for demo in (r"D:\work\客服资料\实拍图\A B混合",
                 r"D:\work\客服资料\实拍图\定风翼堵盖",
                 r"D:\work\客服资料\安装视频"):
        print("  %-40s -> %s  (%s)" % (demo, resolve(demo), exists(demo)))
