# -*- coding: utf-8 -*-
"""混合决策引擎：规则护栏 → 记忆库 → DeepSeek LLM → 敏感词合规"""
from . import llm
from .. import memory
from .guardrail import ACK, KB, PASS, SILENT, decide
from .kb import load_kb
from .sensitive import sanitize


def _trace_sensitive(safe, blocked, replaced):
    """敏感词合规阶段追踪"""
    if blocked:
        return {"stage": "sensitive", "status": "block",
                "detail": "命中高危词被拦截（%s）→ 禁止发送" % "、".join(blocked)}
    if replaced:
        return {"stage": "sensitive", "status": "warn",
                "detail": "替换极限词 %d 处：%s" % (len(replaced), "、".join(replaced[:5]))}
    return {"stage": "sensitive", "status": "pass", "detail": "内容合规，无敏感词"}


def _kb_reply(rule, trace):
    reply = rule.get("answer", "")
    media = rule.get("media") or []
    safe, blocked, replaced = sanitize(reply)
    trace.append(_trace_sensitive(safe, blocked, replaced))
    if blocked:
        return {"action": "silent", "reply": None, "escalate": True,
                "reason": "回复命中高危词被拦截: %s" % blocked, "channel": "sensitive",
                "trace": trace}
    return {"action": "reply", "reply": safe, "media": media, "escalate": False,
            "rule": rule.get("id"), "channel": "kb", "replaced": replaced, "trace": trace}


def _fallback_reply(kb, err=None, trace=None):
    trace = trace or []
    trace.append({"stage": "llm", "status": "skip",
                  "detail": "大模型未参与（%s）→ 使用兜底话术" % (err or "未启用")})
    fb = kb.get("fallback", "亲，您的问题已收到，正在为您查询，请稍等片刻～")
    out = {"action": "reply", "reply": fb, "media": [], "escalate": False,
           "channel": "fallback", "trace": trace}
    if err:
        out["llm_error"] = err
    return out


def _memory_reply(text, trace):
    """记忆库检索：库外问题若有高度相似的历史问答，直接复用历史回复（LLM 之前）。"""
    hits = memory.search(text)
    if not hits:
        trace.append({"stage": "memory", "status": "miss",
                      "detail": "记忆库无高度相似问答（阈值 %.2f）→ 继续" % memory.HIT_MIN})
        return None
    item, score = hits[0]
    reply = item.get("reply", "")
    safe, blocked, replaced = sanitize(reply)
    trace.append({"stage": "memory", "status": "hit",
                  "detail": "命中记忆「%s」相似度 %.2f（历史回复第 %d 次复用）" %
                            (item.get("question", "")[:24], score, item.get("hits", 0) + 1)})
    trace.append(_trace_sensitive(safe, blocked, replaced))
    if blocked:
        return {"action": "silent", "reply": None, "escalate": True,
                "reason": "记忆回复命中高危词被拦截: %s" % blocked, "channel": "sensitive",
                "trace": trace}
    memory.record_hit(item)
    return {"action": "reply", "reply": safe, "media": [], "escalate": False,
            "channel": "memory", "memory_id": item.get("id"), "replaced": replaced, "trace": trace}


def _llm_reply(text, history, kb, config, trace):
    trace.append({"stage": "llm", "status": "hit",
                  "detail": "调用 DeepSeek 大模型生成回复（模型：%s）" % config.get("deepseek_model", "deepseek-chat")})
    messages = llm.build_messages(text, history, kb, config)
    reply, err = llm.call_llm(messages, config)
    if reply is None:
        trace.append({"stage": "llm", "status": "warn",
                      "detail": "大模型调用失败：%s" % (err or "未知错误")})
        return _fallback_reply(kb, err, trace)
    safe, blocked, replaced = sanitize(reply)
    trace.append(_trace_sensitive(safe, blocked, replaced))
    if blocked:
        return {"action": "silent", "reply": None, "escalate": True,
                "reason": "LLM 回复命中高危词被拦截: %s" % blocked, "channel": "sensitive",
                "trace": trace}
    return {"action": "reply", "reply": safe, "media": [], "escalate": False,
            "channel": "llm", "replaced": replaced, "trace": trace}


def handle_message(text, history=None, config=None, kb=None):
    """核心入口：输入客户消息 → 返回决策结果 dict（含 trace 决策链路）。"""
    kb = kb or load_kb()
    config = config or llm.load_config()
    decision = decide(text, kb)
    action = decision["action"]
    trace = list(decision.get("trace", []))

    if action == SILENT:
        return {"action": "silent", "reply": None, "escalate": True,
                "reason": decision.get("reason"), "channel": "guardrail", "trace": trace}
    if action == ACK:
        return {"action": "ack", "reply": None, "escalate": False,
                "reason": decision.get("reason"), "channel": "guardrail", "trace": trace}
    if action == KB:
        return _kb_reply(decision["rule"], trace)

    # PASS → 记忆库（历史问答复用）→ LLM
    if not config.get("enable_llm", True) and not config.get("enable_memory", True):
        return _fallback_reply(kb, "LLM 与记忆均已禁用", trace)
    if config.get("enable_memory", True):
        mem_decision = _memory_reply(text, trace)
        if mem_decision:
            return mem_decision
    if not config.get("enable_llm", True):
        return _fallback_reply(kb, "LLM 已禁用", trace)
    if not llm.has_key(config):
        return _fallback_reply(kb, "API key 未配置", trace)
    return _llm_reply(text, history or [], kb, config, trace)
