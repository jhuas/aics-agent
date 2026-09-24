# -*- coding: utf-8 -*-
"""命令注册中心（动态插件系统）：管理所有可被 AI 调用的运营命令

- 内置命令：开发者锁定，不可删
- 自定义命令：店家/Agent 可自由增删改（命令工厂产物）
- 持久化到 SQLite，重启自动恢复
"""
import json
import os
import sqlite3
import time
from datetime import datetime

from . import settings

LAYER_TAG = {"builtin": "内置", "agent": "Agent生成", "manual": "店家手写"}


class CommandRegistry:
    def __init__(self, db_path=None, version_store=None, healer=None):
        self.db_path = db_path or settings.COMMANDS_DB
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._handlers = {}      # 内存中的执行函数
        self._schema = {}        # 命令 schema
        self.version_store = version_store
        self.healer = healer
        self._init_db()
        self._load_from_db()

    # ---------- 数据库 ----------
    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS commands (
                    name TEXT PRIMARY KEY,
                    description TEXT,
                    parameters TEXT,
                    handler_name TEXT,
                    builtin INTEGER DEFAULT 0,
                    enabled INTEGER DEFAULT 1,
                    created_at TEXT,
                    created_by TEXT,
                    layer TEXT DEFAULT 'builtin'
                )""")

    def _load_from_db(self):
        # 1. 恢复 Agent 生成的命令（从版本库加载真实代码）
        if self.version_store:
            try:
                with sqlite3.connect(self.version_store.db_path) as vc:
                    names = [r[0] for r in vc.execute(
                        "SELECT DISTINCT name FROM versions WHERE status='active'")]
                from .command_forge import SafeSandbox
                for name in names:
                    latest = self.version_store.get_latest(name)
                    if not latest:
                        continue
                    try:
                        fn = SafeSandbox.compile_and_load(latest["code"], name)
                        fn.__name__ = name
                        self._handlers[name] = fn
                        self._schema[name] = {
                            "type": "function",
                            "function": {"name": name,
                                         "description": latest["description"],
                                         "parameters": latest["parameters"]},
                            "builtin": False,
                            "layer": "agent",
                            "handler_name": name,
                        }
                    except Exception:
                        continue
            except Exception:
                pass

        # 2. 恢复元信息（内置命令的 handler 由 engine 重新绑定）
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT name, description, parameters, builtin, layer FROM commands "
                "WHERE enabled=1").fetchall()
        for name, desc, params, builtin, layer in rows:
            if name in self._handlers:
                continue
            self._schema[name] = {
                "type": "function",
                "function": {
                    "name": name,
                    "description": desc,
                    "parameters": json.loads(params) if params
                    else {"type": "object", "properties": {}, "required": []},
                },
                "builtin": bool(builtin),
                "layer": layer or ("builtin" if builtin else "manual"),
                "handler_name": name,
            }

    # ---------- 注册 ----------
    def register(self, name, description, parameters, handler,
                 builtin=False, created_by="system", layer=None):
        layer = layer or ("builtin" if builtin else "manual")
        self._schema[name] = {
            "type": "function",
            "function": {"name": name, "description": description, "parameters": parameters},
            "builtin": builtin,
            "layer": layer,
            "handler_name": handler.__name__,
        }
        self._handlers[name] = handler
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO commands "
                "(name, description, parameters, handler_name, builtin, enabled, "
                "created_at, created_by, layer) VALUES (?,?,?,?,?,1,?,?,?)",
                (name, description, json.dumps(parameters, ensure_ascii=False),
                 handler.__name__, int(builtin), datetime.now().isoformat(),
                 created_by, layer))

    def unregister(self, name):
        if name not in self._schema:
            return False
        if self._schema[name].get("builtin"):
            return False
        del self._schema[name]
        self._handlers.pop(name, None)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE commands SET enabled=0 WHERE name=?", (name,))
        if self.version_store:
            with sqlite3.connect(self.version_store.db_path) as vc:
                vc.execute("UPDATE versions SET status='deleted' WHERE name=?", (name,))
        return True

    def update(self, name, **kwargs):
        if name not in self._schema:
            return False
        if self._schema[name].get("builtin"):
            return False
        fn = self._schema[name]["function"]
        if "description" in kwargs:
            fn["description"] = kwargs["description"]
        if "parameters" in kwargs:
            fn["parameters"] = kwargs["parameters"]
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE commands SET description=?, parameters=? WHERE name=?",
                         (fn["description"], json.dumps(fn["parameters"], ensure_ascii=False), name))
        return True

    # ---------- 查询 ----------
    def get_tools_schema(self):
        return [{"type": "function", "function": s["function"]}
                for s in self._schema.values()]

    def list_commands(self, include_builtin=True):
        out = []
        for name, s in self._schema.items():
            if not include_builtin and s.get("builtin"):
                continue
            layer = s.get("layer", "builtin")
            out.append({
                "name": name,
                "description": s["function"]["description"],
                "type": LAYER_TAG.get(layer, layer),
                "layer": layer,
                "params": list(s["function"]["parameters"].get("properties", {}).keys()),
            })
        return out

    # ---------- 执行 ----------
    def execute(self, name, args):
        if name not in self._handlers:
            return {"error": f"命令 {name} 未注册或已删除"}
        try:
            fn = self._handlers[name]
            self._validate_args(name, args)
            t0 = time.time()
            result = fn(**args)
            return {"ok": True, "result": result, "elapsed": f"{time.time()-t0:.2f}s"}
        except TypeError as e:
            return {"error": f"参数错误: {e}"}
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {e}"
            layer = self._schema.get(name, {}).get("layer")
            if self.healer and layer == "agent":
                heal = self.healer.handle_failure(name, args, err)
                if heal.get("healed"):
                    try:
                        result = self._handlers[name](**args)
                        return {"ok": True, "result": result,
                                "healed": True, "heal_msg": heal["message"]}
                    except Exception as e2:  # noqa: BLE001
                        return {"error": f"自愈后仍失败: {e2}"}
            return {"error": f"执行失败: {err}"}

    def _validate_args(self, name, args):
        spec = self._schema[name]["function"]["parameters"]
        missing = [r for r in spec.get("required", []) if r not in args]
        if missing:
            raise TypeError(f"缺少必需参数: {missing}")
