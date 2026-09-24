# -*- coding: utf-8 -*-
"""真实商家数据仓库：订单 + 商品链接日指标（导入 / 快照 / CDP 同步统一入库）

数据来源（三通道，全部落到一个 JSON 仓库）：
  1) 报表文件导入 —— 拼多多商家后台导出的「订单报表 / 推广报表 / 商品报表」CSV
  2) 手动快照     —— 每日在驾驶舱手动录入各商品链接的成交/花费
  3) CDP 同步     —— 从已登录的商家后台页面自动采集（见 pdd_ops_crawler）

仓库文件：<data>/ops_real.json
结构：
  {
    "orders": [Order...],                    # 真实订单（与 demo 订单同构）
    "links":  { product_id: {                # 商品链接日指标
                 "name": "...",
                 "days": { "YYYY-MM-DD": {"cost","revenue","orders","clicks","impressions","budget"} }
               } },
    "imports": [{"ts","kind","rows","note"}],
    "meta": { "last_sync": "...", "updated": "..." }
  }

使用原则：有真实数据（orders / links 非空）即用真实数据；某项为空才回退演示数据。
"""
import csv
import io
import json
import os
import re
import time
from datetime import datetime

from . import settings
from .analytics import Order
from .roi_monitor import AdPlan

STORE_FILE = os.path.join(settings.data_dir(), "ops_real.json")

_data = {"orders": [], "links": {}, "imports": [], "meta": {},
         "overview": {"provinces": [], "months": []},
         "daily": {}, "periods": {}}


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------------- 持久化 ----------------
def load():
    global _data
    try:
        with open(STORE_FILE, encoding="utf-8") as f:
            d = json.load(f) or {}
        d.setdefault("orders", [])
        d.setdefault("links", {})
        d.setdefault("imports", [])
        d.setdefault("meta", {})
        d.setdefault("overview", {"provinces": [], "months": []})
        d.setdefault("daily", {})
        d.setdefault("periods", {})
        _data = d
    except Exception:
        _data = {"orders": [], "links": {}, "imports": [], "meta": {},
                 "overview": {"provinces": [], "months": []},
                 "daily": {}, "periods": {}}
    return _data


def save():
    _data["meta"]["updated"] = _now()
    try:
        settings.data_dir()
        with open(STORE_FILE, "w", encoding="utf-8") as f:
            json.dump(_data, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def _snapshot():
    return {"orders": len(_data.get("orders", [])),
            "links": len(_data.get("links", {}))}


def _log_import(kind, rows, note=""):
    _data.setdefault("imports", []).append({
        "ts": _now(), "kind": kind, "rows": rows, "note": note or ""})
    _data["imports"] = _data["imports"][-50:]


# ---------------- 读取（供运营引擎使用） ----------------
def real_orders():
    """真实订单 → Order 列表"""
    out = []
    for d in _data.get("orders", []):
        try:
            out.append(Order(**{k: d[k] for k in
                                ("order_id", "date", "amount", "quantity", "buyer_id", "product_id",
                                 "refunded", "refund_amount", "refund_reason",
                                 "refund_days_after", "channel", "is_new_buyer")
                                if k in d}))
        except Exception:
            continue
    return out


def real_plans():
    """真实商品链接日指标 → AdPlan 列表（每个链接每天一条投放计划记录）"""
    out = []
    for pid, node in _data.get("links", {}).items():
        name = str(node.get("name") or pid)
        for day, m in (node.get("days") or {}).items():
            if not day:
                continue
            try:
                out.append(AdPlan(
                    plan_id=str(pid), name=name,
                    cost=float(m.get("cost") or 0),
                    revenue=float(m.get("revenue") or 0),
                    orders=int(m.get("orders") or 0),
                    clicks=int(m.get("clicks") or 0),
                    impressions=int(m.get("impressions") or 0),
                    budget=float(m.get("budget") or 0),
                    price=float(m.get("price") or 0),
                    date=day,
                    product_id=str(pid),
                ))
            except Exception:
                continue
    return out


def link_days():
    """{product_id: {"name":..., "days": {date: {...}}}} —— 供实时监控做趋势判定"""
    return {pid: {"name": str(n.get("name") or pid), "days": dict(n.get("days") or {})}
            for pid, n in _data.get("links", {}).items()}


def real_plan_agg(days=None):
    """真实商品链接 → 每个链接聚合一条 AdPlan（可限定最近 N 天；无数据返回空列表）"""
    from datetime import timedelta
    out = []
    today = datetime.now()
    for pid, node in _data.get("links", {}).items():
        name = str(node.get("name") or pid)
        dmap = node.get("days") or {}
        if days:
            cutoff = (today - timedelta(days=days)).strftime("%Y-%m-%d")
            dmap = {d: m for d, m in dmap.items() if d >= cutoff}
        cost = sum(float(m.get("cost") or 0) for m in dmap.values())
        revenue = sum(float(m.get("revenue") or 0) for m in dmap.values())
        orders = sum(int(m.get("orders") or 0) for m in dmap.values())
        clicks = sum(int(m.get("clicks") or 0) for m in dmap.values())
        impressions = sum(int(m.get("impressions") or 0) for m in dmap.values())
        budget = sum(float(m.get("budget") or 0) for m in dmap.values())
        price = next((float(m.get("price") or 0) for m in dmap.values() if m.get("price")), 0.0)
        if cost or revenue or orders:
            out.append(AdPlan(
                plan_id=str(pid), name=name,
                cost=cost, revenue=revenue, orders=orders, clicks=clicks,
                impressions=impressions, budget=budget, price=price,
            ))
    return out


def has_real():
    """是否已接入真实数据（订单或商品链接任一非空）"""
    return bool(_data.get("orders") or _data.get("links"))


def source_status():
    """数据源状态（供前端展示）"""
    n_orders = len(_data.get("orders", []))
    n_links = len(_data.get("links", {}))
    day_count = sum(len(n.get("days") or {}) for n in _data.get("links", {}).values())
    if n_orders or n_links:
        mode = "real"
    else:
        mode = "demo"
    return {
        "mode": mode,                      # demo | real
        "订单数": n_orders,
        "商品链接数": n_links,
        "链接日记录数": day_count,
        "交易概况": {"省份数": len((_data.get("overview") or {}).get("provinces", [])),
                  "月份数": len((_data.get("overview") or {}).get("months", [])),
                  "更新时间": ((_data.get("overview") or {}).get("updated") or "")},
        "交易数据日统计": {"天数": len(_data.get("daily", {}))},
        "多周期交易数据": {"维度数": len(_data.get("periods", {}))},
        "最近导入": (_data.get("imports") or [{}])[-1] if _data.get("imports") else None,
        "导入记录": _data.get("imports", [])[-10:],
        "meta": _data.get("meta", {}),
        "说明": "真实数据已接入，运营中心自动切换为真实口径" if mode == "real"
                else "暂无真实数据，运营中心使用演示数据",
    }


# ---------------- CSV 解析工具 ----------------
def decode_bytes(raw):
    """兼容 GBK/UTF-8 导出的 CSV 解码"""
    if isinstance(raw, str):
        return raw
    for enc in ("utf-8-sig", "gb18030", "utf-8"):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode("utf-8", errors="replace")


def _norm(h):
    return re.sub(r"\s+", "", str(h or "")).lower()


def _match(headers, keys):
    """返回匹配关键词的表头列下标；关键词按优先级匹配（前面的更具体优先）。

    按「关键词优先」而非「表头顺序」扫描，避免通用词（如「商品」）先命中
    「商品ID」列导致名称列解析错位（例如 商品名称 被读成 商品ID）。
    """
    for k in keys:
        for i, h in enumerate(headers):
            if k in _norm(h):
                return i
    return -1


def to_float(v):
    if v is None:
        return 0.0
    s = re.sub(r"[^\d.\-]", "", str(v).replace(",", "").replace("，", ""))
    if not s or s in ("-", "."):
        return 0.0
    try:
        return float(s)
    except Exception:
        return 0.0


def to_int(v):
    return int(to_float(v))


def to_date(v):
    s = re.sub(r"[^\d]", "", str(v or ""))
    if len(s) >= 8:
        return "%s-%s-%s" % (s[:4], s[4:6], s[6:8])
    return ""


def norm_date(v):
    """兼容 2026/09/20、2026-09-20 12:33、2026年9月20日 → 2026-09-20"""
    s = str(v or "").strip()
    m = re.match(r"(\d{4})[-/年.](\d{1,2})[-/月.](\d{1,2})", s)
    if m:
        return "%s-%02d-%02d" % (m.group(1), int(m.group(2)), int(m.group(3)))
    return to_date(s)


def norm_product_id(v):
    s = str(v or "").strip()
    # 兼容多种写法：goods_id=123 / ID:123 / ID：123 / 链接结尾的数字
    m = re.search(r"(?:goods_id\s*[=:]\s*|ID\s*[:：]\s*)(\d+)" if re.search(r"ID", s, re.I)
                  else r"(?:goods_id\s*[=:]\s*)(\d+)", s, re.I)
    if m:
        return m.group(1)
    return s or "UNKNOWN"


def _first_nonempty(headers, keys, row):
    i = _match(headers, keys)
    if i < 0:
        return ""
    return row[i] if i < len(row) else ""


# ---------------- 导入：订单报表 ----------------
ORDER_COLS = {
    "order_id": ["订单号", "订单编号", "订单id", "订单"],
    "date": ["成交时间", "下单时间", "付款时间", "创建时间", "时间"],
    "amount": ["实付金额", "支付金额", "成交金额", "订单金额", "买家实付"],
    "quantity": ["商品数量", "购买数量", "件数", "数量"],
    "buyer_id": ["买家昵称", "买家", "客户", "买家id"],
    "product_id": ["商品id", "商品编号", "商品链接", "商品", "sku"],
    "refunded": ["退款状态", "是否退款", "订单状态"],
    "refund_amount": ["退款金额"],
    "refund_reason": ["退款原因"],
    "channel": ["订单来源", "成交渠道", "渠道", "来源"],
    "is_new_buyer": ["是否新客", "新客", "新老客"],
}


def import_orders_csv(raw, filename="订单报表.csv"):
    """导入订单 CSV → 合并进仓库（按订单号去重）"""
    text = decode_bytes(raw)
    rows = list(csv.reader(io.StringIO(text)))
    if len(rows) < 2:
        return {"ok": False, "message": "文件内容为空或格式无法识别"}
    headers = [_norm(h) for h in rows[0]]
    added = 0
    for r in rows[1:]:
        if not r or not any(x.strip() for x in r):
            continue
        oid = _first_nonempty(headers, ORDER_COLS["order_id"], r)
        if not oid:
            continue
        date = norm_date(_first_nonempty(headers, ORDER_COLS["date"], r)) or _now()[:10]
        refunded_s = _first_nonempty(headers, ORDER_COLS["refunded"], r)
        refunded = any(k in refunded_s for k in ("退款", "已退", "退货")) and \
                   not any(k in refunded_s for k in ("未退款", "无退款", "无", "正常"))
        new_buyer_s = _first_nonempty(headers, ORDER_COLS["is_new_buyer"], r)
        order = {
            "order_id": oid,
            "date": date,
            "amount": to_float(_first_nonempty(headers, ORDER_COLS["amount"], r)),
            "quantity": max(1, to_int(_first_nonempty(headers, ORDER_COLS["quantity"], r))),
            "buyer_id": _first_nonempty(headers, ORDER_COLS["buyer_id"], r) or "买家",
            "product_id": norm_product_id(_first_nonempty(headers, ORDER_COLS["product_id"], r)),
            "refunded": refunded,
            "refund_amount": to_float(_first_nonempty(headers, ORDER_COLS["refund_amount"], r)),
            "refund_reason": _first_nonempty(headers, ORDER_COLS["refund_reason"], r),
            "refund_days_after": 0,
            "channel": _first_nonempty(headers, ORDER_COLS["channel"], r) or "导入",
            "is_new_buyer": ("新" in new_buyer_s) if new_buyer_s else True,
        }
        idx = next((i for i, o in enumerate(_data["orders"])
                    if o.get("order_id") == oid), None)
        if idx is None:
            _data["orders"].append(order)
        else:
            _data["orders"][idx] = order
        added += 1
    _log_import("订单导入", added, filename)
    save()
    return {"ok": True, "rows": added, "message": f"订单报表导入成功：{added} 条订单"}


# ---------------- 导入：商品链接日指标（推广报表/商品报表） ----------------
LINK_COLS = {
    "date": ["日期", "统计日期", "时间", "数据日期"],
    "product_id": ["商品id", "商品编号", "商品链接", "商品"],
    "name": ["商品名称", "商品标题", "链接标题", "商品"],
    "cost": ["推广花费", "花费", "消耗", "推广费用", "广告花费"],
    "revenue": ["成交金额", "成交额", "交易额", "成交gmv", "gmv"],
    "orders": ["成交订单数", "订单数", "成交件数", "成交订单"],
    "clicks": ["商品访客数", "访客数", "点击量", "点击数", "点击", "消耗点击"],
    "impressions": ["商品浏览量", "浏览量", "展现量", "曝光量", "展现", "曝光"],
    "budget": ["预算", "日预算", "计划预算"],
    "price": ["售价", "单价", "价格"],
}


def import_links_csv(raw, filename="推广报表.csv"):
    """导入商品链接日指标 CSV → 合并进仓库（按 商品id+日期 去重）"""
    text = decode_bytes(raw)
    rows = list(csv.reader(io.StringIO(text)))
    if len(rows) < 2:
        return {"ok": False, "message": "文件内容为空或格式无法识别"}
    headers = [_norm(h) for h in rows[0]]
    added = 0
    for r in rows[1:]:
        if not r or not any(x.strip() for x in r):
            continue
        pid = norm_product_id(_first_nonempty(headers, LINK_COLS["product_id"], r))
        if not pid or pid == "UNKNOWN":
            continue
        date = norm_date(_first_nonempty(headers, LINK_COLS["date"], r)) or _now()[:10]
        node = _data["links"].setdefault(pid, {"name": "", "days": {}})
        name = _first_nonempty(headers, LINK_COLS["name"], r)
        if name:
            node["name"] = name
        m = node["days"].setdefault(date, {})
        for key, col in (("cost", "cost"), ("revenue", "revenue"), ("orders", "orders"),
                         ("clicks", "clicks"), ("impressions", "impressions"),
                         ("budget", "budget"), ("price", "price")):
            v = _first_nonempty(headers, LINK_COLS[col], r)
            if v != "":
                m[key] = to_float(v) if key not in ("orders", "clicks", "impressions") \
                    else to_int(v)
        added += 1
    _log_import("链接指标导入", added, filename)
    save()
    return {"ok": True, "rows": added, "message": f"商品指标导入成功：{added} 条链接日记录"}


# ---------------- 手动快照 ----------------
def add_snapshot(rows):
    """手动录入每日快照：rows = [{product_id, name, date, cost, revenue, orders, clicks, impressions, budget}]"""
    added = 0
    for r in rows or []:
        pid = norm_product_id(r.get("product_id") or "")
        if not pid or pid == "UNKNOWN":
            continue
        date = norm_date(r.get("date")) or _now()[:10]
        node = _data["links"].setdefault(pid, {"name": "", "days": {}})
        if r.get("name"):
            node["name"] = r["name"]
        m = node["days"].setdefault(date, {})
        for key in ("cost", "revenue", "orders", "clicks", "impressions", "budget", "price"):
            if r.get(key) not in (None, ""):
                m[key] = to_float(r[key]) if key not in ("orders", "clicks", "impressions") \
                    else to_int(r[key])
        added += 1
    _log_import("手动快照", added, "每日数据录入")
    save()
    return {"ok": True, "rows": added, "message": f"快照已保存：{added} 条商品链接记录"}


def save_overview(blocks, note=""):
    """保存交易数据页(stores_data)的店铺级交易概况。
    blocks = [{"kind":"provinces|months", "rows":[...]}, ...]"""
    ov = _data.setdefault("overview", {"provinces": [], "months": []})
    for b in blocks or []:
        kind = b.get("kind")
        if kind in ("provinces", "months") and b.get("rows"):
            ov[kind] = b["rows"]
    ov["updated"] = _now()
    _log_import("交易概况", sum(len(b.get("rows", [])) for b in blocks or []), note or "CDP交易概况")
    save()
    return {"ok": True}


def get_overview():
    return _data.get("overview", {"provinces": [], "months": []})


# ---------------- 商店级权威日统计（交易数据页卡） ----------------
def save_daily(records, note=""):
    """保存交易数据页「交易概况」卡的商店级权威日统计。
    records = [{"date":"YYYY-MM-DD", "source":..., "revenue":.., "orders":.., ...}]，
    按日期增量合并，不覆盖未提供的字段。"""
    d = _data.setdefault("daily", {})
    for r in records or []:
        date = r.get("date")
        if not date:
            continue
        ent = d.setdefault(str(date), {})
        ent["updated"] = _now()
        if r.get("source"):
            ent["source"] = r["source"]
        for k in ("revenue", "orders", "buyers", "conversion_rate",
                  "customer_unit_price", "old_buyer_rate", "refund_amount",
                  "refund_orders", "visitor_value", "followers"):
            if r.get(k) is not None:
                ent[k] = r[k]
    save()
    return {"ok": True, "dates": list(d.keys())}


def get_daily():
    """全部商店级日统计：{date: {...}}，按日期倒序返回列表更易展示。"""
    d = _data.get("daily", {})
    return [{"date": k, **v} for k, v in sorted(d.items(), reverse=True)]


def daily_map():
    """按日期索引的商店级权威日统计快照：{date: {...field}}"""
    return dict(_data.get("daily", {}))


# ---------------- 商店级多周期统计（自动点击「实时/昨日/7日/30日/周/月」采集） ----------------
_PERIOD_KEYS = ("revenue", "orders", "buyers", "conversion_rate",
                "customer_unit_price", "old_buyer_rate", "refund_amount",
                "refund_orders", "visitor_value", "followers")
_PERIOD_ORDER = ("实时", "昨日", "7日", "30日", "周", "月")


def save_periods(records, note=""):
    """保存自动点击时间按钮抓取的多周期交易概况。
    records = {"实时": {"revenue":..,"orders":..,...}, "月": {..., "range_start":..,
               "range_end":.., "_cmp": {"成交额":"+x%"}}, ...}
    各周期维度独立存储，绝不与单日权威日统计(daily)混淆。
    range_start/range_end 为该维度在平台页面的「统计时间」区间，供报表侧校验口径吻合。"""
    ent = _data.setdefault("periods", {})
    for label, m in (records or {}).items():
        if not m:
            continue
        rec = {"updated": _now()}
        for k in _PERIOD_KEYS:
            if m.get(k) is not None:
                rec[k] = m[k]
        for k in ("range_start", "range_end"):
            if m.get(k):
                rec[k] = str(m[k])
        if isinstance(m.get("_cmp"), dict) and m["_cmp"]:
            rec["cmp"] = dict(m["_cmp"])
        rec["period"] = label
        ent[str(label)] = rec
    if records:
        _log_import("多周期交易数据", len(records), note or "自动点击采集")
        save()
    return list(ent.keys())


def get_periods():
    """全部多周期交易概况：按 实时/昨日/7日/30日 顺序返回列表。"""
    ent = _data.get("periods", {})
    keys = [k for k in _PERIOD_ORDER if k in ent] + \
           [k for k in ent if k not in _PERIOD_ORDER]
    return [{"period": k, **ent[k]} for k in keys]


def periods_map():
    """按周期维度索引的多周期统计快照：{label: {...field}}"""
    return dict(_data.get("periods", {}))


_ORDER_FIELDS = ("order_id", "date", "amount", "quantity", "buyer_id", "product_id",
                 "refunded", "refund_amount", "refund_reason", "refund_days_after",
                 "channel", "is_new_buyer")


def save_orders(orders, note="CDP 订单明细"):
    """把已结构化的订单明细合并进仓库（按订单号去重），返回新增条数。"""
    added = 0
    for o in orders or []:
        oid = o.get("order_id")
        if not oid:
            continue
        rec = {k: o.get(k) for k in _ORDER_FIELDS if o.get(k) is not None}
        rec.setdefault("refunded", False)
        rec.setdefault("quantity", 1)
        rec.setdefault("buyer_id", "买家")
        rec.setdefault("is_new_buyer", True)
        rec.setdefault("channel", "CDP")
        idx = next((i for i, x in enumerate(_data["orders"])
                    if x.get("order_id") == oid), None)
        if idx is None:
            _data["orders"].append(rec)
            added += 1
        else:
            _data["orders"][idx].update(rec)
    if added:
        _log_import("订单明细", added, note)
        save()
    return added


def mark_live_synced(msg):
    """记录最近一次「实时同步」发生的时间与采样摘要（供驾驶舱展示跟随平台）。"""
    _data["meta"]["last_live_sync"] = _now() + (" · " + msg if msg else "")
    save()


def last_live_sync():
    return _data.get("meta", {}).get("last_live_sync", "")


# ---------------- CDP 同步落库（由 pdd_ops_crawler 调用） ----------------
def save_sync_rows(rows, note=""):
    """把 CDP 同步得到的行直接落库（同 add_snapshot，但记日志为 CDP 同步）"""
    out = add_snapshot(rows)
    if _data["imports"]:
        _data["imports"][-1]["kind"] = "CDP同步"
        _data["imports"][-1]["note"] = note or "商家后台自动采集"
        _data["meta"]["last_sync"] = _now()
        save()
    return out


def clear_real_data():
    _data["orders"] = []
    _data["links"] = {}
    _log_import("清空", 0, "清空全部真实数据")
    save()
    return {"ok": True, "message": "已清空全部真实数据"}


# ---------------- 模板导出（帮助用户理解导入格式） ----------------
def template(kind):
    if kind == "orders":
        return ("订单号,成交时间,商品ID,商品数量,实付金额,买家昵称,退款状态,退款金额,退款原因,成交渠道,是否新客\n"
                "ORD10001,2026-09-20 12:00:00,123456789,1,89.00,买家A,无退款,0,,自然流量,新客")
    return ("日期,商品ID,商品名称,推广花费,成交金额,成交订单数,点击量,展现量,预算\n"
            "2026-09-20,123456789,爆款商品标题,1500.00,5200.00,46,1200,30000,2000")


load()
