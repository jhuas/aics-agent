# -*- coding: utf-8 -*-
"""运营自动化引擎 —— 配置与业务阈值（全部集中在此，禁止硬编码）"""
import os

from .. import paths


def data_dir(sub=None):
    d = os.path.join(paths.data_root(), "data")
    if sub:
        d = os.path.join(d, sub)
    paths.ensure_dir(d)
    return d


# ============ 业务阈值（可按店铺调整）============
class Threshold:
    # --- ROI / 投产比监控 ---
    ROI_TARGET = 3.0          # 目标投产比
    ROI_WARNING = 2.2         # 预警线：低于此值触发降本动作
    ROI_DANGER = 1.5          # 危险线：立即停投/降价
    ROI_CUT_BUDGET_PCT = 0.20  # 触预警时下调预算比例

    # --- 利润 ---
    MIN_GROSS_MARGIN = 0.25   # 最低毛利率 25%
    MIN_NET_MARGIN = 0.08     # 最低净利率 8%

    # --- 退款 ---
    REFUND_RATE_WARNING = 0.05  # 退款率预警 5%
    REFUND_RATE_DANGER = 0.10   # 退款率危险 10%

    # --- 成本 ---
    MAX_AD_COST_RATIO = 0.30    # 广告费占销售额上限 30%


# ============ 实时监控（异常检测阈值）============
class Monitor:
    INTERVAL = 60               # 默认巡检间隔（秒）
    COST_UP_PCT = 0.05          # 推广成本较前日上升 >5% 判定为「成本升」
    REVENUE_DOWN_PCT = 0.05     # 成交额较前日下降 >5% 判定为「成交降」
    MIN_DAYS = 2                # 至少需要连续 N 天才做趋势判定
    MAX_ALERTS = 200            # 告警环形缓冲上限
    LLM_PER_ROUND = 2           # 每轮最多调用 LLM 解读的告警条数
    LLM_CACHE_SEC = 3600        # 同一商品同类型告警 1 小时内不重复解读


# ============ 爬虫 / 采集配置（演示模式 + 官方 API 适配）============
class Crawler:
    PLATFORMS = ["taobao", "jd", "pdd", "douyin"]
    REQUEST_INTERVAL = 2.0     # 请求间隔（秒）
    MAX_RETRY = 3
    TIMEOUT = 15
    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    ]
    COMPLIANCE_MODE = True     # 合规：仅采集公开可见信息，遵守 robots.txt
    DEMO_MODE = True           # 演示模式：本地造数，不发起真实请求

    # --- 商家后台 CDP 同步（pdd_ops_crawler）---
    DEBUGGER = "http://127.0.0.1:9222"   # 调试浏览器 CDP 端口（核心截图/爬取复用）
    # 交易数据页(sycm/stores_data/operation)顶部「交易概况」卡提供商店级权威
    # 成交金额/订单数/买家数/客单价/退款等日统计（优先于商品页推算值），放首
    # 位；自动同步时优先导航过去，随后补采商品数据页的商品链接日指标。
    OP_PAGES = [               # 候选数据页地址（商家后台已登录会话中自动打开）
        "https://mms.pinduoduo.com/sycm/stores_data/operation",
        "https://mms.pinduoduo.com/sycm/goods_effect",
        "https://mms.pinduoduo.com/data/dashboard",
        "https://mms.pinduoduo.com/goods/goods_list",
    ]
    # 订单明细页候选（实时同步时逐单采集；页面只要含「订单号」列表即自动识别，
    # 地址写错会安全跳过）。请按你店铺实际的「订单管理 / 订单明细」页地址替换。
    ORDER_PAGES = [
        "https://mms.pinduoduo.com/order/",
    ]
    SYNC_TIMEOUT = 12          # 等待页面表格渲染的最长秒数
    NAV_WAIT = 6               # 导航后等待秒数


# ============ 存储路径 ============
COMMANDS_DB = os.path.join(data_dir(), "ops_commands.db")
VERSIONS_DB = os.path.join(data_dir(), "ops_command_versions.db")
REFERENCE_IMAGES_DIR = os.path.join(data_dir(), "reference_images")
