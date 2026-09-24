# -*- coding: utf-8 -*-
"""运营中心 API 路由：报表 / 体检 / ROI / 图库 / 命令工厂 / 优化方案 / 数据接入 / 实时监控"""
import os
import urllib.parse

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

from .ops import engine

router = APIRouter(prefix="/api/ops", tags=["运营中心"])

# 启动即初始化：生成演示数据 + 注册内置命令
engine.gen_demo_data()
engine.register_builtin_commands()


# ---------------- 总览 / 报表 ----------------
@router.get("/overview")
def ops_overview():
    return engine.overview()


@router.get("/report")
def ops_report(period: str = "day", date: str = ""):
    return engine.report(period, date)


@router.post("/report/refresh")
def ops_report_refresh(period: str = "day", date: str = ""):
    """经营报表「一键更新数据」：立即跑一轮 CDP 采集并重算报表。"""
    return engine.refresh_report(period, date)


@router.get("/refunds")
def ops_refunds():
    return engine.refunds()


@router.get("/health")
def ops_health():
    return engine.health()


@router.get("/optimization")
def ops_optimization():
    return engine.optimization()


# ---------------- ROI ----------------
@router.get("/roi")
def ops_roi():
    return engine.roi_summary()


class ReallocateIn(BaseModel):
    daily_budget: float = 5000.0


@router.post("/roi/reallocate")
def ops_reallocate(body: ReallocateIn):
    return engine.reallocate(body.daily_budget)


# ---------------- 参考图库 ----------------
@router.get("/images")
def ops_images(category: str = "", platform: str = ""):
    return engine.images(category, platform)


@router.get("/images/file/{name}")
def ops_image_file(name: str):
    """图库图片访问（仅限库内文件名，防目录穿越）"""
    from .ops import settings
    if "/" in name or "\\" in name or ".." in name:
        return {"error": "非法文件名"}
    path = os.path.join(settings.REFERENCE_IMAGES_DIR, name)
    if not os.path.exists(path):
        return {"error": "图片不存在"}
    return FileResponse(path)


class CrawlIn(BaseModel):
    platform: str = "taobao"
    category: str = ""
    keyword: str = ""
    limit: int = 6


@router.post("/images/crawl")
def ops_images_crawl(body: CrawlIn):
    return engine.crawl_images(body.platform, body.category, body.keyword, body.limit)


# ---------------- 命令工厂 ----------------
@router.get("/commands")
def ops_commands():
    return {"commands": engine.commands()}


@router.get("/commands/{name}")
def ops_command_detail(name: str, history: bool = False):
    return engine.command_detail(name, history)


class ExecuteIn(BaseModel):
    name: str
    args: dict = {}


@router.post("/commands/execute")
def ops_command_execute(body: ExecuteIn):
    return engine.execute_command(body.name, body.args)


class CreateIn(BaseModel):
    requirement: str
    sample_args: str = ""


@router.post("/commands/create")
def ops_command_create(body: CreateIn):
    return engine.create_command(body.requirement, body.sample_args)


class EvolveIn(BaseModel):
    name: str
    requirement: str


@router.post("/commands/evolve")
def ops_command_evolve(body: EvolveIn):
    return engine.evolve_command(body.name, body.requirement)


class RollbackIn(BaseModel):
    name: str
    version: int


@router.post("/commands/rollback")
def ops_command_rollback(body: RollbackIn):
    return engine.rollback_command(body.name, body.version)


class DeleteIn(BaseModel):
    name: str


@router.post("/commands/delete")
def ops_command_delete(body: DeleteIn):
    return engine.delete_command(body.name)


@router.get("/forge/status")
def ops_forge_status():
    return engine.forge_status()


# ---------------- 数据接入 ----------------
@router.get("/data/source")
def ops_data_source():
    return engine.data_status()


@router.get("/data/links")
def ops_data_links():
    return engine.links_table()


@router.get("/data/overview-source")
def ops_overview_source():
    """交易数据页(stores_data)同步的店铺级概况：省份交易分布 + 月份完成度"""
    return engine.overview_source()


@router.get("/data/daily")
def ops_data_daily():
    """交易数据页顶部「交易概况」卡的商店级权威日统计（按日期倒序）"""
    return engine.daily_source()


@router.get("/data/periods")
def ops_data_periods():
    """自动点击「实时/昨日/7日/30日」抓取的多周期交易概况（各维度独立）"""
    return engine.periods_source()


@router.post("/live/trigger-periods")
def ops_live_trigger_periods():
    """手动立即执行一轮多周期交易数据采集（无需等 30 分钟定时）"""
    return {"ok": True, "data": engine.trigger_periods()}


@router.get("/reconcile")
def ops_reconcile():
    """严格对账：权威日统计 vs 订单明细逐日比对，偏差超阈值即告警"""
    return engine.reconcile_report()


@router.get("/live/status")
def ops_live_status():
    """实时同步状态（是否跟随平台、最近采样）"""
    return engine.live_status()


@router.post("/live/start")
def ops_live_start(interval: int = 1800):
    from . import live
    return {"ok": True, "data": live.control("start", interval)}


@router.post("/live/stop")
def ops_live_stop():
    from . import live
    return {"ok": True, "data": live.control("stop")}


@router.get("/data/template")
def ops_data_template(kind: str = "orders"):
    return PlainTextResponse(engine.template(kind),
                             media_type="text/plain; charset=utf-8")


@router.post("/data/import/orders")
async def ops_import_orders(request: Request):
    raw = await request.body()
    filename = urllib.parse.unquote(request.headers.get("X-Filename", "订单报表.csv"))
    return engine.import_orders(raw, filename)


@router.post("/data/import/links")
async def ops_import_links(request: Request):
    raw = await request.body()
    filename = urllib.parse.unquote(request.headers.get("X-Filename", "推广报表.csv"))
    return engine.import_links(raw, filename)


class SnapshotIn(BaseModel):
    rows: list = []


@router.post("/data/snapshot")
def ops_data_snapshot(body: SnapshotIn):
    return engine.add_snapshot(body.rows)


class SyncIn(BaseModel):
    use_current: bool = True
    page_url: str = ""


@router.post("/data/sync")
def ops_data_sync(body: SyncIn):
    return engine.sync_ops_data(body.use_current, body.page_url)


@router.post("/data/clear")
def ops_data_clear():
    return engine.clear_real()


# ---------------- 实时监控 ----------------
@router.get("/monitor/status")
def ops_monitor_status():
    return engine.monitor_status()


class MonitorStartIn(BaseModel):
    interval: int = 60


@router.post("/monitor/start")
def ops_monitor_start(body: MonitorStartIn):
    return engine.monitor_start(body.interval)


@router.post("/monitor/stop")
def ops_monitor_stop():
    return engine.monitor_stop()


@router.post("/monitor/run")
def ops_monitor_run():
    return engine.monitor_run_now()


@router.get("/monitor/alerts")
def ops_monitor_alerts(limit: int = 50, level: str = ""):
    return engine.monitor_alerts(limit, level)
