# -*- coding: utf-8 -*-
"""Agent 驱动的命令生成与进化引擎（命令工厂）

核心理念：店家不写代码，只提需求（自然语言）
    "我要一个能自动给差评客户发补偿券的命令，参数是订单号和金额"
    → Agent 理解意图 → 生成代码 → AST 安全审查 → 沙箱试运行 → 版本入库 → 注册上线

三层能力：
    1. CommandBuilder : 需求 → 代码生成 → 注册（CREATE）
    2. CommandEvolver : 对现有命令做改进（UPDATE / ENHANCE）
    3. SelfHealer     : 命令执行失败时自动修复代码（HEAL）

安全底线：生成代码必须过 AST 静态审查 + 沙箱试运行，全程版本管理可回滚。
"""
import ast
import json
import os
import sqlite3
import time
import traceback
from datetime import datetime
from typing import Callable, Dict, List, Optional

from ..engine import llm
from . import settings


# ============================================================
#  一、静态安全审查器
# ============================================================
class SecurityAuditor:
    """对 LLM 生成的代码做 AST 级安全审查（比正则可靠）"""

    FORBIDDEN_MODULES = {
        "os", "sys", "subprocess", "shutil", "socket", "pickle",
        "marshal", "ctypes", "importlib", "builtins", "__builtin__",
        "pty", "commands", "multiprocessing", "threading", "signal",
    }
    FORBIDDEN_CALLS = {
        "eval", "exec", "compile", "open", "__import__", "globals",
        "locals", "vars", "getattr", "setattr", "delattr", "input",
        "exit", "quit", "breakpoint", "memoryview",
    }
    FORBIDDEN_ATTRS = {"__globals__", "__builtins__", "__subclasses__",
                       "__class__", "__bases__", "__mro__", "__code__"}
    ALLOWED_MODULES = {
        "json", "re", "math", "datetime", "time", "random",
        "collections", "statistics", "decimal", "itertools",
        "functools", "typing", "dataclasses", "hashlib", "uuid",
    }

    @classmethod
    def audit(cls, code: str) -> Dict:
        risks, funcs = [], []
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return {"safe": False, "risks": [f"语法错误: {e}"], "functions": []}

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    mod = a.name.split(".")[0]
                    if mod in cls.FORBIDDEN_MODULES:
                        risks.append(f"禁止导入模块: {mod} (第{node.lineno}行)")
                    elif mod not in cls.ALLOWED_MODULES:
                        risks.append(f"未在白名单内的模块: {mod} (第{node.lineno}行)")
            elif isinstance(node, ast.ImportFrom):
                mod = (node.module or "").split(".")[0]
                if mod in cls.FORBIDDEN_MODULES:
                    risks.append(f"禁止导入模块: {mod} (第{node.lineno}行)")
                elif mod and mod not in cls.ALLOWED_MODULES:
                    risks.append(f"未在白名单内的模块: {mod} (第{node.lineno}行)")
            elif isinstance(node, ast.Call):
                name = ""
                if isinstance(node.func, ast.Name):
                    name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    name = node.func.attr
                if name in cls.FORBIDDEN_CALLS:
                    risks.append(f"禁止调用: {name}() (第{node.lineno}行)")
            elif isinstance(node, ast.Attribute):
                if node.attr in cls.FORBIDDEN_ATTRS:
                    risks.append(f"禁止访问属性: {node.attr} (第{node.lineno}行)")
            elif isinstance(node, ast.FunctionDef) and node.col_offset == 0:
                funcs.append({
                    "name": node.name,
                    "args": [a.arg for a in node.args.args],
                    "doc": ast.get_docstring(node) or "",
                })

        return {"safe": len(risks) == 0, "risks": risks, "functions": funcs}


# ============================================================
#  二、受限沙箱执行器
# ============================================================
class SafeSandbox:
    """受限命名空间执行 —— 只暴露白名单内置函数"""

    SAFE_BUILTINS = {
        "len": len, "str": str, "int": int, "float": float, "bool": bool,
        "list": list, "dict": dict, "tuple": tuple, "set": set,
        "sum": sum, "min": min, "max": max, "abs": abs, "round": round,
        "sorted": sorted, "reversed": reversed, "enumerate": enumerate,
        "zip": zip, "range": range, "print": print, "isinstance": isinstance,
        "any": any, "all": all, "map": map, "filter": filter, "hash": hash,
        "Exception": Exception, "ValueError": ValueError,
        "TypeError": TypeError, "KeyError": KeyError, "IndexError": IndexError,
        "True": True, "False": False, "None": None,
    }

    @classmethod
    def compile_and_load(cls, code: str, func_name: str) -> Callable:
        import json as _json
        import re as _re
        import math as _math
        import random as _random
        from datetime import datetime as _dt, timedelta as _td
        from collections import Counter as _Counter, defaultdict as _dd

        namespace = {
            "__builtins__": cls.SAFE_BUILTINS,
            "json": _json, "re": _re, "math": _math, "random": _random,
            "datetime": _dt, "timedelta": _td,
            "Counter": _Counter, "defaultdict": _dd,
        }
        compiled = compile(code, "<agent_generated>", "exec")
        exec(compiled, namespace)  # noqa: S102 - 已通过 AST 审查
        if func_name not in namespace:
            raise NameError(f"生成代码中未找到函数 {func_name}")
        fn = namespace[func_name]
        if not callable(fn):
            raise TypeError(f"{func_name} 不是可调用对象")
        return fn

    @classmethod
    def dry_run(cls, code: str, func_name: str, args: Dict, timeout: int = 10) -> Dict:
        t0 = time.time()
        try:
            fn = cls.compile_and_load(code, func_name)
            result = fn(**args)
            return {"ok": True, "result": result,
                    "elapsed": f"{time.time()-t0:.3f}s"}
        except Exception as e:  # noqa: BLE001
            return {"ok": False,
                    "error": f"{type(e).__name__}: {e}",
                    "traceback": traceback.format_exc()[-800:],
                    "elapsed": f"{time.time()-t0:.3f}s"}


# ============================================================
#  三、命令版本库（支持回滚）
# ============================================================
class CommandVersionStore:
    def __init__(self, db_path=None):
        self.db_path = db_path or settings.VERSIONS_DB
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init()

    def _init(self):
        with sqlite3.connect(self.db_path) as c:
            c.execute("""
                CREATE TABLE IF NOT EXISTS versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT, version INTEGER, code TEXT,
                    description TEXT, parameters TEXT,
                    status TEXT, note TEXT, created_at TEXT
                )""")

    def save(self, name, code, description, parameters, note="", status="active") -> int:
        with sqlite3.connect(self.db_path) as c:
            row = c.execute("SELECT MAX(version) FROM versions WHERE name=?",
                            (name,)).fetchone()
            ver = (row[0] or 0) + 1
            c.execute("""INSERT INTO versions
                (name,version,code,description,parameters,status,note,created_at)
                VALUES (?,?,?,?,?,?,?,?)""",
                (name, ver, code, description,
                 json.dumps(parameters, ensure_ascii=False),
                 status, note, datetime.now().isoformat()))
        return ver

    def get_latest(self, name) -> Optional[Dict]:
        with sqlite3.connect(self.db_path) as c:
            r = c.execute("""SELECT version,code,description,parameters,status,created_at
                FROM versions WHERE name=? ORDER BY version DESC LIMIT 1""",
                (name,)).fetchone()
        if not r:
            return None
        return {"version": r[0], "code": r[1], "description": r[2],
                "parameters": json.loads(r[3]), "status": r[4], "created_at": r[5]}

    def history(self, name) -> List[Dict]:
        with sqlite3.connect(self.db_path) as c:
            rows = c.execute("""SELECT version,status,note,created_at
                FROM versions WHERE name=? ORDER BY version DESC""",
                (name,)).fetchall()
        return [{"version": v, "status": s, "note": n, "at": t}
                for v, s, n, t in rows]

    def rollback(self, name, version) -> Optional[Dict]:
        with sqlite3.connect(self.db_path) as c:
            r = c.execute("""SELECT code,description,parameters FROM versions
                WHERE name=? AND version=?""", (name, version)).fetchone()
        if not r:
            return None
        self.save(name, r[0], r[1], json.loads(r[2]),
                  note=f"回滚至 v{version}", status="active")
        return {"code": r[0], "description": r[1], "parameters": json.loads(r[2])}


# ============================================================
#  四、命令构建引擎（店家用自然语言提需求）
# ============================================================
CODE_GEN_PROMPT = """你是电商运营系统的「命令代码生成器」。店家会用自然语言描述需求，你要生成一个可执行的 Python 命令函数。

【硬性规则】
1. 必须定义且只定义一个顶层函数，函数名用英文小写下划线风格
2. 函数必须有明确的类型注解和 docstring
3. 参数只能使用这些类型：str / int / float / bool / list / dict
4. 只允许导入这些模块：json, re, math, datetime, time, random, collections, statistics
5. 禁止使用 os, sys, subprocess, eval, exec, open, __import__ 等
6. 函数必须 return 一个 dict（便于前端展示）
7. 不要写 if __name__ == "__main__"，不要写测试代码
8. 数据来源：如果需要店铺数据，通过参数传入，不要硬编码
9. 禁止编造虚假 API 调用，如果只是逻辑计算就直接算

【必须的输出格式】严格输出 JSON，不要任何额外文字：
{
  "function_name": "函数名",
  "description": "给AI看的功能描述（中文，一句话说清用途）",
  "parameters": {
    "type": "object",
    "properties": {"参数名": {"type": "string", "description": "参数说明"}},
    "required": ["必填参数名"]
  },
  "code": "完整的Python代码字符串",
  "explanation": "用大白话给店家解释这个命令做了什么"
}"""


class CommandBuilder:
    def __init__(self, registry, version_store=None):
        self.registry = registry
        self.store = version_store or CommandVersionStore()
        self.audit_log: List[Dict] = []

    def build_from_requirement(self, requirement, sample_args=None,
                               auto_register=True) -> Dict:
        """主入口：一句话需求 → 可用的命令"""
        self._log("build_request", {"requirement": requirement})

        if not llm.has_key():
            return self._template_fallback(requirement)

        spec, err = llm.call_llm_json(
            [{"role": "system", "content": CODE_GEN_PROMPT},
             {"role": "user", "content": f"店家需求：{requirement}"}],
            max_tokens=1600)
        if err or not isinstance(spec, dict):
            return {"ok": False, "error": err or "代码生成失败"}

        name = str(spec.get("function_name", "")).strip()
        code = spec.get("code", "")
        desc = spec.get("description", "")
        params = spec.get("parameters", {"type": "object", "properties": {}, "required": []})
        if not name or not code:
            return {"ok": False, "error": "LLM 返回内容不完整", "raw": spec}

        audit = SecurityAuditor.audit(code)
        if not audit["safe"]:
            self._log("build_rejected", {"name": name, "risks": audit["risks"]})
            return {"ok": False, "stage": "安全审查未通过", "risks": audit["risks"],
                    "code": code,
                    "message": "生成的代码含风险操作，已拒绝注册。请换个说法或联系管理员。"}

        test_args = sample_args or self._auto_sample_args(params)
        dry = SafeSandbox.dry_run(code, name, test_args)
        if not dry["ok"]:
            fixed = self._self_fix(code, name, dry.get("error", ""), requirement)
            if fixed:
                code = fixed.get("code", code)
                audit2 = SecurityAuditor.audit(code)
                if audit2["safe"]:
                    dry = SafeSandbox.dry_run(code, name, test_args)
                    if not dry["ok"]:
                        return {"ok": False, "stage": "试运行失败",
                                "error": dry["error"], "code": code}
                else:
                    return {"ok": False, "stage": "修复后代码不安全",
                            "risks": audit2["risks"]}
            else:
                return {"ok": False, "stage": "试运行失败",
                        "error": dry["error"], "traceback": dry.get("traceback"),
                        "code": code}

        if auto_register:
            fn = SafeSandbox.compile_and_load(code, name)
            fn.__name__ = name
            version = self.store.save(name, code, desc, params,
                                      note=f"由需求生成：{requirement[:60]}",
                                      status="active")
            self.registry.register(name, desc, params, fn,
                                   builtin=False, created_by="agent", layer="agent")
            self._log("build_success", {"name": name, "version": version})
            return {"ok": True, "name": name, "version": version,
                    "description": desc, "code": code,
                    "explanation": spec.get("explanation", ""),
                    "preview": dry["result"],
                    "message": f"✅ 命令 [{name}] 已生成并上线，AI 现在可以调用它了"}
        return {"ok": True, "name": name, "code": code, "dry_run": dry}

    def _self_fix(self, code, name, error, requirement) -> Optional[Dict]:
        spec, err = llm.call_llm_json(
            [{"role": "system", "content": CODE_GEN_PROMPT},
             {"role": "user", "content":
                 f"之前的代码运行报错，请修复。\n\n原始需求：{requirement}\n\n"
                 f"出错代码：\n```python\n{code}\n```\n\n报错信息：{error}\n\n"
                 f"请输出修复后的完整 JSON（格式同上，函数名保持 {name}）"}],
            max_tokens=1600)
        return spec if isinstance(spec, dict) else None

    @staticmethod
    def _auto_sample_args(params: Dict) -> Dict:
        args = {}
        type_map = {"string": "test_value", "integer": 1, "number": 1.0,
                    "boolean": True, "array": [], "object": {}}
        for pname, pspec in params.get("properties", {}).items():
            args[pname] = type_map.get(pspec.get("type", "string"), "test")
        return args

    def _template_fallback(self, requirement) -> Dict:
        return {
            "ok": False,
            "offline": True,
            "message": "⚠️ 未配置 DeepSeek API Key，无法自动生成代码。\n"
                       "请在驾驶舱右上角「API 配置」填入 Key 后重试。\n\n"
                       f"你的需求已记录：{requirement}",
        }

    def _log(self, action, data):
        self.audit_log.append({"action": action, "data": data,
                               "at": datetime.now().isoformat()})


# ============================================================
#  五、命令进化引擎
# ============================================================
EVOLVE_PROMPT = """你是电商运营系统的「命令代码进化器」。

店家会提供一个【现有命令代码】和一个【改进需求】，你要输出改进后的完整代码。

【硬性规则】
1. 保持原函数的名称和主要参数不变（除非店家明确要求改）
2. 只做店家要求的改进，不要擅自大改其他逻辑
3. 遵守同样的安全限制：禁止 os/sys/subprocess/eval/exec/open
4. 只允许导入 json, re, math, datetime, time, random, collections, statistics
5. 函数必须 return dict

【输出格式】严格输出 JSON：
{
  "code": "改进后的完整Python代码",
  "description": "更新后的功能描述",
  "parameters": {"type":"object","properties":{},"required":[]},
  "changelog": "用大白话说明改了什么",
  "breaking": false
}"""


class CommandEvolver:
    def __init__(self, registry, version_store=None):
        self.registry = registry
        self.store = version_store or CommandVersionStore()

    def evolve(self, name, requirement, sample_args=None) -> Dict:
        current = self.store.get_latest(name)
        if not current:
            return {"ok": False, "error": f"命令 [{name}] 不存在或没有代码版本记录"}
        if not llm.has_key():
            return {"ok": False, "offline": True,
                    "message": "⚠️ 未配置 API Key，无法自动改写代码"}

        spec, err = llm.call_llm_json(
            [{"role": "system", "content": EVOLVE_PROMPT},
             {"role": "user", "content":
                 f"【现有命令名】{name}\n"
                 f"【现有代码】\n```python\n{current['code']}\n```\n\n"
                 f"【改进需求】{requirement}"}],
            max_tokens=1600)
        if err or not isinstance(spec, dict):
            return {"ok": False, "error": err or "改写失败"}

        code = spec.get("code", "")
        params = spec.get("parameters", current["parameters"])
        audit = SecurityAuditor.audit(code)
        if not audit["safe"]:
            return {"ok": False, "stage": "安全审查未通过", "risks": audit["risks"]}

        test_args = sample_args or CommandBuilder._auto_sample_args(params)
        dry = SafeSandbox.dry_run(code, name, test_args)
        if not dry["ok"]:
            return {"ok": False, "stage": "试运行失败",
                    "error": dry["error"], "code": code}

        fn = SafeSandbox.compile_and_load(code, name)
        fn.__name__ = name
        version = self.store.save(name, code,
                                  spec.get("description", current["description"]),
                                  params, note=f"进化：{requirement[:60]}",
                                  status="active")
        self.registry.update(name, description=spec.get("description"),
                             parameters=params)
        self.registry._handlers[name] = fn
        return {"ok": True, "name": name, "version": version,
                "changelog": spec.get("changelog", ""),
                "preview": dry["result"],
                "breaking": spec.get("breaking", False),
                "message": f"✅ 命令 [{name}] 已升级到 v{version}"}

    def rollback(self, name, version) -> Dict:
        res = self.store.rollback(name, version)
        if not res:
            return {"ok": False, "error": f"版本 v{version} 不存在"}
        fn = SafeSandbox.compile_and_load(res["code"], name)
        fn.__name__ = name
        self.registry._handlers[name] = fn
        self.registry.update(name, description=res["description"],
                             parameters=res["parameters"])
        return {"ok": True, "message": f"✅ 命令 [{name}] 已回滚到 v{version}"}

    def history(self, name) -> Dict:
        return {"name": name, "versions": self.store.history(name)}


# ============================================================
#  六、自愈引擎（命令报错时自动修复）
# ============================================================
class SelfHealer:
    def __init__(self, registry, evolver):
        self.registry = registry
        self.evolver = evolver
        self.heal_log: List[Dict] = []

    def handle_failure(self, name, args, error) -> Dict:
        if not llm.has_key():
            return {"healed": False, "reason": "离线模式无法自愈"}
        self.heal_log.append({"name": name, "error": error,
                              "at": datetime.now().isoformat()})
        req = (f"这个命令执行时出错了，请修复这个 bug，保持功能不变。\n"
               f"调用参数：{json.dumps(args, ensure_ascii=False)}\n"
               f"报错信息：{error}\n"
               f"请确保修复后同样的参数能正常返回结果。")
        result = self.evolver.evolve(name, req, sample_args=args)
        if result.get("ok"):
            return {"healed": True, "version": result["version"],
                    "message": f"🔧 命令 [{name}] 已自动修复并升级到 v{result['version']}"}
        return {"healed": False, "reason": result.get("error", "修复失败")}
