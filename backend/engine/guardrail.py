# -*- coding: utf-8 -*-
"""规则护栏：基于 kb.json 的确定性决策。
红线（投诉/退款/高危违规）绝不让 LLM 越权，宁可不回，不可回错。
"""
from .kb import detect_category, load_kb, match_kb, split_match

SILENT = "silent"   # 静默转人工（不回复，仅告警）
KB = "kb"           # 知识库规则命中
ACK = "ack"         # 客户已了解，不回复
PASS = "pass"       # 护栏放行，交 LLM

# 教程反问门只对脚踏/挡杆品类（或未识别品类）生效，防止抢走定风翼等其它品类
_INSTALL_OBJECT_WORDS = [
    "脚踏", "脚蹬", "踏板", "踩杆", "踩脚",
    "挡杆", "档杆", "换挡", "挂挡", "踩挡", "变速杆",
]
_GEAR_WORDS = ["挡杆", "档杆", "换挡", "挂挡", "踩挡", "变速杆"]
_INSTALL_KW = [
    "有没有安装教程", "有没有教程", "有教程吗", "有教程么",
    "有安装视频吗", "有安装视频么", "有教程", "教程吗", "教程呢",
    "教程", "怎么安装", "怎么装", "安装视频", "教学视频",
]


def _find_rule(kb, rid):
    for r in kb.get("rules", []):
        if r.get("id") == rid:
            return r
    return None


def _hit_any(text, words):
    t = (text or "").lower()
    for w in words or []:
        if w and str(w).lower() in t:
            return True
    return False


def check_ack(text, kb):
    """已了解信号：整句匹配 / 单字 / 短语包含"""
    sig = kb.get("_已了解信号", {})
    t = (text or "").strip()
    for s in sig.get("整句匹配", []):
        if t == s:
            return True
    for s in sig.get("单字", []):
        if t == s:
            return True
    if _hit_any(t, sig.get("短语包含", [])):
        return True
    return False


def check_install_ask(text, kb, category=None):
    """教程反问门：问教程但没说清对象 → 先反问「脚踏还是挡杆」。
    仅对脚踏/挡杆品类（或未识别品类）生效；对象已说清（含脚踏/挡杆等）→ 不走反问。
    """
    if category not in (None, "脚踏与挡杆"):
        return None
    for r in kb.get("rules", []):
        if r.get("id") == "install_ask":
            if _hit_any(text, split_match(r.get("match"))):
                if _hit_any(text, _INSTALL_OBJECT_WORDS):
                    return None  # 对象已说清 → 直接发对应安装教程（走通用规则）
                return r
    return None


def decide(text, kb=None):
    """护栏决策。返回 dict：
      action: silent / kb / ack / pass / none
      rule  : kb 命中时的规则对象
      reason: 决策原因（日志/前端展示用）
      trace : 决策链路（供前端「决策可视化」面板渲染）
    """
    kb = kb or load_kb()
    t = (text or "").strip()
    trace = []
    if not t:
        return {"action": "none", "reason": "空消息", "trace": trace}

    # ⓪ 静默护栏：投诉/纠纷/高危词 → 静默转人工
    human = kb.get("human_handoff_keywords", [])
    silent_kw = kb.get("_静默处理", {}).get("关键词", [])
    if _hit_any(t, human) or _hit_any(t, silent_kw):
        trace.append({"stage": "guardrail", "status": "block",
                      "detail": "命中投诉/纠纷类敏感词 → 静默转人工"})
        return {"action": SILENT, "reason": "命中投诉/纠纷类敏感词，静默转人工", "trace": trace}
    trace.append({"stage": "guardrail", "status": "pass", "detail": "未命中投诉/纠纷敏感词"})

    # 退款静默（涉及资金，交店主人工处理）
    refund_silent = kb.get("_静默处理", {}).get("退款静默", True)
    if refund_silent and _hit_any(t, kb.get("_静默处理", {}).get("退款关键词", [])):
        trace.append({"stage": "guardrail", "status": "block",
                      "detail": "退款/退货涉及资金 → 静默，交店主人工处理"})
        return {"action": SILENT, "reason": "退款/退货静默，交店主人工处理", "trace": trace}
    trace.append({"stage": "guardrail", "status": "pass", "detail": "非退款类消息"})

    # 品类识别（防跨品类发错货）
    category = detect_category(t, kb)
    trace.append({"stage": "category", "status": "hit" if category else "pass",
                  "detail": ("识别品类：%s" % category) if category else "未识别品类（全品类规则可用）"})

    # ① 教程反问门（优先于通用规则；仅脚踏/未定品类）
    install = check_install_ask(t, kb, category)
    if install:
        trace.append({"stage": "kb", "status": "hit",
                      "detail": "教程反问门命中 install_ask：对象未说清，先反问脚踏/挡杆"})
        return {"action": KB, "rule": install, "reason": "教程反问门命中: install_ask", "trace": trace}
    trace.append({"stage": "kb", "status": "pass",
                  "detail": "教程门：对象已说清或品类不适用，跳过反问"})

    # 通用知识库规则（priority=1 交易类优先；按品类过滤）
    rule = match_kb(t, kb, category)
    if rule:
        trace.append({"stage": "kb", "status": "hit",
                      "detail": "知识库规则命中：%s" % rule.get("id")})
        return {"action": KB, "rule": rule, "reason": "知识库规则命中: %s" % rule.get("id"), "trace": trace}
    trace.append({"stage": "kb", "status": "pass", "detail": "知识库未命中，放行给大模型"})

    # 已了解信号 → 不回复，避免骚扰
    if check_ack(t, kb):
        trace.append({"stage": "guardrail", "status": "hit",
                      "detail": "客户已了解信号 → 不回复，避免骚扰"})
        return {"action": ACK, "reason": "客户已了解，不回复", "trace": trace}

    trace.append({"stage": "guardrail", "status": "pass", "detail": "非已了解信号"})
    return {"action": PASS, "reason": "护栏未命中，交 LLM 处理", "trace": trace}
