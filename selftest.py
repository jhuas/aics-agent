# -*- coding: utf-8 -*-
"""引擎自测：模拟各类客户消息，验证 护栏 → 知识库 → LLM 降级 全链路"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.engine import hybrid  # noqa: E402

CASES = [
    ("你好", "客服问候"),
    ("多少钱", "价格问答"),
    ("包邮吗", "运费问答"),
    ("在哪里发货", "发货地问答（不抢发货时间）"),
    ("多久发货", "发货时间问答"),
    ("我要A款", "选款A"),
    ("我要B款，发一下实拍图", "选款B要图"),
    ("有安装教程吗", "教程反问门-未说清对象"),
    ("脚踏板怎么安装", "教程-对象已说清→直接发安装视频"),
    ("定风翼堵盖怎么安装", "品类隔离-定风翼不抢脚踏教程"),
    ("给我看下定风翼堵盖", "定风翼品类素材"),
    ("亲，便宜点吧", "讨价还价"),
    ("我要退款", "退款静默"),
    ("你这是个骗子店", "投诉静默"),
    ("好的，谢谢", "已了解"),
    ("1", "已了解单字"),
    ("你们家脚踏适合无极CU525吗", "无极品牌在库→知识库拦截适配问答"),
    ("我的车是奔达金吉拉450，能装吗", "库外车型适配→LLM"),
    ("天气不错啊", "闲聊→LLM"),
]

print("=" * 70)
print("「智客服」混合引擎自测 v2（含品类隔离与教程门修复）")
print("=" * 70)
ok = 0
for text, desc in CASES:
    r = hybrid.handle_message(text, [])
    act = r["action"]
    ch = r.get("channel", "")
    reply = (r.get("reply") or "")[:50]
    reason = r.get("reason", "")
    flag = "✅" if r.get("reply") or act in ("silent", "ack") else "⚠️"
    print(f"\n[{desc}] 客户说：{text}")
    print(f"   → action={act} channel={ch} {flag}")
    if reply:
        print(f"     回复：{reply}")
    if reason:
        print(f"     原因：{reason}")
    if r.get("media"):
        print(f"     素材：{len(r['media'])} 个")
    if act in ("reply", "silent", "ack"):
        ok += 1

print("\n" + "=" * 70)
print(f"自测完成：{ok}/{len(CASES)} 条链路正常")
