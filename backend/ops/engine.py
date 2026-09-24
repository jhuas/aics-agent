# -*- coding: utf-8 -*-
"""运营自动化引擎装配层

- 模块单例：ROI 优化器 / 主图采集器 / 数据分析 / 优化方案 / 命令工厂
- 演示数据：本地造数（订单 + 投放计划），解压即演示
- 内置命令注册：可被 AI 与前端驾驶舱直接调用
- 客服反哺：客服自动化会话中的「退款诉求」事件 → 运营退款分析输入
"""
import json
import random
from datetime import datetime, timedelta

from .. import agentctl
from . import settings, store
from .analytics import OperationsAnalytics, OptimizationAdvisor, Order
from .command_forge import (CommandBuilder, CommandEvolver,
                            CommandVersionStore, SelfHealer)
from .image_crawler import ImageReferenceCrawler
from .monitor import ops_monitor
from .pdd_ops_crawler import sync as crawler_sync, probe as crawler_probe
from .registry import CommandRegistry
from .roi_monitor import AdPlan, ROIOptimizer

# ---------------- 单例 ----------------
version_store = CommandVersionStore()
registry = CommandRegistry(version_store=version_store)
roi_opt = ROIOptimizer(settings)
crawler = ImageReferenceCrawler()
analytics = OperationsAnalytics(settings)
advisor = OptimizationAdvisor(settings)

builder = CommandBuilder(registry, version_store)
evolver = CommandEvolver(registry, version_store)
healer = SelfHealer(registry, evolver)
registry.healer = healer
FORGE = {"builder": builder, "evolver": evolver, "healer": healer}

# ---------------- 演示数据 ----------------
DEMO_ORDERS: list = []
DEMO_PLANS: list = []


def gen_demo_data():
    global DEMO_ORDERS, DEMO_PLANS
    if DEMO_ORDERS:
        return
    reasons = ["尺码不符", "质量问题", "不喜欢", "物流太慢", "与描述不符",
               "7天无理由", "色差", "发错货"]
    channels = ["自然流量", "付费广告", "直播", "达人"]
    today = datetime.now()
    for i in range(400):
        d = today - timedelta(days=random.randint(0, 400))
        refunded = random.random() < 0.07
        DEMO_ORDERS.append(Order(
            order_id=f"ORD{10000 + i}",
            date=d.strftime("%Y-%m-%d"),
            amount=round(random.uniform(30, 500), 2),
            quantity=random.randint(1, 3),
            buyer_id=f"U{random.randint(1, 300)}",
            product_id=f"P{random.randint(1, 20)}",
            refunded=refunded,
            refund_amount=round(random.uniform(30, 300), 2) if refunded else 0,
            refund_reason=random.choice(reasons) if refunded else "",
            refund_days_after=random.randint(1, 15) if refunded else 0,
            channel=random.choice(channels),
            is_new_buyer=random.random() < 0.6,
        ))
    # 保证今日/昨日有演示订单，日报与环比不空
    for offset, n in ((0, 12), (1, 8)):
        d = today - timedelta(days=offset)
        for j in range(n):
            refunded = random.random() < 0.07
            DEMO_ORDERS.append(Order(
                order_id=f"ORD{20000 + offset * 100 + j}",
                date=d.strftime("%Y-%m-%d"),
                amount=round(random.uniform(40, 480), 2),
                quantity=random.randint(1, 3),
                buyer_id=f"U{random.randint(1, 300)}",
                product_id=f"P{random.randint(1, 20)}",
                refunded=refunded,
                refund_amount=round(random.uniform(30, 300), 2) if refunded else 0,
                refund_reason=random.choice(reasons) if refunded else "",
                refund_days_after=random.randint(1, 15) if refunded else 0,
                channel=random.choice(channels),
                is_new_buyer=random.random() < 0.6,
            ))
    for i in range(5):
        cost = round(random.uniform(500, 3000), 2)
        DEMO_PLANS.append(AdPlan(
            plan_id=f"PLAN{i + 1}", name=f"爆款计划{i + 1}",
            cost=cost, revenue=round(cost * random.uniform(1.0, 6.0), 2),
            orders=random.randint(10, 120), clicks=random.randint(200, 2000),
            impressions=random.randint(5000, 50000),
            budget=round(cost * 1.2, 2), price=round(random.uniform(50, 300), 2),
        ))


# ---------------- 客服 → 运营 反哺 ----------------
def refund_input_orders():
    """运营退款分析输入：只使用订单源本身（真实订单优先，否则演示订单），
    绝不混入客服诉求伪造单——客服事件仅含「退款诉求」标记、无真实订单金额，
    不能再编造退款金额污染退款统计。"""
    return orders_source()


# ---------------- 真实数据接入（真实优先、演示兜底） ----------------
def _real_connected():
    """是否已接入真实运营数据（订单 / 商品链接 / 交易数据页权威日统计任一非空）。
    daily 存在即视为真实接入——即便无订单明细，也绝不能回退演示随机数冒充。"""
    return store.has_real() or bool(store.daily_map())


def orders_source():
    """订单源：真实订单非空用真实；已接入真实数据（如 daily）但无订单明细时返回空，
    绝不回退演示随机数冒充真实退款/成交统计。"""
    real = store.real_orders()
    if real:
        return real
    return [] if _real_connected() else DEMO_ORDERS


def plans_source(days=None):
    """投放计划源：真实商品链接聚合（可限定最近 N 天）；已接入真实数据但无投放计划时
    返回空，绝不回退演示随机计划。"""
    real = store.real_plan_agg(days)
    if real:
        return real
    return [] if _real_connected() else DEMO_PLANS


def data_mode():
    """当前数据口径：real | demo（daily 权威日统计存在即视为真实接入）"""
    return "real" if _real_connected() else "demo"


def data_status():
    """数据源状态 + 连通性探测（供「数据接入」页签）"""
    st = store.source_status()
    st["mode"] = data_mode()
    if st["mode"] == "real" and st.get("说明") and "演示" in st["说明"]:
        st["说明"] = "已接入真实运营数据（订单 / 商品链接 / 交易数据页权威日统计），运营中心自动切换为真实口径"
    st["probe"] = crawler_probe()
    return st


def overview_source():
    """交易数据页同步的店铺级概况（省份分布 + 月份完成度）"""
    return store.get_overview()


def daily_source():
    """交易数据页「交易概况」卡的商店级权威日统计（按日期倒序）"""
    return store.get_daily()


def periods_source():
    """自动点击「实时/昨日/7日/30日」抓取的多周期交易概况（各维度独立，不混淆单日口径）"""
    return store.get_periods()


def trigger_periods():
    """手动立即执行一轮多周期交易数据采集（无需等定时），返回采集结果。"""
    from . import live
    return live.trigger_periods()


def live_status():
    """实时同步状态 + 最近一次采样时间（用于驾驶舱展示是否紧跟平台）"""
    from . import live
    return {"running": live.running(),
            "interval": live.interval(),
            "last": live.last_result(),
            "last_sync": store.last_live_sync()}


def reconcile_report():
    """严格对账：权威日统计 vs 订单明细逐日比对，偏差超阈值即告警"""
    from . import reconcile
    return reconcile.reconcile()


# 交易数据页权威日统计字段 -> 日报中文指标（有则优先覆盖订单聚合值）
_DAILY_METRIC_KEY = {
    "revenue": "成交额",
    "orders": "订单数",
    "customer_unit_price": "客单价",
    "buyers": "成交买家数",
    "conversion_rate": "成交转化率",
}


def _apply_daily(rpt, date_str):
    """用交易数据页「交易概况」卡的权威日统计覆盖日报「今日/昨日」口径。
    仅在存在可用的权威日统计时介入；否则保持订单聚合口径原样。"""
    if not date_str:
        return
    dmap = store.daily_map()
    cur = dmap.get(date_str) or {}
    if not any(cur.get(k) is not None for k in _DAILY_METRIC_KEY):
        return
    idx = rpt.setdefault("指标", {})
    for k, cn in _DAILY_METRIC_KEY.items():
        if cur.get(k) is not None:
            idx[cn] = cur[k]
    idx["数据来源"] = cur.get("source", "交易数据页")
    try:
        prev_date = (datetime.strptime(date_str, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    except Exception:  # noqa: BLE001
        return
    prev = dmap.get(prev_date) or {}
    if not any(prev.get(k) is not None for k in _DAILY_METRIC_KEY):
        return
    for k, cn in _DAILY_METRIC_KEY.items():
        if prev.get(k) is not None:
            idx["昨日" + cn] = prev[k]
    cmp_ = rpt.setdefault("环比", {})
    for k, cn in _DAILY_METRIC_KEY.items():
        c, p = cur.get(k), prev.get(k)
        if c is not None and isinstance(p, (int, float)) and p:
            cmp_[cn] = f"{(c - p) / p:+.2%}"


def links_table():
    """商品链接日指标表（供前端表格展示）"""
    rows = []
    for pid, node in store.link_days().items():
        name = node["name"]
        days = sorted(node["days"].keys(), reverse=True)
        latest = [node["days"][d] for d in days[:7]]
        cost = sum(float(m.get("cost") or 0) for m in latest)
        revenue = sum(float(m.get("revenue") or 0) for m in latest)
        orders = sum(int(m.get("orders") or 0) for m in latest)
        clicks = sum(int(m.get("clicks") or 0) for m in latest)
        rows.append({
            "product_id": pid, "name": name,
            "day_count": len(node["days"]),
            "last_date": days[0] if days else "",
            "cost_7d": round(cost, 2), "revenue_7d": round(revenue, 2),
            "orders_7d": orders, "clicks_7d": clicks,
            "roi_7d": round(revenue / cost, 2) if cost else 0,
        })
    rows.sort(key=lambda r: -r["cost_7d"])
    return {"mode": data_mode(), "rows": rows}


def sync_ops_data(use_current=True, page_url=""):
    """CDP 同步商家后台数据 → 落库"""
    return crawler_sync(use_current=use_current, page_url=page_url)


def cs_feedback_stats():
    """客服反哺统计：最近转人工退款诉求次数"""
    n = 0
    try:
        evs = agentctl.replay(10000)
    except Exception:  # noqa: BLE001
        evs = []
    for e in evs:
        if e.get("t") == "human" and e.get("refund"):
            n += 1
    return {"客服退款诉求数": n, "反哺状态": "已接入事件流" if n else "暂无新事件"}


# ---------------- 内置命令注册 ----------------
def _p(**kw):
    """构造 parameters schema：_p(plan_id="string", limit="integer")"""
    props, req = {}, []
    for k, v in kw.items():
        if isinstance(v, tuple):
            props[k] = {"type": v[0], "description": v[1]}
            if len(v) > 2 and v[2]:
                req.append(k)
        else:
            props[k] = {"type": v}
    return {"type": "object", "properties": props, "required": req}


_EMPTY = {"type": "object", "properties": {}, "required": []}


def register_builtin_commands():
    def check_roi(plan_id: str = "", date_range: str = "today"):
        plans = [p for p in plans_source() if not plan_id or p.plan_id == plan_id]
        return {"数据口径": data_mode(),
                "大盘汇总": roi_opt.summary(plans),
                "逐条诊断": [roi_opt.diagnose(p) for p in plans]}

    def reallocate_budget(daily_budget: float = 5000.0):
        return roi_opt.reallocate(plans_source(), daily_budget)

    def crawl_product_images(platform: str, category: str, keyword: str, limit: int = 10):
        return crawler.crawl_category(platform, category, keyword, limit)

    def search_reference_images(category: str = "", platform: str = ""):
        res = crawler.search_library(category, platform)
        return {"命中": len(res), "图片": res[:50], "统计": crawler.stats()}

    def get_business_report(period: str = "day", date: str = ""):
        return report(period, date or "")

    def analyze_refunds():
        return analytics.refund_analysis(refund_input_orders())

    def shop_health_check():
        return analytics.shop_health_check(orders_source(), plans_source())

    def generate_optimization_plan():
        health = analytics.shop_health_check(orders_source(), plans_source())
        refund = analytics.refund_analysis(refund_input_orders())
        report = report("month")
        roi_sum = roi_opt.summary(plans_source())
        return {"方案": advisor.generate(health, refund, report, roi_sum),
                "反哺": cs_feedback_stats()}

    def sync_ops_data(use_current: bool = True, page_url: str = ""):
        return crawler_sync(use_current=use_current, page_url=page_url)

    def get_data_status():
        return data_status()

    def get_monitor_alerts(limit: int = 20, level: str = ""):
        return {"运行中": ops_monitor.running,
                "最近巡检": ops_monitor.last_summary,
                "告警": ops_monitor.alerts_view(limit, level)}

    def monitor_control(action: str = "start", interval: int = 60):
        if action == "stop":
            return ops_monitor.stop()
        return ops_monitor.start(interval)

    def get_links_table():
        return links_table()

    def add_command(name: str, description: str, handler_key: str,
                    params_desc: str = "无需参数"):
        presets = {
            "send_daily_report": lambda **kw: {"msg": f"日报已发送至商家: {json.dumps(kw, ensure_ascii=False)}"},
            "check_inventory": lambda **kw: {"msg": f"库存检查完成: {kw.get('sku', '全部')}"},
            "auto_reply_comment": lambda **kw: {"msg": f"已自动回复评论: {kw.get('content', '')}"},
            "custom_task": lambda **kw: {"msg": f"自定义任务已执行: {json.dumps(kw, ensure_ascii=False)}"},
        }
        fn = presets.get(handler_key, presets["custom_task"])
        fn.__name__ = name
        props = {"type": "object", "properties": {}, "required": []}
        if params_desc and params_desc != "无需参数":
            for seg in params_desc.split(","):
                if ":" in seg:
                    pname, ptype = seg.split(":", 1)
                    props["properties"][pname.strip()] = {"type": ptype.strip()}
        registry.register(name, description, props, fn, builtin=False,
                          created_by="operator", layer="manual")
        return {"ok": True, "name": name, "message": f"命令 [{name}] 已添加，AI 现在可以调用它了"}

    def create_command(requirement: str, sample_args: str = ""):
        args = {}
        if sample_args:
            try:
                args = json.loads(sample_args)
            except json.JSONDecodeError:
                pass
        return builder.build_from_requirement(requirement, args or None)

    def evolve_command(name: str, requirement: str):
        return evolver.evolve(name, requirement)

    def delete_command(name: str, confirm: bool = False):
        cmd = registry._schema.get(name)
        if not cmd:
            return {"ok": False, "message": f"命令 [{name}] 不存在"}
        if cmd.get("builtin"):
            return {"ok": False, "message": f"🚫 内置命令 [{name}] 受保护，不可删除"}
        if not confirm:
            return {"ok": False, "need_confirm": True,
                    "message": f"⚠️ 即将删除命令 [{name}]（{cmd['function']['description']}）。"
                               f"请确认后再执行，confirm=True"}
        ok = registry.unregister(name)
        return {"ok": ok, "message": f"命令 [{name}] 已删除" if ok else "删除失败"}

    def list_all_commands(include_builtin: bool = True):
        cmds = registry.list_commands(include_builtin)
        return {"总数": len(cmds),
                "按类型统计": {"内置": sum(1 for c in cmds if c["type"] == "内置"),
                            "Agent生成": sum(1 for c in cmds if c["type"] == "Agent生成"),
                            "店家手写": sum(1 for c in cmds if c["type"] == "店家手写")},
                "命令列表": cmds}

    def inspect_command(name: str, show_history: bool = False):
        cmd = registry._schema.get(name)
        if not cmd:
            return {"ok": False, "message": f"命令 [{name}] 不存在"}
        out = {"name": name, "description": cmd["function"]["description"],
               "type": cmd.get("layer", "builtin"),
               "parameters": cmd["function"]["parameters"]}
        latest = version_store.get_latest(name)
        if latest:
            out["current_version"] = latest["version"]
            out["code"] = latest["code"]
            out["updated_at"] = latest["created_at"]
        if show_history:
            out["version_history"] = version_store.history(name)
        return out

    def rollback_command(name: str, version: int):
        return evolver.rollback(name, version)

    def list_commands():
        return {"命令列表": registry.list_commands()}

    specs = [
        ("check_roi", "检查投产比(ROI)并给出预算调节建议，plan_id 为空则检查全部计划",
         _p(plan_id="string", date_range="string"), check_roi),
        ("reallocate_budget", "按 ROI 加权重新分配每日投放预算，把低效预算转给高效计划",
         _p(daily_budget="number"), reallocate_budget),
        ("crawl_product_images", "采集指定平台品类的商品主图，存入参考图库供商家参考",
         _p(platform="string", category="string", keyword="string", limit="integer"),
         crawl_product_images),
        ("search_reference_images", "在参考图库中按品类/平台检索已采集的主图",
         _p(category="string", platform="string"), search_reference_images),
        ("get_business_report", "生成经营数据报表，period 可选 day/week/month/year",
         _p(period="string", date="string"), get_business_report),
        ("analyze_refunds", "分析退款率与退款原因归因（含客服退款诉求反哺）",
         _EMPTY, analyze_refunds),
        ("shop_health_check", "店铺健康度五维体检打分（退款/客单/新客/投放/复购）",
         _EMPTY, shop_health_check),
        ("generate_optimization_plan", "综合体检/退款/报表生成可执行的店铺优化方案",
         _EMPTY, generate_optimization_plan),
        ("sync_ops_data", "CDP 同步商家后台经营数据入库（真实数据优先，无则自动打开数据页）",
         _p(use_current="boolean", page_url="string"), sync_ops_data),
        ("get_data_status", "查看数据源状态：真实/演示口径、导入记录、同步连通性",
         _EMPTY, get_data_status),
        ("get_links_table", "查看商品链接日指标表（花费/成交/订单/ROI）",
         _EMPTY, get_links_table),
        ("get_monitor_alerts", "查看实时监控告警（成本升成交降/ROI 亏损等），level 可选 warn/danger",
         _p(limit="integer", level="string"), get_monitor_alerts),
        ("monitor_control", "启停实时运营监控：action=start/stop，interval 为巡检秒数",
         _p(action="string", interval="integer"), monitor_control),
        ("add_command", "基于预置逻辑快速添加简单命令（复杂需求请用 create_command）",
         _p(name="string", description="string", handler_key="string",
            params_desc="string"), add_command),
        ("create_command", "【核心】店家描述业务需求，Agent 自动生成命令代码并上线",
         _p(requirement="string", sample_args="string"), create_command),
        ("evolve_command", "【核心】用自然语言改进现有命令，自动改写代码并升级版本",
         _p(name="string", requirement="string"), evolve_command),
        ("delete_command", "删除命令（内置命令受保护）。必须先确认再传 confirm=True",
         _p(name="string", confirm="boolean"), delete_command),
        ("list_all_commands", "列出所有命令，含内置/Agent生成/店家手写三类统计",
         _p(include_builtin="boolean"), list_all_commands),
        ("inspect_command", "查看某命令的代码、参数与版本历史",
         _p(name="string", show_history="boolean"), inspect_command),
        ("rollback_command", "把命令回滚到指定历史版本（改坏了用它救急）",
         _p(name="string", version="integer"), rollback_command),
        ("list_commands", "列出所有可用命令（简版）", _EMPTY, list_commands),
    ]
    for name, desc, params, fn in specs:
        registry.register(name, desc, params, fn, builtin=True, layer="builtin")


# ---------------- 驾驶舱 API 便捷封装 ----------------
def _daily_refund_brief():
    """从「交易数据-实时」权威日统计取今日退款概况（订单/退款单/金额）。
    无订单明细时供总览如实展示真实权威值，而非回退演示或留空。"""
    today = datetime.now().strftime("%Y-%m-%d")
    d = store.daily_map().get(today) or {}
    ords = d.get("orders")
    refund_orders = d.get("refund_orders")
    if not isinstance(ords, (int, float)) or ords == 0:
        return None
    rate = (int(refund_orders or 0) / ords) if refund_orders is not None else None
    return {"订单数": int(ords),
            "退款单数": int(refund_orders or 0),
            "退款率": f"{rate:.2%}" if rate is not None else None,
            "退款金额": round(float(d.get("refund_amount") or 0), 2)}


def overview():
    """运营总览指标卡"""
    rpt = report("day")
    orders = orders_source()
    has_orders = bool(orders)
    health = analytics.shop_health_check(orders, plans_source())
    roi = roi_opt.summary(plans_source())
    refund = analytics.refund_analysis(refund_input_orders())
    # 退款率卡：无订单明细时改用真实权威日统计，杜绝用演示随机数
    shown_refund = refund.get("总结") == "暂无退款数据"
    if shown_refund:
        db = _daily_refund_brief()
        if db:
            refund_rate = db.get("退款率") or "0%"
            refund_detail = f"权威日统计 · 退款单 {db['退款单数']}/{db['订单数']}"
        else:
            refund_rate = refund.get("退款率", "0%")
            refund_detail = "暂无订单明细，且今日无交易数据页权威日统计"
    else:
        refund_rate = refund.get("退款率", "0%")
        refund_detail = ""
    return {
        "数据口径": data_mode(),
        "今日": rpt["指标"],
        "环比": rpt["环比"],
        "健康度": {"总分": health["总分"], "等级": health["等级"],
                  "无明细": not has_orders and store.has_real()},
        "ROI": {"整体投产比": roi["整体投产比"], "总花费": roi["总花费"],
                "预警计划数": roi["预警计划数"]},
        "退款率": refund_rate,
        "退款明细": refund_detail,
        "客服反哺": cs_feedback_stats(),
        "监控": {"运行中": ops_monitor.running,
                "告警数": len(ops_monitor.alerts),
                "最近巡检": ops_monitor.last_summary},
        "生成时间": datetime.now().isoformat(),
    }


def report(period="day", date_str=""):
    """经营经营报表。经营成交类指标【只采纳「交易数据-实时」权威日统计】——
    严格执行"数据只能来源于在线平台"：本周期内无任何交易数据页权威日统计时，
    经营指标置空并标注「无在线数据」，绝不回退订单聚合或演示随机数冒充成交。
    订单明细仅用于退款归因维度（assist_refunds），不作为成交额来源。

    覆盖顺序：日统计加总(_apply_daily_period) → 平台权威周期聚合
    (_apply_platform_period)。周/月报与平台对不上的根因是日统计只覆盖
    程序运行以来的少数几天，加总必然偏小；因此当平台「周/月/实时/昨日」
    聚合的统计区间与请求周期吻合时，直接采用平台权威值。"""
    r = analytics.report(orders_source(), period, date_str or None)
    _apply_daily_period(r, period, date_str or None)
    _apply_platform_period(r, period, date_str or None)
    _mark_report_source(r)
    return r


def _iso_date(s):
    """'2026-09-01' → date；非法/空 → None"""
    try:
        return datetime.strptime(str(s or "")[:10], "%Y-%m-%d").date()
    except Exception:  # noqa: BLE001
        return None


def _apply_platform_period(rpt, period, date_str=None):
    """平台权威周期聚合覆盖：月报←「月」、周报←「周」、日报(今/昨)←「实时/昨日」。

    仅当该维度记录的「统计时间」区间与请求周期吻合时才采用（防拿错维度）：
      - day   ：range_start == 请求日；无区间信息时仅限今天←实时 / 昨天←昨日
      - week  ：range_start == 请求周周一；无区间信息时仅限本周
      - month ：range_start 落在请求月内；无区间信息时仅限本月
    区间不吻合或无数据 → 不动（保留日统计加总或「无在线数据」标注）。
    """
    pmap = store.periods_map()
    if not pmap:
        return
    base = date_str or datetime.now().strftime("%Y-%m-%d")
    d0 = _iso_date(base)
    if not d0:
        return
    today = datetime.now().date()

    if period == "day":
        if d0 == today:
            label = "实时"
        elif d0 == today - timedelta(days=1):
            label = "昨日"
        else:
            return
        rec = pmap.get(label)
        if not rec:
            return
        rs = _iso_date(rec.get("range_start"))
        if rs and rs != d0:
            return
    elif period == "week":
        rec = pmap.get("周")
        if not rec:
            return
        label = "周"
        wk_start = d0 - timedelta(days=d0.weekday())
        rs = _iso_date(rec.get("range_start"))
        if rs:
            if rs != wk_start:
                return
        elif wk_start != today - timedelta(days=today.weekday()):
            return
    elif period == "month":
        rec = pmap.get("月")
        if not rec:
            return
        label = "月"
        rs = _iso_date(rec.get("range_start"))
        if rs:
            if rs.strftime("%Y-%m") != d0.strftime("%Y-%m"):
                return
        elif d0.strftime("%Y-%m") != today.strftime("%Y-%m"):
            return
    else:
        return

    rev = rec.get("revenue")
    if rev is None:
        return
    ords = int(rec.get("orders") or 0)
    refund_orders = int(rec.get("refund_orders") or 0)
    idx = rpt.setdefault("指标", {})
    idx["成交额"] = round(float(rev), 2)
    idx["订单数"] = ords
    aov = rec.get("customer_unit_price")
    if aov is not None:
        idx["客单价"] = round(float(aov), 2)
    else:
        idx["客单价"] = round(float(rev) / ords, 2) if ords else 0
    idx["成交买家数"] = int(rec["buyers"]) if rec.get("buyers") is not None else None
    cr = rec.get("conversion_rate")
    idx["成交转化率"] = f"{float(cr):.2f}%" if cr is not None else None
    idx["退款金额"] = round(float(rec.get("refund_amount") or 0), 2)
    idx["退款单数"] = refund_orders
    idx["退款率"] = f"{refund_orders / ords:.2%}" if ords else "0.00%"

    # 环比优先采用平台官方「较前1月/较前1周 ↑x%」；无官方值则清空，
    # 避免用日统计加总的基数与平台权威值混算出不实环比。
    cmp_ = rpt.setdefault("环比", {})
    official = rec.get("cmp") or {}
    for cn in ("成交额", "订单数", "客单价"):
        if official.get(cn):
            cmp_[cn] = official[cn]
        elif cn in cmp_:
            del cmp_[cn]

    rng = ""
    rs, re_ = rec.get("range_start"), rec.get("range_end")
    if rs:
        rng = f"（统计 {str(rs)[5:]}~{str(re_ or rs)[5:]}）"
    idx["数据来源"] = f"交易数据-{label}·平台权威聚合{rng}"


def refresh_report(period="day", date_str=""):
    """「经营报表 · 一键更新数据」：立即跑一轮 CDP 采集（权威日统计 + 订单明细 +
    多周期交易数据）刷新本地仓库，再基于最新数据重算并返回报表。

    采集端已各自优雅降级（CDP 离线 / 未登录商家后台只丢本轮不报错），
    因此无论是否采到新数据都返回报表，前端可据「数据来源」与刷新摘要判断结果。"""
    from . import pdd_ops_crawler as _crawler
    daily = 0
    orders = 0
    per = None
    try:
        base = _crawler.live_refresh(orders_too=True)
        daily = int(base.get("daily_days") or 0)
        orders = int(base.get("orders") or 0)
    except Exception:  # noqa: BLE001
        pass
    try:
        per = _crawler.collect_trade_periods()
    except Exception:  # noqa: BLE001
        per = None
    rpt = report(period, date_str)
    src = (rpt.get("指标") or {}).get("数据来源") or ""
    return {
        "ok": True,
        "刷新": {
            "权威日统计天数": daily,
            "订单": orders,
            "多周期": per,
            "数据来源": src,
        },
        "report": rpt,
    }


def _mark_report_source(rpt):
    """为报表打上可追溯的数据来源。成交类指标严格取自「交易数据-实时」；
    若该周期无在线权威日统计，则明确标注「无在线数据」，杜绝把订单聚合或
    演示随机数当在线成交展示。"""
    idx = rpt.get("指标", {})
    if idx.get("数据来源"):
        return
    TOP = ("成交额", "订单数", "客单价", "成交买家数", "成交转化率", "退款金额", "退款单数", "退款率")
    if not any(idx.get(k) is not None for k in TOP):
        idx["数据来源"] = "无在线数据（交易数据-实时为空，未同步任何权威日统计）"
    elif store.has_real():
        idx["数据来源"] = "订单明细数据（未含交易数据页权威日统计，展示受限于线下/导入口径）"
    else:
        idx["数据来源"] = "演示数据（未接入真实订单，非真实成交）"


def _apply_daily_period(rpt, period, date_str=None):
    """用「交易数据-实时」权威日统计覆盖任意周期（日报/周报/月报/年报）。

    覆盖口径：
      - 成交额 / 订单数 / 退款金额 / 退款单数：周期内每天求和
      - 客单价 = 成交额 / 订单数
      - 成交转化率 = 周期内平均（有值的天）
      - 成交买家数 = 周期内每天之和
      - 数据来源统一标注「交易数据-实时」
    严格执行"数据只能来源于在线平台"：本周期/对比周期无任何权威日统计时，
    成交类指标清空(None)，绝不回退订单聚合或演示随机数冒充在线成交。
    """
    base = (date_str or datetime.now().strftime("%Y-%m-%d"))
    try:
        d0 = datetime.strptime(base, "%Y-%m-%d")
    except Exception:  # noqa: BLE001
        return
    if period == "day":
        start = end = d0
        prev_start = prev_end = d0 - timedelta(days=1)
    elif period == "week":
        start = d0 - timedelta(days=d0.weekday())
        end = start + timedelta(days=6)
        prev_start = start - timedelta(days=7)
        prev_end = start - timedelta(days=1)
    elif period == "month":
        start = d0.replace(day=1)
        end = d0.replace(day=_month_end(d0))
        prev_start = (start - timedelta(days=1)).replace(day=1)
        prev_end = prev_start.replace(day=_month_end(prev_start))
    elif period == "year":
        start = d0.replace(month=1, day=1)
        end = d0.replace(month=12, day=31)
        prev_start = start.replace(year=start.year - 1)
        prev_end = end.replace(year=end.year - 1)
    else:
        return

    dmap = store.daily_map()

    def _agg(s, e):
        days = [v for k, v in dmap.items()
                if s.strftime("%Y-%m-%d") <= k <= e.strftime("%Y-%m-%d")
                and any(v.get(f) is not None for f in _DAILY_METRIC_KEY)]
        if not days:
            return None
        rev = sum(float(v.get("revenue") or 0) for v in days)
        ords = sum(int(v.get("orders") or 0) for v in days)
        buyers = sum(int(v.get("buyers") or 0) for v in days)
        refund_amount = sum(float(v.get("refund_amount") or 0) for v in days)
        refund_orders = sum(int(v.get("refund_orders") or 0) for v in days)
        rates = []
        for v in days:
            cr = v.get("conversion_rate")
            if cr is None:
                continue
            try:
                crf = float(str(cr).rstrip("%"))
            except Exception:  # noqa: BLE001
                continue
            rates.append(crf)
        return {"rev": rev, "ords": ords, "buyers": buyers,
                "refund_amount": refund_amount, "refund_orders": refund_orders,
                "rate": (sum(rates) / len(rates)) if rates else None}

    TOP_KEYS = ("成交额", "订单数", "客单价", "成交买家数",
                "成交转化率", "退款金额", "退款单数", "退款率")

    def _clear_metrics(idx):
        for k in TOP_KEYS:
            idx[k] = None

    idx = rpt.setdefault("指标", {})

    cur = _agg(start, end)
    if not cur:
        # 本周期无在线权威日统计 → 清空成交类指标，标注无在线数据
        _clear_metrics(idx)
        cmp_ = rpt.setdefault("环比", {})
        for cn in ("成交额", "订单数", "客单价"):
            if cn in cmp_:
                del cmp_[cn]
        idx["数据来源"] = "无在线数据（交易数据-实时为空，未同步任何权威日统计）"
        return
    idx["成交额"] = round(cur["rev"], 2)
    idx["订单数"] = cur["ords"]
    idx["客单价"] = round(cur["rev"] / cur["ords"], 2) if cur["ords"] else 0
    idx["成交买家数"] = cur["buyers"]
    idx["退款金额"] = round(cur["refund_amount"], 2)
    idx["退款单数"] = cur["refund_orders"]
    if cur["ords"]:
        idx["退款率"] = f"{cur['refund_orders'] / cur['ords']:.2%}"
    else:
        idx["退款率"] = "0.00%"

    prev = _agg(prev_start, prev_end)
    cmp_ = rpt.setdefault("环比", {})
    if prev:
        prev_aov = prev["rev"] / prev["ords"] if prev["ords"] else 0
        cur_aov = cur["rev"] / cur["ords"] if cur["ords"] else 0
        for cn, c, p in (("成交额", cur["rev"], prev["rev"]),
                         ("订单数", cur["ords"], prev["ords"]),
                         ("客单价", cur_aov, prev_aov)):
            if p:
                cmp_[cn] = f"{(c - p) / p:+.2%}"
    idx["数据来源"] = "交易数据-实时"


def _month_end(d):
    """返回 d 所在月份的天数。"""
    if d.month == 12:
        return 31
    return (datetime(d.year, d.month + 1, 1) - timedelta(days=1)).day


def refunds():
    return analytics.refund_analysis(refund_input_orders())


def health():
    return analytics.shop_health_check(orders_source(), plans_source())


def roi_summary():
    plans = plans_source()
    return {"数据口径": data_mode(),
            "汇总": roi_opt.summary(plans),
            "逐条诊断": [roi_opt.diagnose(p) for p in plans],
            "计划": [p.to_dict() for p in plans]}


def reallocate(daily_budget=5000.0):
    return roi_opt.reallocate(plans_source(), daily_budget)


def images(category="", platform=""):
    return {"图片": crawler.search_library(category, platform),
            "统计": crawler.stats()}


def crawl_images(platform, category, keyword, limit=6):
    """采集主图：返回真实图片列表（不混入 error 项），错误提示单独放统计。"""
    _, _, errors = _split_results(
        crawler.crawl_category(platform, category, keyword, limit))
    return {"结果": [r for r in crawler.crawl_category(platform, category, keyword, limit)
                    if not r.get("error")], "统计": crawler.stats(), "提示": errors}


def _split_results(results):
    """把采集结果拆成 [真实图片, 演示图片, 错误提示]。"""
    imgs = [r for r in results if not r.get("error")]
    demos = [r for r in imgs if r.get("demo")]
    reals = [r for r in imgs if not r.get("demo")]
    errs = [r.get("error") for r in results if r.get("error")]
    return reals, demos, errs


def optimization():
    health_r = analytics.shop_health_check(orders_source(), plans_source())
    refund_r = analytics.refund_analysis(refund_input_orders())
    report_r = report("month")
    roi_r = roi_opt.summary(plans_source())
    return {"方案": advisor.generate(health_r, refund_r, report_r, roi_r),
            "输入": {"数据口径": data_mode(),
                    "体检分": health_r["总分"], "退款率": refund_r.get("退款率", "0%"),
                    "ROI": roi_r["整体投产比"], "客服反哺": cs_feedback_stats()}}


def commands():
    return registry.list_commands(include_builtin=True)


def command_detail(name, show_history=False):
    return inspect_command_public(name, show_history)


def inspect_command_public(name, show_history=False):
    cmd = registry._schema.get(name)
    if not cmd:
        return {"ok": False, "message": f"命令 [{name}] 不存在"}
    out = {"name": name, "description": cmd["function"]["description"],
           "type": cmd.get("layer", "builtin"),
           "parameters": cmd["function"]["parameters"]}
    latest = version_store.get_latest(name)
    if latest:
        out["current_version"] = latest["version"]
        out["code"] = latest["code"]
        out["updated_at"] = latest["created_at"]
    if show_history:
        out["version_history"] = version_store.history(name)
    return out


def execute_command(name, args):
    return registry.execute(name, args or {})


def create_command(requirement, sample_args=""):
    args = {}
    if sample_args:
        try:
            args = json.loads(sample_args)
        except json.JSONDecodeError:
            pass
    return builder.build_from_requirement(requirement, args or None)


def evolve_command(name, requirement):
    return evolver.evolve(name, requirement)


def rollback_command(name, version):
    return evolver.rollback(name, version)


def delete_command(name):
    cmd = registry._schema.get(name)
    if not cmd:
        return {"ok": False, "message": f"命令 [{name}] 不存在"}
    if cmd.get("builtin"):
        return {"ok": False, "message": f"🚫 内置命令 [{name}] 受保护，不可删除"}
    return {"ok": registry.unregister(name), "message": f"命令 [{name}] 已删除"}


def forge_status():
    return {"audit_log": builder.audit_log[-20:], "heal_log": healer.heal_log[-20:]}


# ---------------- 数据接入 & 实时监控（ops_api 透传） ----------------
def import_orders(raw, filename="订单报表.csv"):
    return store.import_orders_csv(raw, filename)


def import_links(raw, filename="推广报表.csv"):
    return store.import_links_csv(raw, filename)


def add_snapshot(rows):
    return store.add_snapshot(rows)


def clear_real():
    return store.clear_real_data()


def template(kind):
    return store.template(kind)


def monitor_start(interval=60):
    return ops_monitor.start(interval)


def monitor_stop():
    return ops_monitor.stop()


def monitor_status():
    return ops_monitor.status()


def monitor_run_now():
    """立即执行一轮巡检（不依赖线程间隔，演示/手动触发用）"""
    return ops_monitor.run_once()


def monitor_alerts(limit=50, level=""):
    return {"status": ops_monitor.status(),
            "history": ops_monitor.history_view(60),
            "alerts": ops_monitor.alerts_view(limit, level)}
