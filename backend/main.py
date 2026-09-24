# -*- coding: utf-8 -*-
"""智客服 · AI 电商客服 Agent 平台 —— 本地驾驶舱后端

职责：
- 管理自动化引擎子进程（启动/停止）
- 暴露实时事件流 / 历史回放 / 运行统计
- 保存 DeepSeek Key 配置
- 托管 Vue 构建产物（驾驶舱界面）
"""
import os
import sys
import threading

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import agentctl, paths, memory
from .engine import llm
from .ops_api import router as ops_router

app = FastAPI(title="智客服 · AI 电商客服 Agent 平台", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ops_router)

FRONTEND_DIR = os.path.join(paths.resource_root(), "frontend", "dist")  # Vue 构建产物（优先）
LEGACY_DIR = os.path.join(paths.resource_root(), "legacy")              # 旧 HTML 单页（降级）


def _static_root():
    """选择前端静态根：Vue dist 优先，缺失时回退 legacy"""
    for d in (FRONTEND_DIR, LEGACY_DIR):
        if os.path.exists(os.path.join(d, "index.html")):
            return d
    return None


# ---------------- 自动化引擎控制 ----------------

class AgentStartIn(BaseModel):
    interval: int = 30
    dry: bool = False


@app.post("/api/agent/start")
def agent_start(body: AgentStartIn):
    ok, msg = agentctl.start(body.interval, body.dry)
    return {"ok": ok, "message": msg}


@app.post("/api/agent/stop")
def agent_stop():
    ok, msg = agentctl.stop()
    return {"ok": ok, "message": msg}


@app.get("/api/agent/status")
def agent_status():
    return agentctl.status()


@app.get("/api/agent/events")
def agent_events(after: int = 0):
    cursor, evs = agentctl.events(after)
    return {"cursor": cursor, "events": evs}


@app.get("/api/agent/replay")
def agent_replay(limit: int = 200):
    return {"events": agentctl.replay(limit)}


# ---------------- 配置（DeepSeek Key 等） ----------------

@app.get("/api/config")
def get_config():
    """返回运行配置（不含 key 明文）"""
    cfg = llm.load_config()
    return {
        "store_name": cfg.get("store_name", ""),
        "model": cfg.get("deepseek_model", "deepseek-chat"),
        "llm_ready": llm.has_key(cfg),
        "enable_llm": cfg.get("enable_llm", True),
    }


@app.post("/api/config/key")
def set_key(body: dict):
    """保存 DeepSeek API key（本地 config.json，不上传 GitHub）"""
    key = str(body.get("deepseek_api_key", "")).strip()
    cfg = llm.load_config()
    cfg["deepseek_api_key"] = key
    llm.save_config(cfg)
    return {"ok": True, "llm_ready": bool(key)}


@app.get("/api/health")
def health():
    return {"ok": True, "agent_running": agentctl.running()}


# ---------------- 记忆库（历史问答复用） ----------------

@app.get("/api/memory/stats")
def memory_stats():
    return memory.stats()


@app.get("/api/memory/list")
def memory_list(query: str = "", limit: int = 100):
    return {"items": memory.all_items(query, limit)}


@app.post("/api/memory/learn")
def memory_learn():
    """扫描历史回复记录（sessions.json + agent_events.jsonl）学习问答对"""
    return {"ok": True, "learned": memory.learn_from_sources()}


@app.post("/api/memory/toggle")
def memory_toggle(body: dict):
    enabled = body.get("enabled", True)
    return memory.set_enabled(bool(enabled))


@app.post("/api/memory/remove")
def memory_remove(body: dict):
    return memory.remove(str(body.get("id", "")))


@app.get("/api/memory/test")
def memory_test(text: str):
    return {"hits": memory.test(text)}


# ---------------- 记忆库 · 一键同步客服记录（CDP 逐一遍历） ----------------
# 与「学习历史记录」不同：那只是扫描本地已存的 sessions/agent_events；
# 这里会真正通过 CDP 驱动客服工作台，滚动加载并逐一打开每个历史会话，
# 读取完整聊天，把「客户问题→客服回复」问答对写入会话库 + 记忆库。
# 解决「很多客服没自动同步」——不再只看当前面板可见会话，而是全量遍历。

_keeper_mod = None
_keeper_lock = threading.Lock()


def _load_keeper():
    """惰性加载 agent 目录的 auto_keeper 模块（main 进程内复用同一个实例）。"""
    global _keeper_mod
    with _keeper_lock:
        if _keeper_mod is not None:
            return _keeper_mod
        d = os.path.join(paths.resource_root(), "agent")
        if d not in sys.path:
            sys.path.insert(0, d)
        try:
            import auto_keeper  # noqa: E402
            _keeper_mod = auto_keeper
        except Exception:
            _keeper_mod = None
        return _keeper_mod


def _sync_error_state(msg):
    return {"busy": False, "done": True, "start": None, "end": None,
            "total": 0, "scanned": 0, "learned": 0, "skipped": 0,
            "errored": 1, "pairs": 0, "last": "", "message": msg}


@app.post("/api/memory/sync")
def memory_sync():
    """启动后台线程：CDP 逐一遍历全部客服会话 → 写入会话库 + 记忆库。"""
    ak = _load_keeper()
    if ak is None:
        return _sync_error_state("无法加载客服模块，请确认程序完整")
    if ak.SYNC_STATE.get("busy"):
        return {"ok": False, "message": "同步已在运行中", "state": ak.SYNC_STATE}

    def _worker():
        try:
            ak.run_sync(400)
        except Exception as e:
            ak.SYNC_STATE.update(busy=False, done=True,
                                 message="同步异常：" + str(e)[:160])

    threading.Thread(target=_worker, daemon=True).start()
    return {"ok": True, "message": "已开始同步", "state": ak.SYNC_STATE}


@app.get("/api/memory/sync/status")
def memory_sync_status():
    """轮询同步进度。"""
    ak = _load_keeper()
    if ak is None:
        return _sync_error_state("无法加载客服模块")
    return ak.SYNC_STATE


# ---------------- 前端静态托管（Vue dist 优先，legacy 兜底） ----------------

@app.get("/")
def index():
    root = _static_root()
    if root:
        return FileResponse(os.path.join(root, "index.html"))
    return JSONResponse({
        "message": "「智客服」后端已运行 ✓（前端页面待构建：cd frontend && npm install && npm run build）",
        "api": ["POST /api/agent/start", "POST /api/agent/stop", "GET /api/agent/status",
                "GET /api/agent/events", "GET /api/agent/replay", "GET /api/config"],
    })


_root = _static_root()
if _root:
    app.mount("/assets", StaticFiles(directory=os.path.join(_root, "assets")), name="assets")
