# -*- coding: utf-8 -*-
"""打包感知的路径工具：PyInstaller 冻结环境重定向资源与数据目录。

- 只读资源（frontend/dist、legacy、kb.json）：PyInstaller 解压到 _MEIPASS
- 可写数据（config.json、sessions.json）：放在 exe 所在目录，便于持久化
"""
import os
import sys


def _frozen():
    return bool(getattr(sys, "frozen", False))


def resource_root():
    """只读资源根目录：冻结时为 _MEIPASS，源码模式为项目根 ai-cs-agent/"""
    if _frozen():
        return sys._MEIPASS
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def data_root():
    """可写数据根目录：冻结时为 exe 所在目录，源码模式为 backend/"""
    if _frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)
    return path
