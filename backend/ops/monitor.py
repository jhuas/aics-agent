# -*- coding: utf-8 -*-
"""实时运营监控引擎：异常检测 + 规则建议 + LLM 解读

后台线程按间隔扫描数据（真实数据优先，演示兜底），每轮生成：
- 大盘快照（总花费/总成交/整体 ROI/告警数）
- 告警列表，三种核心异常：
    ① 推广成本上升 且 成交额下降  —— 用户核心场景（成本升·成交降）
    ② ROI 低于保本线 / 预警线      —— 亏损与利润承压
    ③ 退款率突增（可选，有订单数据时）
每条告警附带：规则建议（内置诊断）+ LLM 解读（有 API key 时，自然语言经营建议）

告警环形落盘 <data>/monitor_alerts.json，供前端「实时监控」页签与命令调用。
"""
import json
import os
import threading
import time
from datetime import datetime

from ..engine import llm
from . import settings, store
from .roi_monitor import AdPlan, ROIOptimizer

ALERTS_FILE = os.path.join(settings.data_dir(), "monitor_alerts.json")

LEVELS = {"info": "提示", "warn": "预警", "danger": "严重"}

_SEV = {"cost_up_revenue_down": "danger", "roi_loss": "danger",
        "roi_warning": "warn"}


class OperationMonitor:
    """实时监控单例：线程巡检 + 告警环形缓冲 + LLM 解读缓存"""

    def __init__(self, cfg):
        self.cfg = cfg
        self.optimizer = ROIOptimizer(cfg)
        self._thread = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.running = False
        self.interval = cfg.Monitor.INTERVAL
        self.alerts = []
        self.history = []
        self.last_run = None
        self.last_summary = None
        self._llm_cache = {}
        self._load()

    # ---------------- 生命周期 ----------------
    def start(self, interval=None):
        if self.running:
            return {"ok": True, "message": f"实时监控已在运行（每 {self.interval}s 巡检）"}
        if interval:
            self.interval = max(10, int(interval))
        self.running = True
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return {"ok": True, "message": f"实时监控已启动：每 {self.interval} 秒巡检一次运营数据"}

    def stop(self):
        self.running = False
        self._stop.set()
        return {"ok": True, "message": "实时监控已停止（已生成的历史告警仍保留）"}

    def status(self):
        return {
            "running": self.running,
            "interval": self.interval,
            "last_run": self.last_run,
            "alert_count": len(self.alerts),
            "last_summary": self.last_summary,
        }

    def _loop(self):
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception:  # noqa: BLE001 —— 巡检绝不能被单轮异常打断
                pass
            self._stop.wait(self.interval)

    # ---------------- 单轮巡检 ----------------
    def run_once(self):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        links = store.link_days()
        plans = store.real_plan_agg() if links else []
        alerts = []
        for p in plans:
            series = (links.get(str(p.plan_id)) or {}).get("days", {})
            for a in self._check_plan(p, series):
                alerts.append(a)

        cost = sum(p.cost for p in plans)
        revenue = sum(p.revenue for p in plans)
        summary = {
            "ts": now,
            "mode": "real" if (links or store.daily_map()) else "demo",
            "links": len(plans),
            "total_cost": round(cost, 2),
            "total_revenue": round(revenue, 2),
            "roi": round(revenue / cost, 2) if cost else 0,
            "alerts": len(alerts),
        }
        self.last_run = now
        self.last_summary = summary

        with self._lock:
            self.history.append(summary)
            self.history = self.history[-120:]
            for a in alerts:
                self.alerts.insert(0, a)
            self.alerts = self.alerts[: self.cfg.Monitor.MAX_ALERTS]
        self._save()
        return {"summary": summary, "alerts": alerts}

    # ---------------- 异常检测 ----------------
    def _check_plan(self, p: AdPlan, series: dict):
        """一条链接一轮检测 → 告警列表（规则诊断，附建议）"""
        T = self.cfg.Threshold
        alerts = []

        # ① ROI 亏损 / 预警（聚合口径）
        if p.roi > 0 and p.roi < p.breakeven_roi:
            alerts.append(self._make("roi_loss", p, series,
                                     f"投产比 {p.roi} 低于保本线 {p.breakeven_roi}，处于亏损区间",
                                     f"净亏约 ¥{abs(p.net_profit):.0f}"))
        elif p.roi > 0 and p.roi < T.ROI_WARNING:
            alerts.append(self._make("roi_warning", p, series,
                                     f"投产比 {p.roi} 低于预警线 {T.ROI_WARNING}，利润承压",
                                     f"花费 ¥{p.cost:.0f} / 成交 ¥{p.revenue:.0f}"))

        # ② 成本升 + 成交降（用户核心场景，日环比）
        trend = self._trend(series)
        if trend and trend["cost_up"] and trend["revenue_down"]:
            alerts.append(self._make(
                "cost_up_revenue_down", p, series,
                f"推广成本 {trend['cost_prev']:.0f}→{trend['cost_now']:.0f}（+{trend['cost_pct']:.0f}%），"
                f"成交额 {trend['revenue_prev']:.0f}→{trend['revenue_now']:.0f}（{trend['revenue_pct']:.0f}%）："
                f"成本升、成交降，ROI 正在恶化",
                f"日环比口径"))

        for a in alerts:
            a["suggestion"] = self._suggestion(a["type"], p, trend)
        self._llm_decorate(alerts, p)
        return alerts

    def _trend(self, series: dict):
        """最新一天 vs 前一天：成本/成交环比。数据不足两天返回 None"""
        days = sorted(series.keys())
        if len(days) < self.cfg.Monitor.MIN_DAYS:
            return None
        d2, d1 = days[-2], days[-1]
        m2, m1 = series[d2], series[d1]
        cost_prev = float(m2.get("cost") or 0)
        revenue_prev = float(m2.get("revenue") or 0)
        cost_now = float(m1.get("cost") or 0)
        revenue_now = float(m1.get("revenue") or 0)
        if cost_prev <= 0 or revenue_prev <= 0:
            return None
        cost_pct = round((cost_now - cost_prev) / cost_prev * 100, 1)
        revenue_pct = round((revenue_now - revenue_prev) / revenue_prev * 100, 1)
        return {
            "date_prev": d2, "date_now": d1,
            "cost_prev": cost_prev, "cost_now": cost_now, "cost_pct": cost_pct,
            "revenue_prev": revenue_prev, "revenue_now": revenue_now, "revenue_pct": revenue_pct,
            "cost_up": cost_pct > self.cfg.Monitor.COST_UP_PCT * 100,
            "revenue_down": revenue_pct < -self.cfg.Monitor.REVENUE_DOWN_PCT * 100,
        }

    def _make(self, kind, p: AdPlan, series: dict, message: str, extra=""):
        return {
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "level": _SEV.get(kind, "warn"),
            "type": kind,
            "product_id": p.plan_id,
            "name": p.name,
            "message": message,
            "extra": extra,
            "metrics": {
                "roi": p.roi, "cost": round(p.cost, 2), "revenue": round(p.revenue, 2),
                "orders": p.orders, "clicks": p.clicks, "ctr": p.ctr, "cvr": p.cvr,
                "cpc": p.cpc, "cpa": p.cpa, "net_profit": round(p.net_profit, 2),
                "breakeven_roi": p.breakeven_roi,
            },
            "suggestion": "",
            "llm_advice": "",
        }

    # ---------------- 规则建议 ----------------
    def _suggestion(self, kind, p: AdPlan, trend=None):
        if kind == "cost_up_revenue_down":
            return ("① 先看点击成本(CPC)：成本升通常是出价/竞价环境变化，可下调出价 10%~20% 观察一天；"
                    "② 若 CPC 未涨但成交掉，说明转化率下滑，检查竞品价格与评价、优化主图/详情页/优惠券；"
                    "③ 预算建议下调 20%，把额度让给 ROI 达标的链接，避免持续失血。")
        if kind == "roi_loss":
            return ("① 该链接 ROI 已低于保本线，建议暂停或降至最低出价止血；"
                    "② 复盘投放词与人群包，剔除高花费低转化词；"
                    "③ 同步检查售价与毛利：若毛利率上调，保本线会同步下降。")
        if kind == "roi_warning":
            return ("① 预算下调 20% 并观察 1~2 天，避免直接停投导致销量断层；"
                    "② 对比同品类竞品的价格/卖点，考虑加优惠券或换主图提升点击率。")
        return "保持观望，持续巡检。"

    # ---------------- LLM 解读 ----------------
    def _llm_decorate(self, alerts, p: AdPlan):
        """有 key 时对新鲜告警做 LLM 解读；同商品同类型 1 小时内不重复调用"""
        cfg = llm.load_config()
        if not llm.has_key(cfg):
            return
        budget = self.cfg.Monitor.LLM_PER_ROUND
        for a in alerts:
            if budget <= 0:
                break
            key = (a["product_id"], a["type"])
            cached = self._llm_cache.get(key)
            if cached and time.time() - cached[0] < self.cfg.Monitor.LLM_CACHE_SEC:
                a["llm_advice"] = cached[1]
                continue
            prompt = (
                "你是资深电商投放运营专家。以下是店铺某商品链接的实时监控告警：\n"
                f"商品：{a['name']}（ID {a['product_id']}）\n"
                f"问题：{a['message']}\n"
                f"指标：{json.dumps(a['metrics'], ensure_ascii=False)}\n"
                "请给出最多 3 条、可直接执行的调整建议（每条 30 字内），聚焦修复 ROI。"
            )
            content, err = llm.call_llm([{"role": "user", "content": prompt}],
                                        config=cfg, timeout=25)
            if content:
                a["llm_advice"] = content
                self._llm_cache[key] = (time.time(), content)
            budget -= 1

    # ---------------- 持久化 ----------------
    def _save(self):
        try:
            with self._lock:
                payload = {
                    "alerts": self.alerts[: self.cfg.Monitor.MAX_ALERTS],
                    "history": self.history[-120:],
                }
            with open(ALERTS_FILE, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=1)
        except Exception:  # noqa: BLE001
            pass

    def _load(self):
        try:
            with open(ALERTS_FILE, encoding="utf-8") as f:
                d = json.load(f) or {}
            self.alerts = d.get("alerts", []) or []
            self.history = d.get("history", []) or []
        except Exception:  # noqa: BLE001
            self.alerts = []
            self.history = []

    def alerts_view(self, limit=50, level=""):
        out = [a for a in self.alerts if not level or a.get("level") == level]
        return out[:limit]

    def history_view(self, limit=60):
        return self.history[-limit:]


# 模块级单例（与 engine 内其余单例同风格，避免重复实例）
ops_monitor = OperationMonitor(settings)
