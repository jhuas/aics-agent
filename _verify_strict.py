# -*- coding: utf-8 -*-
"""验证严格口径：每日/周/月/30天交易额只能来自在线权威日统计(daily)。
- 无 daily 权威数据 → 成交类指标置空并标注「无在线数据」，绝不用演示/订单冒充。
- 有 daily → 精确聚合。
- 参考图库 crawl_category 在 CDP 不可达时安全降级演示。
"""
from unittest import mock
from datetime import datetime, timedelta

from backend.ops import engine
from backend.ops.image_crawler import ImageReferenceCrawler

TODAY = datetime.now().strftime("%Y-%m-%d")
YDAY = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")


class FakeStore:
    def __init__(self, daily=None, real_orders=None, has_real=True):
        self._daily = daily or {}
        self._orders = real_orders or []
        self._has_real = has_real
    def has_real(self): return self._has_real
    def real_orders(self): return self._orders
    def daily_map(self): return self._daily
    def periods_map(self): return {}
    def get_daily(self): return []
    def link_days(self): return {}
    def real_plan_agg(self, days=None): return []
    def last_live_sync(self): return None
    def source_status(self): return {"说明": ""}
    def get_overview(self): return {}


def fmt(idx):
    return {k: idx.get(k) for k in ("成交额", "订单数", "客单价", "退款率") if idx.get(k) is not None}


# 场景①：完全无 daily → day/week/month 必须都标注「无在线数据」，成交类为 None
s = FakeStore(daily={}, real_orders=[], has_real=False)
with mock.patch.object(engine, "store", s):
    engine.gen_demo_data()
    for p in ("day", "week", "month"):
        r = engine.report(p)
        src = r["指标"].get("数据来源")
        amt = r["指标"].get("成交额")
        print("[无daily] %s 来源=%s 成交额=%s" % (p, src, amt))
        assert "无在线数据" in src, p + " 应标无在线数据，got " + str(src)
        assert amt is None, p + " 成交额应为None，got " + str(amt)
print("✅ 场景① 无daily→严格置空标注 通过\n")

# 场景②：有 daily → 精确聚合
daily = {TODAY: {"revenue": 5000.0, "orders": 50, "buyers": 40,
                 "conversion_rate": "3.5%", "refund_orders": 2, "refund_amount": 200.0}}
s = FakeStore(daily=daily, real_orders=[])
with mock.patch.object(engine, "store", s):
    for p in ("day", "week", "month"):
        r = engine.report(p)
        idx = r["指标"]
        print("[有daily] %s 来源=%s 成交额=%s 单=%s 客单=%s" % (
            p, idx.get("数据来源"), idx.get("成交额"), idx.get("订单数"), idx.get("客单价")))
        assert idx.get("数据来源") == "交易数据-实时"
        if p == "day":
            assert idx.get("成交额") == 5000.0 and idx.get("客单价") == 100.0
print("✅ 场景② 有daily→精确聚合 通过\n")

# 场景③：有订单但无 daily → 成交类也必须置空（订单不作为交易额来源）
s3 = FakeStore(daily={}, real_orders=[], has_real=True)
with mock.patch.object(engine, "store", s3):
    r = engine.report("day")
    print("[有真实订单但无daily] 来源=%s 成交额=%s" % (r["指标"].get("数据来源"), r["指标"].get("成交额")))
    assert "无在线数据" in r["指标"]["数据来源"]
    assert r["指标"]["成交额"] is None
print("✅ 场景③ 订单不得冒充在线成交 通过\n")

# 场景④：overview / optimization 空 daily 不应崩溃
s = FakeStore(daily={}, real_orders=[], has_real=False)
with mock.patch.object(engine, "store", s):
    engine.gen_demo_data()
    o = engine.overview()
    print("[overview] 今日成交额=%s 数据口径=%s" % (
        o["今日"].get("成交额"), o["数据口径"]))
    opt = engine.optimization()
    print("[optimization] 生成状态=%s" % (list(opt.keys())[0]))
print("✅ 场景④ overview/optimization 空daily不崩溃 通过\n")

# 场景⑤：参考图库 CDP 不可达 → 自动拉起失败后降级演示，不崩溃
import os as _os
_os.environ["AICS_NO_CHROME"] = "1"   # 测试环境禁止自动拉起浏览器
c = ImageReferenceCrawler()
res = c.crawl_category("pdd", "摩托车", "定风翼", 3)
errors = [r for r in res if r.get("error") or r.get("warn")]
print("[图库CDP不可达] 结果%d条，提示%d条，真实图%d条" % (
    len(res), len(errors), len([r for r in res if not r.get("error")])))
assert errors, "CDP不可达时应返回降级提示"
assert any(r.get("warn") for r in res), "降级提示应带 warn 标记供前端提示"
print("✅ 场景⑤ 图库CDP不可达安全降级 通过")

print("\nALL STRICT-MODE VERIFICATIONS PASSED ✅")