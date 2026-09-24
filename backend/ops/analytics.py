# -*- coding: utf-8 -*-
"""运营数据监控与多维报表

- 日/周/月/年 成交数据报表
- 退款率监控 + 退款原因归因分析
- 店铺健康度体检（五维打分）
- 自动生成优化方案
"""
from dataclasses import dataclass, field, asdict
from typing import List, Dict
from datetime import datetime, timedelta
from collections import Counter, defaultdict
import json

from ..engine import llm


@dataclass
class Order:
    order_id: str
    date: str
    amount: float
    quantity: int
    buyer_id: str
    product_id: str
    refunded: bool = False
    refund_amount: float = 0.0
    refund_reason: str = ""
    refund_days_after: int = 0
    channel: str = "自然流量"
    is_new_buyer: bool = True

    def to_dict(self) -> Dict:
        return asdict(self)


class OperationsAnalytics:
    def __init__(self, cfg):
        self.cfg = cfg

    # ---------------- 1. 周期报表 ----------------
    def report(self, orders: List[Order], period: str = "day", date_str: str = None) -> Dict:
        date_str = date_str or datetime.now().strftime("%Y-%m-%d")
        d = datetime.strptime(date_str, "%Y-%m-%d")

        if period == "day":
            sel = [o for o in orders if o.date == date_str]
            label = f"{date_str} 日报"
            prev_sel = [o for o in orders if o.date == (d - timedelta(days=1)).strftime("%Y-%m-%d")]
        elif period == "week":
            start = d - timedelta(days=d.weekday())
            end = start + timedelta(days=6)
            sel = [o for o in orders if start.strftime("%Y-%m-%d") <= o.date <= end.strftime("%Y-%m-%d")]
            label = f"{start.strftime('%Y-%m-%d')} ~ {end.strftime('%Y-%m-%d')} 周报"
            pstart = start - timedelta(days=7)
            prev_sel = [o for o in orders if pstart.strftime("%Y-%m-%d") <= o.date < start.strftime("%Y-%m-%d")]
        elif period == "month":
            prefix = d.strftime("%Y-%m")
            sel = [o for o in orders if o.date.startswith(prefix)]
            label = f"{prefix} 月报"
            prev_prefix = (d.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
            prev_sel = [o for o in orders if o.date.startswith(prev_prefix)]
        elif period == "year":
            prefix = d.strftime("%Y")
            sel = [o for o in orders if o.date.startswith(prefix)]
            label = f"{prefix} 年报"
            prev_sel = [o for o in orders if o.date.startswith(str(int(prefix) - 1))]
        else:
            sel, prev_sel, label = [], [], "未知周期"

        cur = self._metrics(sel)
        prev = self._metrics(prev_sel)
        return {
            "label": label,
            "period": period,
            "指标": cur,
            "环比": self._compare(cur, prev),
            "趋势": self._daily_trend(sel),
        }

    def _metrics(self, sel: List[Order]) -> Dict:
        if not sel:
            return {"成交额": 0, "订单数": 0, "客单价": 0, "件数": 0,
                    "退款单数": 0, "退款金额": 0,
                    "退款率": "0%", "退款原因TOP": [], "新客占比": "0%"}
        amount = sum(o.amount for o in sel)
        cnt = len(sel)
        refunds = [o for o in sel if o.refunded]
        reasons = Counter(o.refund_reason for o in refunds if o.refund_reason)
        return {
            "成交额": round(amount, 2),
            "订单数": cnt,
            "客单价": round(amount / cnt, 2),
            "件数": sum(o.quantity for o in sel),
            "退款单数": len(refunds),
            "退款金额": round(sum(o.refund_amount for o in refunds), 2),
            "退款率": f"{len(refunds)/cnt:.2%}" if cnt else "0%",
            "退款原因TOP": [[r, n] for r, n in reasons.most_common(5)],
            "新客占比": f"{sum(1 for o in sel if o.is_new_buyer)/cnt:.2%}" if cnt else "0%",
        }

    def _compare(self, cur: Dict, prev: Dict) -> Dict:
        out = {}
        for k in ["成交额", "订单数", "客单价"]:
            c, p = cur.get(k, 0), prev.get(k, 0)
            if isinstance(c, str):
                continue
            out[k] = f"{(c - p) / p:+.2%}" if p else "—"
        return out

    def _daily_trend(self, sel: List[Order]) -> List[Dict]:
        by_day = defaultdict(float)
        for o in sel:
            by_day[o.date] += o.amount
        return [{"date": k, "amount": round(v, 2)} for k, v in sorted(by_day.items())]

    # ---------------- 2. 退款归因 ----------------
    def refund_analysis(self, orders: List[Order]) -> Dict:
        refunds = [o for o in orders if o.refunded]
        total = len(orders)
        if not refunds:
            return {"总结": "暂无退款数据", "退款率": "0%"}

        reasons = Counter(o.refund_reason or "未标注" for o in refunds)
        amount_lost = sum(o.refund_amount for o in refunds)

        platform_issue = {"质量问题", "发错货", "少发货", "破损", "物流太慢"}
        user_issue = {"不喜欢", "不想要了", "拍错了", "7天无理由"}
        desc_issue = {"尺码不符", "与描述不符", "色差"}

        buckets = {"商品/发货问题": 0, "买家主观原因": 0, "描述与预期不符": 0, "其他": 0}
        for reason, n in reasons.items():
            if reason in platform_issue:
                buckets["商品/发货问题"] += n
            elif reason in user_issue:
                buckets["买家主观原因"] += n
            elif reason in desc_issue:
                buckets["描述与预期不符"] += n
            else:
                buckets["其他"] += n

        avg_days = sum(o.refund_days_after for o in refunds) / len(refunds) if refunds else 0

        prod = defaultdict(lambda: {"n": 0, "total": 0})
        for o in orders:
            prod[o.product_id]["total"] += 1
            if o.refunded:
                prod[o.product_id]["n"] += 1
        bad_products = sorted(
            [{"product_id": k, "refund_rate": f"{v['n']/v['total']:.2%}", "orders": v["total"]}
             for k, v in prod.items() if v["total"] >= 3 and v["n"] / v["total"] > 0.08],
            key=lambda x: -float(x["refund_rate"].rstrip("%")))

        return {
            "退款率": f"{len(refunds)/total:.2%}",
            "退款单数": len(refunds),
            "退款金额": round(amount_lost, 2),
            "退款原因分布": [{"原因": r, "数量": n, "占比": f"{n/len(refunds):.1%}"}
                        for r, n in reasons.most_common()],
            "问题归类": buckets,
            "平均退款时长": f"{avg_days:.1f} 天",
            "高退款风险商品": bad_products[:10],
        }

    # ---------------- 3. 店铺体检 ----------------
    def shop_health_check(self, orders: List[Order], ad_plans: List = None) -> Dict:
        if not orders:
            return {"总分": 0, "等级": "无数据", "维度": []}

        refunds = [o for o in orders if o.refunded]
        refund_rate = len(refunds) / len(orders)
        avg_price = sum(o.amount for o in orders) / len(orders)
        new_buyer_rate = sum(1 for o in orders if o.is_new_buyer) / len(orders)

        dims = []
        s1 = max(0, 25 * (1 - refund_rate / 0.15))
        dims.append({"维度": "退款健康度", "得分": round(s1, 1), "满分": 25,
                     "实测": f"{refund_rate:.2%}", "行业基准": "<5%"})
        s2 = min(15, 15 * (avg_price / 200)) if avg_price else 0
        dims.append({"维度": "客单价水平", "得分": round(s2, 1), "满分": 15,
                     "实测": f"¥{avg_price:.1f}", "行业基准": ">¥100"})
        s3 = min(20, 20 * (new_buyer_rate / 0.4))
        dims.append({"维度": "新客获取力", "得分": round(s3, 1), "满分": 20,
                     "实测": f"{new_buyer_rate:.2%}", "行业基准": ">35%"})
        if ad_plans:
            roi = sum(p.revenue for p in ad_plans) / max(sum(p.cost for p in ad_plans), 1)
            s4 = min(20, 20 * (roi / 4.0))
        else:
            roi, s4 = 0, 10
        dims.append({"维度": "投放效率", "得分": round(s4, 1), "满分": 20,
                     "实测": f"ROI {roi:.2f}", "行业基准": ">3.0"})
        repurchase = 1 - new_buyer_rate
        s5 = min(20, 20 * (repurchase / 0.5))
        dims.append({"维度": "复购留存", "得分": round(s5, 1), "满分": 20,
                     "实测": f"{repurchase:.2%}", "行业基准": ">40%"})

        total_score = round(sum(d["得分"] for d in dims), 1)
        grade = ("优秀" if total_score >= 85 else "良好" if total_score >= 70
                 else "及格" if total_score >= 60 else "需改进")
        return {"总分": total_score, "等级": grade, "维度": dims,
                "体检时间": datetime.now().isoformat()}


# ============================================================
#  优化方案生成器（LLM 优先，规则引擎兜底）
# ============================================================
class OptimizationAdvisor:
    SYSTEM_PROMPT = """你是一名资深电商运营顾问。你会收到一份店铺体检报告和数据分析结果。
请输出一份【可立即执行】的优化方案，要求：
1. 按【紧急程度】排序，分为「🔴立即处理」「🟡本周优化」「🟢长期规划」
2. 每条建议必须包含：问题现象 → 根因分析 → 具体操作步骤 → 预期效果
3. 语言简洁，商家可直接照做，避免空话套话
4. 涉及数据的地方要引用报告中的具体数字
5. 最后给出【未来30天行动清单】，用待办清单格式"""

    def __init__(self, cfg):
        self.cfg = cfg

    def generate(self, health: Dict, refund: Dict, report: Dict,
                 roi_summary: Dict = None) -> str:
        context = f"""
【店铺体检报告】
总分：{health.get('总分')}（{health.get('等级')}）
各维度明细：
{json.dumps(health.get('维度', []), ensure_ascii=False, indent=2)}

【退款分析】
{json.dumps(refund, ensure_ascii=False, indent=2)}

【经营数据】
{json.dumps(report.get('指标', {}), ensure_ascii=False, indent=2)}
环比：{json.dumps(report.get('环比', {}), ensure_ascii=False)}

【投放情况】
{json.dumps(roi_summary or {}, ensure_ascii=False, indent=2)}
"""
        if not llm.has_key():
            return self._rule_based_plan(health, refund, report, roi_summary)
        try:
            content, err = llm.call_llm(
                [{"role": "system", "content": self.SYSTEM_PROMPT},
                 {"role": "user", "content": context}],
                timeout=60)
            if err:
                raise RuntimeError(err)
            return content
        except Exception as e:
            print(f"⚠️ AI 方案生成失败，回退规则引擎: {e}")
            return self._rule_based_plan(health, refund, report, roi_summary)

    def _rule_based_plan(self, health, refund, report, roi_summary) -> str:
        lines = ["# 📋 店铺优化方案（规则引擎生成）\n"]
        urgent, weekly, longterm = [], [], []

        rr = float(str(refund.get("退款率", "0%")).rstrip("%")) if isinstance(refund.get("退款率"), str) else 0
        if rr >= self.cfg.Threshold.REFUND_RATE_DANGER * 100:
            top = (refund.get("退款原因分布") or [{}])[0].get("原因", "未知")
            bad = (refund.get("高退款风险商品") or [{}])[0].get("product_id", "N/A")
            urgent.append(f"**退款率 {refund.get('退款率')} 已超危险线**\n"
                          f"- 根因：{top} 占比最高\n"
                          f"- 操作：立即核查高退款商品「{bad}」，暂停推广并优化详情页\n"
                          f"- 预期：退款率下降至 6% 以内")
        elif rr >= self.cfg.Threshold.REFUND_RATE_WARNING * 100:
            weekly.append(f"**退款率 {refund.get('退款率')} 偏高**\n"
                          f"- 操作：完善尺码表/实物图，客服主动关怀\n"
                          f"- 预期：退款率降至 5% 以下")

        if roi_summary:
            losers = roi_summary.get("已亏损计划数", 0)
            if losers:
                urgent.append(f"**{losers} 条投放计划已亏损**\n"
                              f"- 操作：立即暂停这些计划，预算转移至 ROI 前 3 的计划\n"
                              f"- 预期：整体投产比提升 0.3~0.5")

        for d in health.get("维度", []):
            ratio = d["得分"] / d["满分"] if d["满分"] else 0
            if ratio < 0.5:
                weekly.append(f"**{d['维度']} 严重不足**（{d['得分']}/{d['满分']}，"
                              f"实测 {d['实测']}，基准 {d['行业基准']}）\n"
                              f"- 操作：针对该维度制定专项提升计划\n"
                              f"- 预期：得分提升至 {d['满分']*0.75:.0f} 分以上")

        longterm.append("**建立数据日报机制**\n- 操作：每天 9 点查看自动日报，关注退款率与投产比趋势\n- 预期：问题提前 3-7 天被发现")
        longterm.append("**沉淀商品素材库**\n- 操作：每周从参考图库挑选 5 张优质主图做 A/B 测试\n- 预期：主图点击率提升 10%+")

        def fmt(title, items):
            if not items:
                return ""
            return f"\n## {title}\n" + "\n\n".join(f"{i+1}. {x}" for i, x in enumerate(items)) + "\n"

        lines.append(fmt("🔴 立即处理（24小时内）", urgent))
        lines.append(fmt("🟡 本周优化", weekly))
        lines.append(fmt("🟢 长期规划", longterm))

        lines.append("\n## ✅ 未来 30 天行动清单\n")
        lines.append("- [ ] 第1天：暂停所有亏损投放计划，重新分配预算")
        lines.append("- [ ] 第2-3天：优化退款率最高的 3 款商品详情页")
        lines.append("- [ ] 第4-7天：用参考图库做一轮主图 A/B 测试")
        lines.append("- [ ] 第2周：建立每日数据看板，设置退款率预警")
        lines.append("- [ ] 第3周：分析复购客户画像，设计老客召回活动")
        lines.append("- [ ] 第4周：复盘整月数据，输出优化报告")
        return "\n".join(lines)
