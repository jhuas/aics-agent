# -*- coding: utf-8 -*-
"""ROI（投产比）实时监控与动态调节引擎

实时采集投放数据 -> 计算 ROI -> 与阈值比较 -> 生成调节动作/建议
"""
from dataclasses import dataclass
from typing import List, Dict
from datetime import datetime
from enum import Enum


class Action(str, Enum):
    KEEP = "保持观望"
    CUT_BUDGET = "下调预算"
    PAUSE_PLAN = "暂停计划"
    RAISE_BUDGET = "追加预算"
    ADJUST_PRICE = "调整售价"
    REPLACE_CREATIVE = "更换素材"
    ALERT_HUMAN = "人工介入"


@dataclass
class AdPlan:
    """一条广告投放计划"""
    plan_id: str
    name: str
    cost: float
    revenue: float
    orders: int
    clicks: int
    impressions: int
    budget: float
    price: float = 0.0
    cogs_ratio: float = 0.45

    @property
    def roi(self) -> float:
        return round(self.revenue / self.cost, 2) if self.cost > 0 else 0.0

    @property
    def ctr(self) -> float:
        return round(self.clicks / self.impressions, 4) if self.impressions else 0.0

    @property
    def cvr(self) -> float:
        return round(self.orders / self.clicks, 4) if self.clicks else 0.0

    @property
    def cpc(self) -> float:
        return round(self.cost / self.clicks, 2) if self.clicks else 0.0

    @property
    def cpa(self) -> float:
        return round(self.cost / self.orders, 2) if self.orders else 0.0

    @property
    def gross_profit(self) -> float:
        return round(self.revenue * (1 - self.cogs_ratio), 2)

    @property
    def net_profit(self) -> float:
        return round(self.gross_profit - self.cost, 2)

    @property
    def net_margin(self) -> float:
        return round(self.net_profit / self.revenue, 4) if self.revenue else 0.0

    @property
    def breakeven_roi(self) -> float:
        return round(1 / (1 - self.cogs_ratio), 2) if self.cogs_ratio < 1 else 0.0

    def to_dict(self) -> Dict:
        return {
            "plan_id": self.plan_id, "name": self.name,
            "cost": self.cost, "revenue": self.revenue,
            "orders": self.orders, "clicks": self.clicks,
            "impressions": self.impressions, "budget": self.budget,
            "price": self.price, "cogs_ratio": self.cogs_ratio,
            "roi": self.roi, "ctr": self.ctr, "cvr": self.cvr,
            "cpc": self.cpc, "cpa": self.cpa,
            "net_profit": self.net_profit,
            "net_margin": self.net_margin,
            "breakeven_roi": self.breakeven_roi,
        }


class ROIOptimizer:
    """投产比优化器：输出每条第计划的调节指令"""

    def __init__(self, cfg):
        self.cfg = cfg

    def diagnose(self, plan: AdPlan) -> Dict:
        roi = plan.roi
        be = plan.breakeven_roi
        actions: List[str] = []
        reasons: List[str] = []

        if roi < be:
            actions.append(Action.PAUSE_PLAN)
            reasons.append(
                f"投产比 {roi} 低于保本线 {be}，每单亏损约 "
                f"{plan.cpa - plan.gross_profit/max(plan.orders,1):.2f} 元")
        elif roi < self.cfg.Threshold.ROI_DANGER:
            actions.append(Action.PAUSE_PLAN)
            reasons.append(f"投产比 {roi} 低于危险线 {self.cfg.Threshold.ROI_DANGER}")
        elif roi < self.cfg.Threshold.ROI_WARNING:
            actions.append(Action.CUT_BUDGET)
            pct = int(self.cfg.Threshold.ROI_CUT_BUDGET_PCT * 100)
            reasons.append(f"投产比 {roi} 低于预警线，建议预算下调 {pct}%")
        elif roi >= self.cfg.Threshold.ROI_TARGET:
            actions.append(Action.RAISE_BUDGET)
            reasons.append(f"投产比 {roi} 达标，可追加预算放量")
        else:
            actions.append(Action.KEEP)
            reasons.append(f"投产比 {roi} 处于健康区间")

        if plan.ctr < 0.02:
            actions.append(Action.REPLACE_CREATIVE)
            reasons.append(f"点击率 {plan.ctr:.2%} 偏低（素材吸引力不足）")
        if plan.cvr < 0.01 and plan.clicks > 50:
            actions.append(Action.ADJUST_PRICE)
            reasons.append(f"转化率 {plan.cvr:.2%} 偏低（价格或详情页竞争力不足）")

        if plan.net_margin < self.cfg.Threshold.MIN_NET_MARGIN and plan.revenue > 0:
            actions.append(Action.ALERT_HUMAN)
            reasons.append(f"净利率 {plan.net_margin:.2%} 低于底线，需人工评估定价")

        return {
            "plan_id": plan.plan_id,
            "plan_name": plan.name,
            "roi": roi,
            "breakeven_roi": be,
            "net_profit": plan.net_profit,
            "net_margin": f"{plan.net_margin:.2%}",
            "actions": [a.value for a in actions],
            "reasons": reasons,
            "ts": datetime.now().isoformat(),
        }

    def reallocate(self, plans: List[AdPlan], daily_budget: float) -> Dict:
        total_roi = sum(max(p.roi, 0) for p in plans) or 1.0
        allocation = []
        for p in plans:
            weight = max(p.roi, 0) / total_roi
            suggest = round(daily_budget * weight, 2)
            allocation.append({
                "plan_id": p.plan_id,
                "name": p.name,
                "roi": p.roi,
                "current_budget": p.budget,
                "suggest_budget": suggest,
                "delta": round(suggest - p.budget, 2),
                "action": "追加" if suggest > p.budget
                else ("下调" if suggest < p.budget else "不变"),
            })
        allocation.sort(key=lambda x: -x["roi"])
        return {
            "total_budget": daily_budget,
            "expect_roi": round(sum(p.revenue for p in plans) / max(sum(p.cost for p in plans), 1), 2),
            "allocation": allocation,
        }

    def summary(self, plans: List[AdPlan]) -> Dict:
        cost = sum(p.cost for p in plans)
        revenue = sum(p.revenue for p in plans)
        orders = sum(p.orders for p in plans)
        profit = sum(p.net_profit for p in plans)
        return {
            "总花费": round(cost, 2),
            "总成交": round(revenue, 2),
            "整体投产比": round(revenue / cost, 2) if cost else 0,
            "总订单": orders,
            "总净利": round(profit, 2),
            "整体净利率": f"{profit / revenue:.2%}" if revenue else "0%",
            "健康计划数": sum(1 for p in plans if p.roi >= self.cfg.Threshold.ROI_TARGET),
            "预警计划数": sum(1 for p in plans if p.roi < self.cfg.Threshold.ROI_WARNING),
            "已亏损计划数": sum(1 for p in plans if p.net_profit < 0),
        }
