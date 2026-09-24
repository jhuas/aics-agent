# -*- coding: utf-8 -*-
"""DeepSeek LLM 管道（OpenAI 兼容接口）"""
import json
import os

import requests

from .. import paths

CONFIG_FILE = os.path.join(paths.data_root(), "config.json")


def load_config():
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def has_key(config=None):
    config = config or load_config()
    return bool(config.get("deepseek_api_key", "").strip())


def call_llm(messages, config=None, timeout=25):
    """调用 DeepSeek chat completions。返回 (content, error)。"""
    config = config or load_config()
    key = config.get("deepseek_api_key", "").strip()
    if not key:
        return None, "API key 未配置：请在 backend/config.json 填写 deepseek_api_key"
    url = config.get("deepseek_base_url", "https://api.deepseek.com").rstrip("/") + "/chat/completions"
    payload = {
        "model": config.get("deepseek_model", "deepseek-chat"),
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 300,
        "stream": False,
    }
    try:
        resp = requests.post(
            url, json=payload,
            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
            timeout=timeout,
        )
        if resp.status_code != 200:
            return None, "DeepSeek API 错误 %s: %s" % (resp.status_code, resp.text[:200])
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip(), None
    except Exception as e:  # noqa: BLE001
        return None, "LLM 调用异常: %s" % e


def call_llm_json(messages, config=None, max_tokens=1600, temperature=0.2, timeout=60):
    """调用 DeepSeek 并要求 JSON 对象输出（命令工厂/方案生成用）。

    返回 (dict | None, error)。解析失败时返回 (None, None)。
    """
    config = config or load_config()
    key = config.get("deepseek_api_key", "").strip()
    if not key:
        return None, "API key 未配置：请在 backend/config.json 填写 deepseek_api_key"
    url = config.get("deepseek_base_url", "https://api.deepseek.com").rstrip("/") + "/chat/completions"
    payload = {
        "model": config.get("deepseek_model", "deepseek-chat"),
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
        "response_format": {"type": "json_object"},
    }
    try:
        resp = requests.post(
            url, json=payload,
            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
            timeout=timeout,
        )
        if resp.status_code != 200:
            return None, "DeepSeek API 错误 %s: %s" % (resp.status_code, resp.text[:200])
        data = resp.json()
        content = data["choices"][0]["message"]["content"].strip()
        return _extract_json(content), None
    except Exception as e:  # noqa: BLE001
        return None, "LLM 调用异常: %s" % e


def _extract_json(content):
    """兼容 markdown 围栏 / 前后缀噪声的 JSON 提取"""
    if content.startswith("```"):
        content = content.strip("`")
        if content.startswith("json"):
            content = content[4:]
        content = content.strip()
    try:
        return json.loads(content)
    except Exception:
        start, end = content.find("{"), content.rfind("}")
        if 0 <= start < end:
            try:
                return json.loads(content[start:end + 1])
            except Exception:
                return None
    return None


def _kb_facts(kb):
    """从 kb.json 提炼店铺知识摘要（供 LLM 参考，保持口径一致）"""
    lines = []
    cat = kb.get("_商品类目路由", {})
    for name, cfg in cat.items():
        if cfg.get("状态") != "ready":
            continue
        lines.append("【品类】%s：关键词 %s，话术：%s" % (
            name, "、".join(split_match(cfg.get("关键词"))[:6]), cfg.get("话术", "")[:100]))
    vid = kb.get("_视频映射", {})
    for k, v in vid.items():
        if k.startswith("_"):
            continue
        lines.append("【素材】%s → 素材库视频：%s" % (k, "、".join(v.get("素材库标题", []))))
    return "\n".join(lines)


def split_match(v):
    if isinstance(v, list):
        return [str(x) for x in v]
    if isinstance(v, str):
        return [x for x in v.split("|") if x]
    return []


def build_system_prompt(kb, store_name=""):
    store = store_name or kb.get("_店铺名", "本店")
    facts = _kb_facts(kb)
    return (
        "你是电商平台「%s」的 AI 客服助理。你的职责是亲切、简短地回复客户咨询，"
        "促成下单并维护店铺口碑。\n\n"
        "【硬性纪律，必须遵守】\n"
        "1. 回复不超过 60 字，口语化、亲切，带「亲」字头。\n"
        "2. 绝不出现：最/第一/顶级/全网最低等极限词（广告法风险）；微信/QQ/手机号/转账/私下交易/站外平台等违规内容。\n"
        "3. 不承诺做不到的事（如绝对包售后、无效退款）；不确定的信息就说帮您核实，不编造。\n"
        "4. 客户投诉、退款、纠纷：不争吵、不承诺，礼貌安抚后请客户留言，店主会人工处理。\n"
        "5. 涉及价格：以商品链接实际标价为准，不主动报价。\n"
        "6. 语气：像热情靠谱的店小二，但绝不油腔滑调。\n\n"
        "【店铺知识库（回答时优先参考，口径必须一致）】\n%s\n\n"
        "【当前店铺】%s"
    ) % (store, facts or "（暂无知识库配置）", store)


def build_messages(text, history, kb, config=None):
    """构造对话消息序列：系统提示 + 最近会话历史 + 当前问题"""
    config = config or load_config()
    store = config.get("store_name", "")
    sys_prompt = build_system_prompt(kb, store)
    messages = [{"role": "system", "content": sys_prompt}]
    for h in (history or [])[-8:]:
        role = h.get("role")
        if role in ("user", "assistant"):
            messages.append({"role": role, "content": h.get("text", "")})
    messages.append({"role": "user", "content": text})
    return messages
