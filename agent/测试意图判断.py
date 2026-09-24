# -*- coding: utf-8 -*-
"""auto_keeper 意图判断离线自测（不连浏览器、不发送）"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from auto_keeper import decide, match_style, is_ack  # noqa: E402

# 读类目路由配置，用于构造「定风翼堵盖」会话场景
with open(os.path.join(HERE, "kb.json"), encoding="utf-8") as _f:
    _ROUTES = json.load(_f).get("_商品类目路由", {})
WING = ("定风翼堵盖", _ROUTES.get("定风翼堵盖", {}))

CASES = [
    # (客户消息, 我方是否有历史, 期望动作, 期望参数, 会话类目[, 咨询商品文本][, 会话状态flags])
    # ---- 脚踏/挡杆 品类（默认） ----
    ("有实拍图吗", False, "images", "?"),          # 未指明款式 → 追问
    ("发个实拍图看看", True, "images", "?"),
    ("我要A款", True, "chosen", "A款脚踏"),
    ("a款吧", True, "chosen", "A款脚踏"),
    ("第一个那个", True, "chosen", "A款脚踏"),
    ("B款", True, "chosen", "B款脚踏"),
    ("b款看着不错", True, "chosen", "B款脚踏"),
    ("要A款，先发个实拍图看看", True, "images", "A款脚踏"),

    # ================= 用户 2026-09-19 新命令：教程咨询先反问 =================
    # 问教程但没说清「脚踏还是挡杆」→ 先发 install_ask 反问（kb:install_ask），不发视频
    ("有没有安装教程", True, "kb", "kb:install_ask"),
    ("有教程吗", True, "kb", "kb:install_ask"),
    ("有安装视频吗", True, "kb", "kb:install_ask"),
    ("教程", True, "kb", "kb:install_ask"),
    ("怎么安装", True, "kb", "kb:install_ask"),
    ("老板有没有安装视频", True, "kb", "kb:install_ask"),
    ("发个安装视频", True, "kb", "kb:install_ask"),
    ("安装视频发我", True, "kb", "kb:install_ask"),
    ("谢谢，有安装教程吗", True, "kb", "kb:install_ask"),   # 不能被「谢谢」当客套吞掉
    # 说清了对象 → 直接发对应视频（不退化成反问）
    ("有没有挡杆的安装教程", True, "install", "挡杆安装"),
    ("这是脚踏的不是挡杆的，我要的是挡杆的安装教程", True, "install", "挡杆安装"),
    ("挡杆怎么装", True, "install", "挡杆安装"),
    ("有没有脚踏的安装教程", True, "install", "脚踏安装"),
    ("脚踏怎么安装", True, "install", "脚踏安装"),
    # 客户没说，但【咨询商品】能判断出对象 → 也直接发（算「说清」）
    ("有教程吗", True, "install", "脚踏安装", None, "A款脚踏 摩托车脚踏板 斜纹"),
    ("有教程吗", True, "install", "挡杆安装", None, "春风500SR 前后踩挡杆总成"),
    ("怎么安装", True, "install", "黑旗600挡杆安装", None, "黑旗600 改装挡杆 黑色"),
    # 反问已发 → 客户的回答（正文可能不含「教程/安装」二字）
    ("脚踏", True, "install", "脚踏安装", None, "", {"tut_asked": True}),
    ("挡杆的", True, "install", "挡杆安装", None, "", {"tut_asked": True}),
    ("挡杆，我是黑旗600", True, "install", "黑旗600挡杆安装", None, "", {"tut_asked": True}),
    ("两个都要", True, "install", ["脚踏安装", "挡杆安装"], None, "", {"tut_asked": True}),
    # 回答里夹了别的意图 → 不能被当成「回答」（否则「脚踏多少钱」会被发安装视频）
    ("脚踏多少钱", True, "kb", "kb:price_ask", None, "", {"tut_asked": True}),
    ("发个实拍图看看", True, "images", "?", None, "", {"tut_asked": True}),
    # 视频已发过 → 不再进入「等回答」状态
    ("脚踏的", True, "kb", "kb:pedal_A", None, "",
     {"tut_asked": True, "tut_video_sent": True}),

    # ---- 指令二：咨询商品含「黑旗600」→ 第一个视频换成黑旗600专用版 ----
    ("有没有挡杆的安装教程", True, "install", "黑旗600挡杆安装", None, "黑旗600 改装挡杆 黑色"),
    ("挡杆怎么装", True, "install", "黑旗600挡杆安装", None, "黑旗 600 前后踩挡杆"),
    ("有没有挡杆的安装教程", True, "install", "挡杆安装", None, "春风550CLC 挡杆"),
    # ---- 2026-09-19 实测回归：客户【正文】含黑旗600，但咨询商品读不到（goods 为空）----
    ("有没有黑旗600挡杆安装教程", True, "install", "黑旗600挡杆安装", None, ""),
    ("黑旗 600 挡杆怎么装", True, "install", "黑旗600挡杆安装", None, ""),
    ("黑旗600的挡杆安装视频发我", True, "install", "黑旗600挡杆安装"),
    ("有没有挡杆的安装教程", True, "install", "挡杆安装", None, ""),
    ("黑旗600脚踏怎么装", True, "install", "脚踏安装", None, ""),

    # ---- 指令一：对安装教程不满意 → 引导去车店（优先于「安装」，也优先于「教程反问」）----
    ("这个教程看不懂", True, "kb", "kb:install_go_shop"),
    ("教程不对", True, "kb", "kb:install_go_shop"),
    ("视频不对，不是我要的", True, "kb", "kb:install_go_shop"),
    ("看了还是不会弄", True, "kb", "kb:install_go_shop"),
    ("挡杆教程不满意", True, "kb", "kb:install_go_shop"),
    # ---- 追加指令：客户【仍然】不满意 → 给两个选择（留言等店主 / 去车店）----
    ("还是不行", True, "kb", "kb:install_leave_msg", None, "", {"go_shop_sent": True}),
    ("还是不会弄", True, "kb", "kb:install_leave_msg", None, "", {"go_shop_sent": True}),
    ("教程还是看不懂", True, "kb", "kb:install_leave_msg", None, "",
     {"go_shop_sent": True, "leave_msg_sent": False}),
    # 已给过两个选择还在抱怨 → 静默，留给店主人工跟进
    ("还是不行", True, "ack", "安装不满意·已引导留言，转店主人工跟进", None, "",
     {"go_shop_sent": True, "leave_msg_sent": True}),

    ("在吗", False, "consult", None),
    ("你好", False, "consult", None),
    ("你好", True, "kb", "kb:greet_first"),        # 老客户打招呼

    # ========== 用户 2026-09-19 改口：退款/退货一律【静默】，等店主自己处理 ==========
    ("我要退款", True, "human", "退款"),
    ("怎么退货", True, "human", "退款"),
    ("我要退货退款", False, "human", "退款"),      # 新会话首句也必须静默（不能发对比图）
    ("能退货吗", True, "human", "退款"),
    ("教程不对，我要退款", True, "human", "退款"),   # 与教程同时出现 → 退款静默优先

    # ---- 需求4：客户「已了解」信号 → 不回复 ----
    ("嗯，我已了解", True, "ack", None),
    ("我已了解", True, "ack", None),
    ("1", True, "ack", None),
    ("好的", True, "ack", None),
    ("谢谢", True, "ack", None),
    ("好的，我要A款", True, "chosen", "A款脚踏"),        # 不能被当成客套而漏答
    ("质量好的吗", True, "kb", "kb:pedal_A_features"),   # 不能误判为「好的」

    # ---- 需求3：闲聊 / 库外 → 统一兜底话术 ----
    ("天气不错", True, "unknown_reply", None),
    ("你们老板是谁", True, "unknown_reply", None),

    # ---- 静默护栏（最高优先级） ----
    ("我要投诉", True, "human", "投诉"),
    ("再这样我就投诉了", True, "human", "投诉"),
    ("转人工", True, "human", "人工"),
    ("我要举报你们", True, "human", "举报"),

    # ---- 通用问答 ----
    ("多少钱", True, "kb", "kb:price_ask"),
    ("这个什么价格", True, "kb", "kb:price_ask"),
    ("能便宜点吗", True, "kb", "kb:price_bargain"),
    ("包邮吗", True, "kb", "kb:ship_fee"),
    ("哪里发货的", True, "kb", "kb:ship_from"),

    # ---- 定风翼堵盖 品类：教程反问【不能】抢走本品类（关键防错）----
    ("你好", False, "category", "定风翼堵盖", WING),
    ("发个实拍图看看", True, "category", "定风翼堵盖", WING),
    ("怎么安装", True, "kb", "kb:wingcover_install", WING),   # ← 不能被 install_ask 抢走
    ("有教程吗", True, "kb", "kb:wingcover_install", WING),   # ← 同上
    ("多少钱", True, "kb", "kb:price_ask", WING),
    ("定风翼堵盖多少钱", True, "kb", "kb:price_ask", WING),
    ("包邮吗", True, "kb", "kb:ship_fee", WING),
    ("我要退款", True, "human", "退款", WING),
    ("我要投诉", True, "human", "投诉", WING),
    ("今天股市怎么样", True, "unknown_reply", None, WING),
]

PASS = FAIL = 0
print("=" * 76)
print("意图判断自测（含类目路由 / 退款 / 已了解 / 兜底话术）")
print("=" * 76)
for case in CASES:
    # 支持 4~7 元组：
    # (消息, 我方有历史, 期望动作, 期望参数[, 类目信息][, 咨询商品文本][, 升级状态flags])
    text, hist, want_a, want_arg = case[0], case[1], case[2], case[3]
    cat_info = case[4] if len(case) > 4 else None
    goods = case[5] if len(case) > 5 else ""
    flags = case[6] if len(case) > 6 else None
    cat = cat_info[0] if cat_info else None
    cfg = cat_info[1] if cat_info else None

    a, arg = decide(text, hist, category=cat, cat_cfg=cfg, goods=goods, flags=flags)
    if isinstance(arg, dict):
        arg = "kb:" + str(arg.get("id"))
    elif isinstance(arg, tuple):
        arg = arg[0]
    ok = (a == want_a) and (want_arg is None or arg == want_arg)
    PASS += 1 if ok else 0
    FAIL += 0 if ok else 1
    _extra = (("｜商品=" + goods) if goods else "") + (
        "｜" + str(flags) if flags else "")
    print("%s 「%s」(历史=%s, 类目=%s%s) → %s %s   [期望 %s %s]" % (
        "✅" if ok else "❌", text, "有" if hist else "无", cat or "脚踏/默认",
        _extra, a, arg or "", want_a, want_arg or ""))

print("=" * 76)
print("通过 %d，失败 %d" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
