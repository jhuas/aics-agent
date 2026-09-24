# -*- coding: utf-8 -*-
import json, os, sys
sys.path.insert(0, r"d:\traework\6aae8dd9cbf1d382b9c007d0\ai-cs-agent")
os.chdir(r"d:\traework\6aae8dd9cbf1d382b9c007d0\ai-cs-agent")
from backend.ops import store, reconcile

def mk_order(oid, date, amount, buyer, refunded=False, ra=0.0):
    return {"order_id": oid, "date": date, "amount": amount, "quantity": 1,
            "buyer_id": buyer, "product_id": "P1", "refunded": refunded,
            "refund_amount": ra, "refund_reason": "不喜欢" if refunded else "",
            "refund_days_after": 1, "channel": "CDP", "is_new_buyer": True}

# 场景A：完全一致
store._data = {"orders": [], "links": {}, "imports": [], "meta": {}, "overview": {}, "daily": {}}
store._data["daily"]["2026-09-01"] = {"revenue": 1000.0, "orders": 10, "buyers": 8,
                                      "refund_orders": 1, "refund_amount": 50.0, "source": "交易数据页"}
store._data["orders"] = [mk_order(f"O{i}", "2026-09-01", 100.0, f"B{i}") for i in range(9)]
store._data["orders"].append(mk_order("Or", "2026-09-01", 100.0, "Br", True, 50.0))
r = reconcile.reconcile()
print("A一致:", r["conclusion"], "| 状态:", [row["status"] for row in r["rows"]],
      "| warn天数:", r["summary"]["warn"])

# 场景B：订单数缺失（少2单）
store._data["orders"] = [mk_order(f"O{i}", "2026-09-01", 100.0, f"B{i}") for i in range(8)]
r = reconcile.reconcile()
print("B少单:", r["conclusion"], "| 订单数偏差:",
      [m for row in r["rows"] for m in row["metrics"] if m["name"] == "订单数"])

# 场景C：仅有权威日统计无订单
store._data["orders"] = []
r = reconcile.reconcile()
print("C无明细:", r["conclusion"], "| 状态:", [row["status"] for row in r["rows"]])

# 场景D：权威缺退款字段（跳过比对）
store._data["orders"] = [mk_order(f"O{i}", "2026-09-01", 100.0, f"B{i}") for i in range(9)]
store._data["daily"]["2026-09-01"] = {"revenue": 1000.0, "orders": 10, "buyers": 8}
r = reconcile.reconcile()
metrics = [row["metrics"] for row in r["rows"] if row["metrics"]][0]
print("D缺退款字段:", [m["name"] for m in metrics], "| 判定:", r["rows"][0]["status"])

# 场景E：有订单但无权威（订单无对应权威日）
store._data["daily"] = {}
r = reconcile.reconcile()
print("E仅订单:", r["summary"], "| conclusion:", r["conclusion"], "| rows:", len(r["rows"]))

# 场景F：空数据
store._data["orders"] = []
store._data["daily"] = {}
r = reconcile.reconcile()
print("F空数据:", r["summary"], "| conclusion:", r["conclusion"])

# 场景G：全部无订单明细（权威有、订单空）——结论不应再误报“通过”
store._data["orders"] = []
store._data["daily"]["2026-09-01"] = {"revenue": 1000.0, "orders": 10, "buyers": 8, "source": "交易数据页"}
r = reconcile.reconcile()
print("G全无明细:", r["conclusion"], "| 状态:", [row["status"] for row in r["rows"]])

# 场景H：auth=0 且 orders=0 应判一致（dev 0），不为“不可比”
store._data["orders"] = [mk_order("Oz1", "2026-09-03", 0.0, "Bz")]
store._data["daily"]["2026-09-03"] = {"revenue": 0.0, "orders": 1, "buyers": 1, "source": "交易数据页"}
r = reconcile.reconcile()
h = [row for row in r["rows"] if row["date"] == "2026-09-03"][0]
hm = {m["name"]: (m["dev"], m["warn"]) for m in h["metrics"]}
print("H零口径:", h["status"], "| 成交额偏差:", hm.get("成交额"), "| 订单数偏差:", hm.get("订单数"))

# 场景I：重复 order_id 应去重，订单数不虚高
store._data["orders"] = [
    mk_order("dup1", "2026-09-04", 100.0, "Bd1"),
    mk_order("dup1", "2026-09-04", 100.0, "Bd1"),  # 重复单号
]
store._data["daily"]["2026-09-04"] = {"revenue": 100.0, "orders": 1, "buyers": 1, "source": "交易数据页"}
r = reconcile.reconcile()
i = [row for row in r["rows"] if row["date"] == "2026-09-04"][0]
im = {m["name"]: (m["authority"], m["orders"], m["dev"]) for m in i["metrics"]}
print("I去重:", i["status"], "| 订单数(权威vs订单):", im.get("订单数"), "| 成交额:", im.get("成交额"))

# 场景J：wo_authority 具体日期透出
store._data["orders"] = [mk_order("w1", "2026-09-05", 50.0, "Bw")]
store._data["daily"] = {}
r = reconcile.reconcile()
print("J仅订单:', r['summary'].get('orders_wo_authority_dates'), '| 数量:", r["summary"]["orders_wo_authority"])
print("OK")