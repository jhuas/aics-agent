# -*- coding: utf-8 -*-
"""严格对账：以「交易数据-实时」权威日统计为基准，与本地订单明细逐日比对，
任一字段偏差超阈值即告警，用于自检数据是否完整、口径是否一致、同步是否有误。

原则（与全项目口径一致）：权威日统计为准，订单明细仅作校验参考。
- 有权威日统计、无订单明细的日期 → only_daily（无法比对，仅提示，不判告警）
- 有权威日统计 + 有订单明细 → 逐字段比对，任一字段偏差 > 阈值 → warn
- 权威无对应字段（如 refund_amount 缺失）→ 跳过该字段
"""
from datetime import datetime

from . import store

# 偏差阈值：|权威 - 订单| / 权威，超过即告警（0.05 = 5%）
DEVIATION_THRESHOLD = 0.05


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# (权威字段, 订单聚合方式, 中文名, 是否参与告警判定)
# 买家数在权威统计与订单明细间口径常不一致（如退款买家两口径统计不同），
# 故仅列示比对、不触发整体告警，避免非真实偏差噪音。
FIELDS = (
    ("revenue", "sum_amount", "成交额", True),
    ("orders", "count", "订单数", True),
    ("buyers", "count_buyers", "买家数", False),
    ("refund_orders", "count_refunds", "退款单数", True),
    ("refund_amount", "sum_refund", "退款金额", True),
)


def _agg_orders(orders):
    """按日期聚合订单明细。amount/订单数/独立买家数/退款单数/退款金额。
    同一 order_id 只计一次（save_orders/导入均已按单号去重，此处再做内存兜底，
    防止外部改写仓库或历史遗留重复导致订单数/成交额虚高）。"""
    by = {}
    seen = set()
    for o in orders:
        oid = getattr(o, "order_id", "")
        if oid:
            if oid in seen:
                continue
            seen.add(oid)
        d = getattr(o, "date", "") or ""
        if not d:
            continue
        a = by.setdefault(d, {"amount": 0.0, "n": 0, "buyers": set(),
                              "refunds": 0, "refund_amt": 0.0})
        a["amount"] += float(getattr(o, "amount", 0) or 0)
        a["n"] += 1
        b = getattr(o, "buyer_id", "")
        if b:
            a["buyers"].add(b)
        if getattr(o, "refunded", False):
            a["refunds"] += 1
            a["refund_amt"] += float(getattr(o, "refund_amount", 0) or 0)
    return by


def _field_val(a, key):
    return {
        "count": a["n"],
        "sum_amount": a["amount"],
        "count_buyers": len(a["buyers"]),
        "count_refunds": a["refunds"],
        "sum_refund": a["refund_amt"],
    }[key]


def deviation(auth, orders_val):
    """偏差率 = |orders - auth| / auth；auth 为 0 时特殊处理。
    - 两者都为 0 → 0（一致，不算偏差）
    - 权威为 0 但订单非 0 → 1.0（100% 偏差，告警）
    - 权威非 0 → 相对偏差"""
    if not auth:
        return 0.0 if orders_val == 0 else 1.0
    return abs(orders_val - auth) / auth


def reconcile():
    """返回权威日统计 vs 订单明细的严格对账报告。"""
    dmap = store.daily_map()
    orders = store.real_orders()
    agg = _agg_orders(orders)

    daily_dates = sorted(dmap.keys())
    rows = []
    n_ok = n_warn = n_only_daily = 0

    for date in daily_dates:
        rec = dmap[date] or {}
        a = agg.get(date)
        if a is None:
            n_only_daily += 1
            rows.append({"date": date, "status": "only_daily",
                         "source": rec.get("source", ""),
                         "note": "仅有权威日统计、无对应订单明细",
                         "metrics": []})
            continue

        metrics = []
        day_warn = False
        for dkey, aggkey, name, warnable in FIELDS:
            av = rec.get(dkey)
            if av is None:
                continue
            try:
                avf, ovf = float(av), float(_field_val(a, aggkey))
            except (TypeError, ValueError):
                continue
            dev = deviation(avf, ovf)
            is_warn = warnable and dev is not None and dev > DEVIATION_THRESHOLD
            if is_warn:
                day_warn = True
            metrics.append({"name": name, "authority": avf, "orders": ovf,
                            "dev": dev, "warn": is_warn})

        status = "warn" if day_warn else "ok"
        if status == "warn":
            n_warn += 1
        else:
            n_ok += 1
        rows.append({"date": date, "status": status,
                     "source": rec.get("source", ""), "metrics": metrics})

    # 有订单明细但无对应权威日统计的天（权威口径之外的补充数据，单独提示）
    wo_authority = sorted(set(agg.keys()) - set(dmap.keys()))

    if n_warn:
        conclusion = f"有 {n_warn} 天存在偏差，需核查数据完整性或口径"
    elif not daily_dates:
        # 没有任何权威日统计（权威为准），无论订单是否存在都无可比对
        conclusion = "暂无权威日统计，暂无可对账数据"
    elif n_ok == 0 and n_only_daily:
        # 没有一天能真正两两比对，不能用「通过」误导用户
        conclusion = "仅有权威日统计、尚未采集订单明细，暂无可对账数据"
    else:
        conclusion = "通过"
    return {
        "generated_at": _now(),
        "threshold": DEVIATION_THRESHOLD,
        "mode": "real" if (dmap or agg) else "demo",
        "summary": {
            "dates": len(daily_dates),
            "ok": n_ok,
            "warn": n_warn,
            "only_daily": n_only_daily,
            "orders_wo_authority": len(wo_authority),
            "orders_wo_authority_dates": wo_authority,
        },
        "conclusion": conclusion,
        "rows": rows,
    }