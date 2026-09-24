# -*- coding: utf-8 -*-
"""
拼多多客服 · 全自动守护进程
================================================================
每 N 秒检查一次拼多多客服工作台，对『待回复』会话自动应答。
你离开电脑前启动它即可，之后无需人值守。

启动：双击 `启动全自动客服.bat`
单轮自检：python auto_keeper.py --once
预演模式：python auto_keeper.py --dry      （只判断不发送）
指定间隔：python auto_keeper.py --interval 30

停止：Ctrl+C，或直接关闭窗口

---------------- 安全策略（宁可不回，不可回错）----------------
1. 命中人工介入词（投诉/退款/举报/差评/人工…）→ 不回复，仅记录到日志
2. 无法识别的消息 → 不回复，仅记录（避免答错得罪客户）
3. 同一条消息已处理过 → 跳过（状态持久化，防刷屏）
4. 每轮之间强制间隔，避免触发平台风控
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
# 打包成 exe 后 __file__ 指向临时解包目录，必须改用 exe 所在目录（见 asset_path.app_dir）
try:
    import asset_path
    HERE = asset_path.app_dir()
except Exception:                                   # pragma: no cover
    pass
sys.path.insert(0, HERE)


def _KB_PATH():
    """
    kb.json 路径：优先 <程序目录>/kb.json（用户可改），否则用包内自带的（见 asset_path.kb_path）。
    打包成 exe 后即使 exe 旁边没放 kb.json 也能跑。
    """
    try:
        return asset_path.kb_path()
    except Exception:                               # pragma: no cover
        return os.path.join(HERE, "kb.json")

from pdd_send import (  # noqa: E402
    connect, ev, goto_workbench, open_chat_by_index, open_chat_by_match,
    list_pending_chats,
    get_last_customer_msg, send_text, send_mix_pair, send_images_batch,
    send_video, is_bot_paused, cleanup_overlays,
    get_consult_goods, match_category,
    collect_all_chats, open_chat_scroll_match, read_chat_messages,
)
from 款式识别 import pick_style_images, style_chosen_reply, SPEC_TEXT  # noqa: E402
from sensitive import sanitize  # noqa: E402

# ---------------- 记忆库（backend.memory） ----------------
# 源码模式：agent/ 的上级即项目根（ai-cs-agent/）；exe 模式：_MEIPASS/agent 的上级即 _MEIPASS。
# 两种模式 dirname(dirname(__file__)) 都是 backend 包所在根，确保 import backend.memory 可用。
try:
    _MEM_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _MEM_ROOT not in sys.path:
        sys.path.insert(0, _MEM_ROOT)
    from backend import memory as _memory  # noqa: E402
    try:
        from backend import session as _bsession  # noqa: E402
        _BS_OK = True
    except Exception:
        _bsession = None
        _BS_OK = False
    _MEM_OK = True
except Exception:                                    # pragma: no cover
    _memory = None
    _bsession = None
    _MEM_OK = False
    _BS_OK = False

_RE_REPLY_TXT = re.compile(r"话术=([^｜|]+)")


def _extract_reply_text(result):
    """从发送结果描述里提取实际话术（'…｜话术=xxx｜…'）"""
    m = _RE_REPLY_TXT.search(str(result or ""))
    return m.group(1).strip() if m else ""


def _mem_search(text):
    """库外问题查记忆库，命中返回记忆条目，否则 None。失败静默降级。"""
    if not _MEM_OK or not _memory:
        return None
    try:
        hits = _memory.search(text)
        return hits[0][0] if hits else None
    except Exception:                                # pragma: no cover
        return None


def _mem_learn(question, result):
    """真实发送成功后，把「客户问题 → 回复话术」增量记入记忆库。"""
    if not _MEM_OK or not _memory:
        return
    try:
        reply = _extract_reply_text(result)
        if reply:
            _memory.remember(question, reply, "live", "auto")
    except Exception:                                # pragma: no cover
        pass


# ---------------- 全量同步客服记录（CDP 逐一遍历 → 记忆库） ----------------
# 供驾驶舱「记忆库 → 一键同步客服记录」按钮调用（后台线程执行）。
# 通过 CDP 遍历客服工作台全部分组会话、滚动加载、逐一打开读完整聊天，
# 提取「客户问题→客服回复」问答对写入会话库 + 记忆库，解决「很多客服没同步」的问题。
SYNC_STATE = {
    "busy": False, "done": False, "start": None, "end": None,
    "total": 0, "scanned": 0, "learned": 0, "skipped": 0, "errored": 0,
    "pairs": 0, "last": "", "message": "",
}


def _sync_extract_pairs(msgs):
    """从完整消息序列里提取问答对：每个客户问题 → 其后的第一条客服回复。"""
    pairs = []
    for i in range(len(msgs) - 1):
        if msgs[i].get("role") != "user":
            continue
        q = (msgs[i].get("text") or "").strip()
        if not q:
            continue
        for j in range(i + 1, len(msgs)):
            if msgs[j].get("role") == "assistant":
                a = (msgs[j].get("text") or "").strip()
                if a:
                    pairs.append((q, a))
                break
    return pairs


def run_sync(max_convs=400):
    """
    ★ 完整遍历并同步所有客服会话记录到记忆库。

    与普通巡检不同：不再只看「当前面板可见会话」，而是滚动触发懒加载、
    跨全部分组收集全部会话，逐一打开读取完整聊天，把问答对写入会话库与记忆库。
    失败逐条捕获，绝不中断整体；全程写 SYNC_STATE 供前端轮询进度。
    返回 SYNC_STATE。
    """
    global SYNC_STATE
    if SYNC_STATE.get("busy"):
        return SYNC_STATE
    SYNC_STATE = {
        "busy": True, "done": False, "start": now(),
        "end": None, "total": 0, "scanned": 0, "learned": 0,
        "skipped": 0, "errored": 0, "pairs": 0, "last": "", "message": "正在遍历客服会话…",
    }
    try:
        log("🧠 开始全量同步客服记录（逐一读取，非仅当前面板）")
        chats = collect_all_chats(max_rounds=40)
        if not chats:
            SYNC_STATE.update(busy=False, done=True, end=now(),
                              message="未读取到任何会话：请确认已登录拼多多客服工作台")
            log("⚠️ 全量同步：未读取到会话（可能未登录工作台）")
            return SYNC_STATE
        SYNC_STATE["total"] = len(chats)
        log("🧠 遍历到 %d 个会话，开始逐一读取" % len(chats))
        for i, c in enumerate(chats):
            name, preview = c.get("name", ""), c.get("preview", "")
            SYNC_STATE["scanned"] = i + 1
            SYNC_STATE["last"] = name or "?"
            try:
                op = open_chat_scroll_match(name, preview)
                if not op.get("ok"):
                    SYNC_STATE["errored"] += 1
                    log("   ⌁ 会话 #%d %s 定位失败，跳过" % (i, name or "?"))
                    continue
                time.sleep(1.0)
                msgs = read_chat_messages()
                pairs = _sync_extract_pairs(msgs)
                if not pairs:
                    continue
                sid = "cdp_" + name
                for q, a in pairs:
                    SYNC_STATE["pairs"] += 1
                    if _BS_OK and _bsession:
                        try:
                            _bsession.append_message(
                                sid, "user", q,
                                {"channel": "cdp", "action": "sync", "source": "cdp_sync"})
                            _bsession.append_message(
                                sid, "assistant", a,
                                {"channel": "cdp", "action": "sync", "source": "cdp_sync"})
                        except Exception:
                            pass
                    if _MEM_OK and _memory and _memory.remember(q, a, "cdp_sync", "cdp_sync"):
                        SYNC_STATE["learned"] += 1
                    else:
                        SYNC_STATE["skipped"] += 1
            except Exception as e:
                SYNC_STATE["errored"] += 1
                log("   ✗ 会话 #%d %s 读取异常：%s" % (i, name or "?", str(e)[:120]))
            if (i + 1) % 20 == 0:
                log("   …进度 %d/%d，已学习 %d 条" % (i + 1, len(chats), SYNC_STATE["learned"]))
            time.sleep(1.0)  # 会话间留间隔，避免风控
        SYNC_STATE.update(busy=False, done=True, end=now(),
                          message="同步完成")
        log("🧠 全量同步完成：会话 %d｜新增记忆 %d｜重复/无效 %d｜异常 %d"
            % (len(chats), SYNC_STATE["learned"], SYNC_STATE["skipped"], SYNC_STATE["errored"]))
    except Exception as e:
        SYNC_STATE.update(busy=False, done=True, end=now(),
                          message="同步异常：" + str(e)[:160])
        log("✗ 全量同步异常：%s" % str(e)[:160])
        log(traceback.format_exc()[-500:])
    return SYNC_STATE

LOG_DIR = os.path.join(HERE, "logs")
STATE_FILE = os.path.join(LOG_DIR, "auto_state.json")
os.makedirs(LOG_DIR, exist_ok=True)


def _resolve_asset(path):
    """
    素材路径解析（打包/换电脑用）：
    本机绝对路径存在 → 原样返回；否则回退到「程序目录/素材/…」下的同名相对路径。
    详见 asset_path.py。任何异常都退回原路径，绝不因此中断自动回复。
    """
    if not path:
        return path
    try:
        import asset_path
        return asset_path.resolve(path)
    except Exception:
        return path


# ---------------- 运行统计（用于定期汇报） ----------------
STATS = {
    "start": None,
    "rounds": 0,
    "handled": 0,      # 自动回复成功次数
    "human": 0,        # 转人工告警次数
    "blocked": 0,      # 违规回复被拦截次数
    "unknown": 0,      # 无法识别未回复次数
    "errors": 0,       # 异常次数
    "alerts": [],      # 告警明细 [(时间, 内容)]
}
_last_report_hour = [None]

# ---------------- 规则配置 ----------------

# ① 人工介入词：命中即【不自动回复】
# ⚠️ 2026-09-19 用户要求：投诉与退款一律【静默】不自动回复，等店主自己处理。
#    词表可在 kb.json 的 `_静默处理` 里改（下面的常量只是兜底默认值）。
HUMAN_KW = [
    "投诉", "12315", "举报", "差评", "人工", "纠纷", "转人工",
    "维权", "消协", "工商", "骗子", "假货", "起诉", "曝光", "差评师",
]

# ② 客户要实拍图的信号
WANT_IMG_KW = ["实拍图", "实拍照片", "看图片", "看图", "发图片", "发图", "照片", "细节图"]

# ③ 要安装视频的信号
INSTALL_KW = ["安装", "怎么装", "怎么安", "教程", "装不上", "不会装"]

# ③b 安装对象细分（2026-09-17 新增）：客户问的是【挡杆】还是【脚踏】。
#    起因：客户说「这是脚踏的不是挡杆的，我要的是挡杆的安装教程」，
#    程序却又发了一遍脚踏视频 → 客户体验差。现在按对象路由不同视频。
GEAR_KW = ["挡杆", "档杆", "换挡", "挂挡", "踩挡", "挡杠", "变速杆"]

# ③c 脚踏侧的对象词（2026-09-19 新增，配合「教程反问」判断客户回答）
PEDAL_KW = ["脚踏", "踏板", "脚蹬", "踩脚"]

# ③d 客户「都要」的表达 → 脚踏 + 挡杆两套视频一起发
BOTH_KW = ["都要", "全都", "两个都", "两样都", "都发", "都来", "都想要", "各来"]

# ③e 「教程反问后，客户的回答」里不该出现别的意图词（防误判）。
#     起因：反问「脚踏还是挡杆」后，客户若回「脚踏多少钱」，
#     不能因为含「脚踏」就发安装视频 —— 那是价格问题。
ANSWER_BLOCK_KW = [
    "多少钱", "价格", "报价", "包邮", "运费", "邮费", "发货", "物流", "快递",
    "优惠", "便宜", "退款", "退货", "投诉", "实拍", "图片", "照片", "图",
]
#     回答通常很短；超过这个长度就认为不是「一句话回答」。
ANSWER_MAX_LEN = 20

# ④ 售后退款/退货信号
#    2026-09-15：统一按「同意退货后再退款」自动回复。
#    ⚠️ 2026-09-19 用户改口：涉及退款按【静默】处理，等店主自己处理
#       （kb.json `_静默处理.退款静默` = true）。把该开关改成 false 即可恢复自动回话术。
REFUND_KW = ["退款", "退货", "退回", "退换", "要退", "申请退", "退了吧", "能退", "无理由"]

# ⑤ 客户「已了解」信号 → 不再回复（避免骚扰）。优先级低于选款/安装/退款。
#    具体词表从 kb.json 的 `_已了解信号` 读取，用户可自行增删。
ACK_SINGLE_RE = re.compile(r"^[1１]\s*[.。!！~～]*$")   # 单发一个「1」

# ⑥ 选款信号 → (正则, 款式)
STYLE_PATTERNS = [
    (re.compile(r"[aA]\s*款|第一[款个]|前面那[款个]|上面那[款个]|左边那[款个]|这[款个]好看"), "A款脚踏"),
    (re.compile(r"[bB]\s*款|第二[款个]|后面那[款个]|下面那[款个]|右边那[款个]"), "B款脚踏"),
]

# ⑦ 素材库视频标题（安装类兜底；正常走 kb.json 的 _视频映射）
INSTALL_VIDEO_TITLE = "脚踏板安装"
GEAR_INSTALL_VIDEO_TITLE = "挡杆安装通用教程"

# 脚踏安装视频必附的「通用说明」（消除车型适配顾虑）。可在 kb.json
# _视频映射['脚踏安装']['通用说明话术'] 覆盖；此处仅为缺省兜底。
PEDAL_UNIVERSAL_TEXT = "亲，我们脚踏板都是通用的，只是根据不同车型的连接件不同"


def _kb_text(key, default=""):
    """从 kb.json 读取一段配置（如 _无法回复话术 / _已了解信号）"""
    try:
        with open(_KB_PATH(), encoding="utf-8") as f:
            return json.load(f).get(key) or default
    except Exception:
        return default


_ACK_CFG = _kb_text("_已了解信号", {}) or {}
ACK_EXACT = _ACK_CFG.get("整句匹配") or ["嗯，我已了解", "我已了解", "已了解", "了解了"]
ACK_PREFIX = _ACK_CFG.get("短语包含") or ["好的", "嗯嗯", "谢谢", "收到", "ok", "OK"]

# ①b 「静默护栏」配置（kb.json `_静默处理`）
#     用户 2026-09-19 要求：投诉与退款都不自动回复，交店主人工处理。
#     改这里（或改 kb.json）即可调整词表；退款静默改成 false 可恢复「同意退货后再退款」自动回话术。
_SILENT_CFG = _kb_text("_静默处理", {}) or {}
if _SILENT_CFG.get("关键词"):
    HUMAN_KW = list(_SILENT_CFG["关键词"])
if _SILENT_CFG.get("退款关键词"):
    REFUND_KW = list(_SILENT_CFG["退款关键词"])
REFUND_SILENT = bool(_SILENT_CFG.get("退款静默", True))


def is_ack(text):
    """
    客户是否表示『已了解』→ 程序不再回复。
    判定从严，避免误伤：
      · 单发一个「1」（可带标点）
      · 整句匹配词（如「我已了解」）且整条消息 ≤10 字
      · 以客套词开头（如「好的」「谢谢」）且整条消息 ≤6 字
    这样「好的，我要A款」「质量好的吗」等不会被误判，仍能正常选款/回答。
    """
    s = (text or "").strip().strip("。.!！~～,，、 ")
    if not s:
        return False
    if ACK_SINGLE_RE.match(s):
        return True
    if len(s) <= 10 and any(k in s for k in ACK_EXACT):
        return True
    if len(s) <= 6 and any(s.startswith(k) for k in ACK_PREFIX):
        return True
    return False


# ---------------- 事件上报（驾驶舱 JSONL） ----------------
EVENT_FILE = None  # 由 --event-file 指定；为空时不写


def _event(typ, **kw):
    """写一条结构化事件（供 Vue 驾驶舱实时展示 / 回放）。失败不影响主流程。"""
    if not EVENT_FILE:
        return
    try:
        rec = {"t": typ, "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        rec.update(kw)
        with open(EVENT_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ---------------- 日志 ----------------

def log(msg, also_print=True):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = "[%s] %s" % (ts, msg)
    if also_print:
        print(line, flush=True)
    day = datetime.datetime.now().strftime("%Y-%m-%d")
    with open(os.path.join(LOG_DIR, "auto_%s.log" % day), "a", encoding="utf-8") as f:
        f.write(line + "\n")
    _event("log", msg=msg)


def add_alert(msg):
    """登记一条告警（会进入小时报告）"""
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    STATS["alerts"].append((ts, msg))
    log("     🚨 %s" % msg)


def write_hourly_report():
    """生成本小时的运行报告（追加到 logs/report_YYYY-MM-DD.md）"""
    now_dt = datetime.datetime.now()
    day, hour = now_dt.strftime("%Y-%m-%d"), now_dt.strftime("%H")
    path = os.path.join(LOG_DIR, "report_%s.md" % day)
    lines = [
        "",
        "## %s:00 - %s:59 运行报告" % (hour, hour),
        "| 项目 | 数量 |",
        "|---|---|",
        "| 巡检轮次 | %d |" % STATS["rounds"],
        "| 自动回复成功 | %d |" % STATS["handled"],
        "| 转人工告警 | %d |" % STATS["human"],
        "| 拦截违规回复 | %d |" % STATS["blocked"],
        "| 无法识别(未回复) | %d |" % STATS["unknown"],
        "| 异常 | %d |" % STATS["errors"],
    ]
    if STATS["alerts"]:
        lines.append("")
        lines.append("**告警明细：**")
        for t, m in STATS["alerts"][-30:]:
            lines.append("- `%s` %s" % (t, m))
    else:
        lines.append("")
        lines.append("**告警明细：** 无")
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    log("📊 已生成小时报告 → %s" % path)

    for k in ("rounds", "handled", "human", "blocked", "unknown", "errors"):
        STATS[k] = 0
    STATS["alerts"].clear()


def maybe_hourly_report():
    """跨过整点则输出上一小时报告"""
    h = datetime.datetime.now().strftime("%Y-%m-%d %H")
    if _last_report_hour[0] is None:
        _last_report_hour[0] = h
        return
    if h != _last_report_hour[0]:
        write_hourly_report()
        _last_report_hour[0] = h


# ---------------- 状态（防重复回复） ----------------

def load_state():
    if os.path.isfile(STATE_FILE):
        try:
            with open(STATE_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_state(st, dry=False):
    """保存巡检去重状态。

    ⚠️ 2026-09-19 修正：**预演模式（--dry）绝不写盘**。
    实测 `--dry` 会把「（预演）将执行 category」以及 human 判定写进 auto_state.json，
    而 state 是「这条消息已处理过」的去重表 —— 一旦被预演污染，
    真实启动时对应客户会被误判为「已处理」而**漏回**。
    """
    if dry:
        return
    # 只保留最近 500 条，防止无限增长
    if len(st) > 500:
        for k in list(st.keys())[:-500]:
            st.pop(k, None)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)


def msg_key(name, text, salt=""):
    """
    消息去重键。

    ⚠️ 2026-09-15：拼多多侧栏昵称是**掩码**（两字昵称一律显示 `**`），
    不同客户可能同名；若只用「昵称+文本」，两个客户同时发「你好」会互相顶掉，
    导致其中一个永远得不到回复（正是本次"客户消息没回"的同类故障）。
    故把侧栏显示的最后消息时间并入键，保证跨会话唯一。
    """
    return hashlib.md5(((name or "") + "|" + (text or "") + "|" + (salt or ""))
                       .encode("utf-8")).hexdigest()[:16]


# ---------------- 安全发送（敏感词过滤） ----------------

def safe_send_text(text, tag=""):
    """
    发送文字前统一过敏感词过滤。
    - 命中极限词 → 自动替换为安全表述
    - 命中高危词（微信/QQ/转账/私下交易…）→ 拦截，不发送，转人工
    返回发送结果描述。
    """
    safe, blocked, replaced = sanitize(text)
    if blocked:
        STATS["blocked"] += 1
        add_alert("回复含高危词 %s → 已拦截，转人工" % blocked)
        log("     🚫 含高危词 %s → 拦截不发送" % blocked)
        return "BLOCKED:%s" % blocked
    if replaced:
        log("     🔧 极限词已替换为安全表述：%s" % replaced)
    return send_text(safe)


# ---------------- 知识库匹配 ----------------

def load_kb_rules():
    kb = _KB_PATH()
    try:
        with open(kb, encoding="utf-8") as f:
            return json.load(f).get("rules", []) or []
    except Exception:
        return []


# 「仅由 decide() 按意图直接调用的规则」→ 不参与通用 match_kb 关键词匹配。
# ⚠️ install_ask 的关键词是「教程 / 怎么安装」这类极通用的词，
#    若参与通用匹配，会把「定风翼堵盖怎么安装」抢成脚踏教程反问（发错品类）。
INTERNAL_RULES = {"install_ask"}


def match_kb(text, exclude_ids=None):
    """
    匹配知识库规则。评分 = (priority, 最长命中关键词长度, 命中关键词个数)，取最高者。

    - priority：规则在 kb.json 里可选字段 `"priority": 1`（默认 0）。
      价格/包邮/发货等「交易类」问答设为 1，确保「定风翼堵盖多少钱」优先答价格，
      而不是被商品介绍规则抢走。
    - 个数：命中关键词越多越具体。如「定风翼怎么安装」命中 wingcover_fit(1个)
      与 wingcover_install(2个) → 取后者。
    - exclude_ids：排除某些规则（如按品类路由时排除脚踏专属规则）。
    - INTERNAL_RULES：无论何时都不参与通用匹配（见上方说明）。

    返回 (rule, 命中关键词) 或 (None, None)
    """
    tl = (text or "").lower()
    exclude = exclude_ids or ()
    best_rule, best_kw, best_score = None, None, (-1, -1, -1)
    for r in load_kb_rules():
        if r.get("id") in exclude or r.get("id") in INTERNAL_RULES:
            continue
        hits = [kw for kw in (r.get("match") or []) if kw.lower() in tl]
        if not hits:
            continue
        longest = max(hits, key=len)
        score = (int(r.get("priority", 0) or 0), len(longest), len(hits))
        if score > best_score:
            best_rule, best_kw, best_score = r, longest, score
    return best_rule, best_kw


# 「脚踏/挡杆」专属规则：非脚踏类会话（如定风翼堵盖/短尾）不得误用
PEDAL_RULES = {
    "style_guide", "pedal_A", "pedal_B", "pedal_A_chosen", "pedal_B_chosen",
    "pedal_install", "pedal_A_real", "pedal_A_package", "pedal_A_features",
    "shifter_fit",
}


def get_session_category(fallback_text=""):
    """
    读取当前会话咨询商品的类目（用于按品类路由，避免把脚踏素材发给定风翼客户）。

    两级判定：
      ① 读会话商品卡片（title/spec）→ match_category
      ② 卡片读不到时，用**客户消息文本**兜底（如客户直接说「定风翼堵盖多少钱」）
    返回 (类目名, 路由配置)，都判不出时返回 (None, {})。
    """
    try:
        g = get_consult_goods() or {}
        cat, cfg = match_category(g.get("title", ""), g.get("spec", ""))
        if cat:
            return cat, (cfg or {})
        if fallback_text:
            cat, cfg = match_category(fallback_text)
            if cat:
                return cat, (cfg or {})
        return None, {}
    except Exception:
        return None, {}


# ---------------- 意图判断 ----------------

def kb_rule_by_id(rid):
    """按 id 取 kb.json 的规则（用于把某条规则绑定到固定意图）"""
    for r in load_kb_rules():
        if r.get("id") == rid:
            return r
    return None


def get_session_goods_text():
    """
    当前会话【咨询商品】的「标题 + 规格」文本。
    用途：判断客户是从哪个商品链接进来的（如「车型特殊标记」黑旗600）。
    读不到返回 ""。
    """
    try:
        g = get_consult_goods() or {}
        return " ".join(str(g.get(k) or "") for k in ("title", "spec")).strip()
    except Exception:
        return ""


def _special_install_key(goods_text):
    """
    指令二（2026-09-17）：客户咨询商品含「车型特殊标记」→ 返回专用 _视频映射 键，否则 None。
    标记表在 kb.json 的 `_车型特殊标记`，如 {"黑旗600": "黑旗600挡杆安装"}。
    比较前统一去掉空白，避免「黑旗 600」这类渲染差异导致漏判。
    """
    cfg = _kb_text("_车型特殊标记", {}) or {}
    g = re.sub(r"\s+", "", goods_text or "")
    if not g:
        return None
    for mark, key in cfg.items():
        if str(mark).startswith("_") or not key:
            continue
        if re.sub(r"\s+", "", str(mark)) in g:
            return key
    return None


def _install_target(text, goods="", allow_goods_infer=True):
    """
    判断客户要的是【脚踏】还是【挡杆】的教程 → 返回 _视频映射 的键。
      返回 "脚踏安装" / "挡杆安装" / "黑旗600挡杆安装" 或 ["脚踏安装","挡杆安装"]（两者都要）
      判断不出返回 None（→ 走反问）。

    优先级：客户正文明确说出的对象 > 车型特殊标记 > 咨询商品推断。
    参数 allow_goods_infer=False 时不用「咨询商品」兜底推断 ——
    用于「已反问过、等客户回答」的场景，避免客户问别的事（如「发个实拍图」）
    时因为商品是脚踏就被误发安装视频。
    """
    t = text or ""
    g = (goods or "") if allow_goods_infer else ""
    has_gear = any(k in t for k in GEAR_KW)
    has_pedal = any(k in t for k in PEDAL_KW)
    # 「都要」→ 两套一起发。注意：不能只要「脚踏/挡杆都出现」就判定都要 ——
    # 客户常说「这是脚踏的、不是挡杆的，我要挡杆教程」，此时应只发挡杆（沿用旧逻辑：挡杆优先）。
    both = any(k in t for k in BOTH_KW) or (
        has_gear and has_pedal
        and any(c in t for c in ("和", "跟", "与", "还有", "以及")))
    gear_key = _special_install_key((goods or "") + " " + t) or "挡杆安装"

    if both:
        return ["脚踏安装", gear_key]
    if has_gear:
        return gear_key
    if has_pedal:
        return "脚踏安装"
    # 客户没说对象 → 看车型特殊标记（如只说「黑旗600」）
    spec = _special_install_key(g + " " + t)
    if spec:
        return spec
    # 再看咨询商品本身是脚踏还是挡杆
    if g:
        if any(k in g for k in GEAR_KW):
            return "挡杆安装"
        if any(k in g for k in PEDAL_KW):
            return "脚踏安装"
    return None


def _looks_like_object_answer(text):
    """
    反问了「脚踏还是挡杆」之后，这条消息是否算「客户的回答」。
    判据从严，避免把别的问题当成回答：
      · 必须提到 脚踏/踏板/脚蹬 或 挡杆/档杆…（或「都要」）
      · 不能同时带着价格/退款/实拍等别的意图词
      · 长度 ≤ ANSWER_MAX_LEN（回答通常很短，如「挡杆的」「脚踏 我的车是XX」）
    """
    t = (text or "").strip()
    if not t or len(t) > ANSWER_MAX_LEN:
        return False
    if any(k in t for k in ANSWER_BLOCK_KW):
        return False
    if any(k in t for k in BOTH_KW):
        return True
    return any(k in t for k in GEAR_KW + PEDAL_KW)


def _unsat_kw():
    """
    「对安装教程不满意」的信号词表 = install_go_shop 与 install_leave_msg 两级
    规则 match 的**并集**。

    ⚠️ 必须取并集：升级级别的词（如「还是不行」）只在 install_leave_msg 里，
    若只取第一级，带升级词的抱怨会绕过前面的升级判定、直接掉到知识库匹配，
    导致「已引导留言」这一档永远触发不到。
    """
    kws = []
    for rid in ("install_go_shop", "install_leave_msg"):
        r = kb_rule_by_id(rid) or {}
        for k in (r.get("match") or []):
            if k not in kws:
                kws.append(k)
    return kws


def session_sent_contains(needle):
    """
    当前会话【我方已发消息】里是否包含某段文字。
    用途：判断「去车店」话术是不是已经说过 → 决定是否升级到「留言 / 去车店」两个选择。

    实现：直接读 DOM 历史（我方消息容器 = .cs-item），无需额外状态文件，
    也不会因为昵称掩码、进程重启而失准。
    """
    if not needle:
        return False
    ws = connect()
    try:
        js = r"""(function(){
var n=%(n)s;
return [].slice.call(document.querySelectorAll('.msg-list .onemsg')).some(function(e){
  if(!e.querySelector('.cs-item')) return false;
  var c=e.cloneNode(true);
  try{ c.querySelectorAll('.nickname,.message-time').forEach(function(x){x.remove();}); }catch(err){}
  return (c.innerText||'').indexOf(n)>=0;
});})()""" % {"n": json.dumps(needle, ensure_ascii=False)}
        return bool(ev(ws, js))
    except Exception:
        return False


def _sent_any(marker):
    """marker 可为字符串或字符串列表；任一在本会话我方消息里出现过即 True。"""
    if not marker:
        return False
    items = marker if isinstance(marker, list) else [marker]
    return any(session_sent_contains(x) for x in items if x)


def get_install_flags():
    """
    每次巡检读一次会话历史，得到本次判断需要的全部「已经说过/发过」状态：
      go_shop_sent    已引导去摩托车维修店（不满意第 1 档已发）
      leave_msg_sent  已给「留言等店主 / 去车店」两个选择（第 2 档已发）
      tut_asked       已发过「脚踏还是挡杆的教程？」反问
      tut_video_sent  已发过安装教程视频（脚踏或挡杆任一）
    标记取自 kb.json 的 `_升级标记`，都是对应话术里的原样子串。
    """
    m = _kb_text("_升级标记", {}) or {}
    return {
        "go_shop_sent": _sent_any(m.get("去车店已发")),
        "leave_msg_sent": _sent_any(m.get("留言已发")),
        "tut_asked": _sent_any(m.get("教程反问已发")),
        "tut_video_sent": _sent_any(m.get("教程视频已发")),
    }


def decide(text, has_history, category=None, cat_cfg=None, goods="", flags=None):
    """
    根据客户消息决定动作。
    返回 (action, arg)：
      human         不自动回复（投诉/退款 → 静默，交店主人工处理，仅告警）
      category      按商品类目发素材（定风翼堵盖 / 短尾等非脚踏品类）
      images  A/'B'/'?'   客户要实拍图；'?' = 未指明款式 → 反问车型与商品
      chosen  A/'B'  客户选定款式 → 发对应款实拍视频
      install  _视频映射键  '脚踏安装' / '挡杆安装' / '黑旗600挡杆安装'
                            （2026-09-17 细分：挡杆发 3 个视频；含「黑旗600」标记时换第一个）
                            也可以是列表 → 脚踏+挡杆两套一起发（客户说「都要」）
      kb      rule  命中知识库（含 install_ask 反问、对教程不满意→去车店→「留言/去车店」两个选择）
      consult       新咨询 → 发 A B混合 + 引导话术
      ack           客户「已了解」（含单发 1）→ 不再回复
      unknown_reply 库外 / 闲聊 → 回复统一兜底话术
      none          不回复（仅空消息）

    参数：
      goods  当前会话咨询商品标题+规格（用于「车型特殊标记」，如黑旗600）
      flags  会话状态 {'go_shop_sent','leave_msg_sent','tut_asked','tut_video_sent'}
             由 get_install_flags() 读会话历史得出。

    优先级（2026-09-19 调整）：
      ⓪ 静默护栏（投诉/退款 → 不回复，店主自己处理）
      ① 教程咨询门 ← 【用户 2026-09-19 新命令·优先执行】
           问教程但没说清「脚踏还是挡杆」→ 先反问（kb:install_ask），不发视频；
           说清了（正文提到脚踏/挡杆，或咨询商品能判断）→ 直接发对应教程视频；
           反问后客户回答「脚踏 / 挡杆 / 车型」→ 直接发对应视频。
      ② 非脚踏品类路由 ③ 要图 ④ 选款 ⑤ 退款（仅退款静默=false 时）
      ⑥ 对教程不满意升级 ⑦ 安装兜底 ⑧ 已了解 ⑨ 新会话开场 ⑩ 知识库 ⑪ 兜底
    """
    t = (text or "").strip()
    if not t:
        return ("none", None)

    fl = flags or {}

    # ⓪ 静默护栏（用户 2026-09-19：投诉和退款一律【不自动回复】，等店主自己处理）
    for k in HUMAN_KW:
        if k in t:
            return ("human", k)
    if REFUND_SILENT:
        for k in REFUND_KW:
            if k in t:
                return ("human", "退款")

    # ① 教程咨询门（优先于其它内容规则；非「脚踏/挡杆」品类不适用，避免发错货）
    if category in (None, "脚踏与挡杆"):
        is_tut = any(k in t for k in INSTALL_KW)
        # 「这个教程看不懂」之类 → 让给 ⑥ 不满意升级流程，不走反问
        if is_tut and any(k in t for k in _unsat_kw()):
            is_tut = False
        awaiting = bool(fl.get("tut_asked")) and not fl.get("tut_video_sent")
        if is_tut or (awaiting and _looks_like_object_answer(t)):
            # is_tut 时才允许用「咨询商品」推断对象；等回答时只认客户正文，防误发
            target = _install_target(t, goods, allow_goods_infer=is_tut)
            if target:
                return ("install", target)
            if is_tut:
                # 对象没说清 → 反问「脚踏还是挡杆 + 车型」
                rule = kb_rule_by_id("install_ask")
                return ("kb", rule) if rule else ("unknown_reply", None)

    # ② 非「脚踏/挡杆」类目（定风翼堵盖 / 短尾）→ 按该品类路由，
    #     绝不能用脚踏的选款/发图/安装视频去回答，否则发错货。
    if category and category != "脚踏与挡杆":
        cfg = cat_cfg or {}
        ready = (cfg.get("动作") in ("send_images", "send_mix_pair")
                 and not str(cfg.get("状态", "")).startswith("pending"))
        # 新进线（我方从未发言）或客户明确要看实物图 → 发本品类素材 + 开场话术
        if ready and (not has_history or any(k in t for k in WANT_IMG_KW)):
            return ("category", (category, cfg))
        rule, _kw = match_kb(t, exclude_ids=PEDAL_RULES | INTERNAL_RULES)
        if rule:
            return ("kb", rule)
        # 未命中 → 统一兜底话术（用户要求：不沉默）
        return ("unknown_reply", None)

    # ③ 客户要实拍图（未指明款式 → 反问车型与所购商品）
    if any(k in t for k in WANT_IMG_KW):
        style = match_style(t)
        return ("images", style or "?")

    # ④ 客户选定款式
    style = match_style(t)
    if style:
        return ("chosen", style)

    # ⑤ 售后退款 / 退货
    #    ⚠️ 2026-09-19 起默认【静默】（见 ⓪，REFUND_SILENT=true），本分支仅在
    #       把 kb.json `_静默处理.退款静默` 改回 false 时才生效（恢复自动回统一口径）。
    if any(k in t for k in REFUND_KW):
        rule, _kw = match_kb("退款")
        if rule:
            return ("kb", rule)

    # ⑥ 客户对安装教程「不满意」→ 分两级升级（2026-09-17 用户指令一 + 追加指令）
    #    必须放在「安装」之前：「这个教程不对」里含「教程」，否则会被当成重新索取视频。
    #      第 1 次不满意 → 引导去就近摩托车维修店（install_go_shop）
    #      仍然不满意   → 给两个选择：① 留言等店主晚上回复 ② 去车店找师傅（install_leave_msg）
    #      已给过两个选择还在抱怨 → 不再回复（已让客户留言，交给店主晚上处理，避免刷屏）
    if any(k in t for k in _unsat_kw()):
        if fl.get("leave_msg_sent"):
            # 已引导留言 → 静默，留给店主人工跟进（避免反复刷同样的话）
            return ("ack", "安装不满意·已引导留言，转店主人工跟进")
        rid = "install_leave_msg" if fl.get("go_shop_sent") else "install_go_shop"
        rule = kb_rule_by_id(rid)
        if rule:
            return ("kb", rule)

    # ⑦ 问安装（兜底：正常情况下已在 ① 教程咨询门处理掉）
    #    ⚠️ 同时命中「不满意」词时不发视频，避免给正在抱怨的客户再发一遍安装视频。
    if any(k in t for k in INSTALL_KW) and not any(k in t for k in _unsat_kw()):
        target = _install_target(t, goods)
        return ("install", target or "脚踏安装")

    # ⑧ 客户「已了解」（含单发一个 1）→ 不再回复。
    #     放在选款/安装/退款之后，避免「好的，我要A款」被当成客套而漏答。
    if is_ack(t):
        return ("ack", None)

    # ⑨ 新咨询（本会话我方从未回复过）→ 发对比图开场
    if not has_history:
        return ("consult", None)

    # ⑩ 知识库匹配（价格/包邮/发货地/规格/材质等常见问答）
    rule, kw = match_kb(t, exclude_ids=INTERNAL_RULES)
    if rule:
        return ("kb", rule)

    # ⑪ 库外 / 闲聊 → 回复统一兜底话术（用户 2026-09-15 要求，不再沉默）
    return ("unknown_reply", None)


def match_style(text):
    for pat, style in STYLE_PATTERNS:
        if pat.search(text):
            return style
    return None


# ---------------- 执行动作 ----------------

def do_action(action, arg, dry=False):
    """执行动作，返回结果描述。所有文字均过敏感词过滤后再发送。"""
    if dry:
        return "（预演）将执行 %s %s" % (action, arg if isinstance(arg, str) else "")

    if action == "consult":
        txt = ("亲，咱家脚踏有 A款 和 B款 两个款式哦～ 我发您两张对比图，"
               "您看下更喜欢哪一款，告诉我就行～")
        r1 = safe_send_text(txt)
        r2 = send_mix_pair()
        return "发对比图开场｜话术=%s｜图片=%s" % (r1, r2.replace("\n", " "))

    if action == "chosen":
        style = arg if arg in ("A款脚踏", "B款脚踏") else "A款脚踏"
        titles = _video_titles_for(style)
        reply = style_chosen_reply(style, media="video")
        out = ["话术=" + safe_send_text(reply)]
        for t in titles:
            out.append(send_video(t))
        return "发【%s】视频｜%s" % (style, "｜".join(out))

    if action == "images":
        if arg not in ("A款脚踏", "B款脚踏"):
            # 用户 2026-09-15 要求：未指明款式时不再沉默，改为追问车型与所购商品
            ask = ("亲，您想看哪一款的实拍图呀？麻烦告诉我您的【车型】，"
                   "以及您要了解的是哪一款商品～ 咱们脚踏有 A款 和 B款 两个款式，"
                   "我按您的需求发对应的实拍图或视频给您～")
            return "客户要图但未指明款式 → 追问车型/商品｜话术=" + safe_send_text(ask)
        imgs = pick_style_images(arg, 2)
        reply = style_chosen_reply(arg, media="image")
        out = ["话术=" + safe_send_text(reply)]
        if imgs:
            out.append("图片=" + send_images_batch(imgs).replace("\n", " "))
        return "发【%s】实拍图｜%s" % (arg, "｜".join(out))

    if action == "ack":
        # 客户表示「已了解」→ 不再回复，只记录
        log("     💬 客户已了解 → 不再回复")
        return "客户已了解（含单发 1）→ 不回复"

    if action == "unknown_reply":
        # 库外 / 闲聊 → 统一兜底话术（用户要求，不再沉默）
        txt = _kb_text("_无法回复话术", "亲，我无法进行回复，请您见谅～")
        return "库外/闲聊 → 兜底话术｜话术=" + safe_send_text(txt)

    if action == "memory":
        # 记忆库命中 → 复用历史回复（过敏感词过滤）
        txt = safe_send_text(arg if isinstance(arg, str) else "")
        if not txt:
            return "记忆回复为空 → 不发"
        send_text(txt)
        return "记忆库回复｜话术=" + txt

    if action == "install":
        # arg = _视频映射 的键：'脚踏安装' / '挡杆安装' / '黑旗600挡杆安装'
        #       （兼容旧值 '脚踏' / '挡杆'）；也可以是列表 → 两套依次发（客户说「都要」）
        keys = arg if isinstance(arg, list) else [arg if isinstance(arg, str) and arg else "脚踏安装"]
        keys = [k for k in keys if k]
        if not keys:
            keys = ["脚踏安装"]
        out, desc = [], []
        for i, key in enumerate(keys):
            if key in ("脚踏", "挡杆"):
                key += "安装"
            vmap = _video_map(key)
            is_gear = "挡杆" in key
            if is_gear:
                titles = vmap.get("素材库标题") or [GEAR_INSTALL_VIDEO_TITLE]
            else:
                titles = vmap.get("素材库标题") or [INSTALL_VIDEO_TITLE]
            if not isinstance(titles, list):
                titles = [titles]
            # 发【脚踏安装】视频时必附「通用说明」（客户常担心车型不适配）；
            # 挡杆不适用。话术可在 kb.json 改，缺省用内置兜底。
            if not is_gear:
                uni = vmap.get("通用说明话术") or PEDAL_UNIVERSAL_TEXT
                out.append("通用说明=" + safe_send_text(uni))
            # 话术只发第一条的，避免两套视频连发两条意思相同的话
            if i == 0:
                txt = vmap.get("话术")
                if not txt:
                    rule, _ = match_kb("安装教程", exclude_ids=INTERNAL_RULES)
                    txt = (rule.get("answer") if rule
                           else "亲，我发您安装教程视频，里面有安装步骤和注意点，照着做就行～")
                out.append("话术=" + safe_send_text(txt))
            for t in titles:
                out.append(send_video(t))
            desc.append("【%s】%d 个视频" % (key, len(titles)))
        return "发安装教程（%s）｜%s" % (" + ".join(keys), "｜".join(out))

    if action == "category":
        cat, cfg = arg if isinstance(arg, tuple) else (arg, {})
        cfg = cfg or {}
        d = _resolve_asset(cfg.get("素材目录", ""))
        exts = (".jpg", ".jpeg", ".png", ".webp")
        imgs = sorted(os.path.join(d, f) for f in os.listdir(d)
                      if f.lower().endswith(exts)) if os.path.isdir(d) else []
        out = []
        talk = cfg.get("话术", "")
        if talk:
            out.append("话术=" + safe_send_text(talk))
        else:
            out.append("话术=(未配置)")
        if imgs:
            out.append("图片=" + send_images_batch(imgs).replace("\n", " "))
        else:
            out.append("⚠️ 素材目录为空: %s" % (d or "-"))
        return "品类【%s】开场｜%s" % (cat, "｜".join(out))

    if action == "kb":
        rule = arg or {}
        txt = rule.get("answer", "")
        out = ["话术=" + safe_send_text(txt)]
        # 知识库若带图片素材，一并发送
        for m in (rule.get("media") or []):
            if m.get("type") == "image" and m.get("path"):
                out.append("图片=" + send_images_batch(
                    [_resolve_asset(m["path"])]).replace("\n", " "))
        return "知识库[%s]｜%s" % (rule.get("id", "?"), "｜".join(out))

    return "无动作"


def _video_map(key):
    """读取 kb.json 的 `_视频映射[key]` 整条配置（含 素材库标题 / 话术）"""
    kb = _KB_PATH()
    try:
        with open(kb, encoding="utf-8") as f:
            return (json.load(f).get("_视频映射", {}) or {}).get(key) or {}
    except Exception:
        return {}


def _video_titles_for(style):
    """读取 kb.json 的 _视频映射 → 该款式要发的素材库标题列表"""
    t = _video_map(style).get("素材库标题") or []
    return t if isinstance(t, list) else [t]


def has_my_history():
    """
    当前会话我方是否已有发言（用于判断是否为新咨询）。

    ⚠️ 2026-09-15 修正：不能用「文本里含『主账号』」判断——
    客户发的【引用消息】里会带上被引用的我方昵称『主账号：』，
    会被误判成"我方已发言"，导致新会话开场话术（A B混合对比图）发不出去。
    正确判据：消息容器 `.cs-item` = 我方（与 get_last_customer_msg 保持一致）。
    """
    ws = connect()
    try:
        n = ev(ws, r"""[...document.querySelectorAll('.msg-list .onemsg')]
          .filter(function(e){ return !!e.querySelector('.cs-item'); }).length""")
        return bool(n and int(n) > 0)
    finally:
        ws.close()


# ---------------- 单轮巡检 ----------------

def run_once(dry=False):
    STATS["rounds"] += 1
    # 0) 确保工作台在前面
    try:
        goto_workbench()
    except Exception as e:
        log("⚠️ 工作台不可用：%s" % str(e)[:120])
        return 0

    try:
        cleanup_overlays()
    except Exception:
        pass

    pending = list_pending_chats()
    if not pending:
        log("巡检：当前面板无可见会话")
        _event("round", pending=0)
        return 0

    log("巡检：可见会话 %d 个 → %s" % (
        len(pending),
        ", ".join("#%d %s%s" % (c["idx"], c["name"],
                                "(%s)" % (c.get("title") or c.get("group") or "")[:6]
                                if (c.get("title") or c.get("group")) else "")
                  for c in pending)))
    _event("round", pending=len(pending))

    handled = 0
    st = load_state()

    for c in pending:
        idx, name = c["idx"], c["name"]
        preview = c.get("preview", "")
        try:
            # ⚠️ 不用序号定位：回复一条后侧栏会重排，序号会指向别的客户。
            #    改为「昵称+预览」实时重新定位，定位不到就跳过本轮（下轮再处理）。
            op = open_chat_by_match(name, preview)
            if not op.get("ok"):
                log("  #%d %s → 会话已移动/定位不到，跳过（下轮重试）" % (idx, name))
                continue
            time.sleep(1.0)

            last = get_last_customer_msg()
            if not last.get("found"):
                log("  #%d %s → 无有效消息，跳过" % (idx, name))
                continue
            if last.get("is_me"):
                log("  #%d %s → 最后一条是我方消息，跳过" % (idx, name))
                continue

            text = last.get("text", "")
            # 新键带会话时间（跨会话唯一）；旧键仅作向后兼容，避免升级后重复回复
            k = msg_key(name, text, c.get("time", ""))
            k_legacy = msg_key(name, text)
            if st.get(k) or st.get(k_legacy):
                log("  #%d %s → 该消息已处理过，跳过" % (idx, name))
                continue

            # 判断（先读会话商品类目，按品类路由，避免发错品类素材）
            hist = has_my_history()
            cat, cat_cfg = get_session_category(text)
            goods = get_session_goods_text()
            # 安装不满意处理的升级状态（读会话历史判断哪一档话术已经说过）
            try:
                flags = get_install_flags()
            except Exception:
                flags = {}
            action, arg = decide(text, hist, category=cat, cat_cfg=cat_cfg,
                                 goods=goods, flags=flags)
            # 记忆层：库外/闲聊问题先查记忆库，命中则复用历史回复（比统一兜底更贴心）
            if action == "unknown_reply":
                mem = _mem_search(text)
                if mem:
                    action, arg = "memory", mem.get("reply", "")
                    log("     🧠 记忆库命中：%s" % mem.get("question", "")[:40])
            _event("decision", session=name, text=text[:120], category=cat,
                   action=action, arg=arg if isinstance(arg, str) else "+".join(arg) if isinstance(arg, list) else "")
            log("  #%d %s | 客户消息：%s" % (idx, name, text[:60]))
            _mark = _special_install_key((goods or "") + " " + text)
            log("     → 品类=%s｜我方有历史=%s｜咨询商品=%s%s｜已发去车店=%s/留言=%s｜已反问教程=%s/已发教程视频=%s｜判定动作：%s %s" % (
                cat or "(未识别)", hist, (goods[:40] or "(未读到)"),
                ("｜⚑车型标记→%s" % _mark) if _mark else "",
                flags.get("go_shop_sent"), flags.get("leave_msg_sent"),
                flags.get("tut_asked"), flags.get("tut_video_sent"),
                action,
                arg if isinstance(arg, str) else
                ("+".join(arg) if isinstance(arg, list) else "")))

            if action == "human":
                STATS["human"] += 1
                _event("human", session=name, reason=arg, refund=(arg == "退款"))
                if arg == "退款":
                    # 用户 2026-09-19：退款/退货一律静默，等店主自己处理
                    add_alert("会话#%d %s 命中退款/退货 → 已静默未回复，等店主人工处理"
                              % (idx, name))
                else:
                    add_alert("会话#%d %s 命中人工介入词「%s」→ 未回复，需人工处理"
                              % (idx, name, arg))
                log("     ⏸ 已跳过，等待人工处理")
                st[k] = {"at": now(), "action": "human"}
                save_state(st, dry)
                continue

            if action == "none":
                STATS["unknown"] += 1
                _event("unknown", session=name)
                log("     ⏭ 无法识别 → 不回复（避免答错）")
                st[k] = {"at": now(), "action": "none"}
                save_state(st, dry)
                continue

            if action == "ack":
                _event("ack", session=name)
                if isinstance(arg, str) and arg:
                    log("     💬 %s → 不回复" % arg)
                else:
                    log("     💬 客户已了解（或单发 1）→ 不回复")
                st[k] = {"at": now(), "action": "ack"}
                save_state(st, dry)
                continue

            # ⚠️ 不再自动点『立即恢复接待』。
            # 那会开启拼多多自带的客服机器人，导致「平台机器人 + 本程序」双重回复，
            # 平台机器人还可能给出错误话术。这里只记录，不点击。
            try:
                if is_bot_paused():
                    log("     ℹ️ 平台机器人处于『暂停接待』（正常，避免与我们抢答）")
            except Exception:
                pass

            res = do_action(action, arg, dry=dry)
            _event("send", session=name, action=action,
                   arg=arg if isinstance(arg, str) else "+".join(arg) if isinstance(arg, list) else "",
                   dry=dry, result=res[:200])
            log("     ✅ %s" % res)
            st[k] = {"at": now(), "action": action, "arg": arg, "result": res[:200]}
            save_state(st, dry)
            handled += 1
            STATS["handled"] += 1
            if not dry:
                # 真实发送成功 → 增量学习（把本次问答记入记忆库）
                _mem_learn(text, res)

            time.sleep(2)  # 会话间留间隔，避免风控
        except Exception as e:
            STATS["errors"] += 1
            log("  ❌ #%d %s 处理异常：%s" % (idx, name, str(e)[:160]))
            log(traceback.format_exc()[-600:])

    return handled


def resume_reception():
    """点击『立即恢复接待』（机器人被平台暂停时）"""
    ws = connect()
    try:
        ev(ws, r"""(function(){
var els=[...document.querySelectorAll('*')].filter(function(e){
  var t=(e.innerText||'').trim();
  return /立即恢复接待/.test(t) && t.length<40;});
if(els.length){try{els[els.length-1].click();}catch(e){}
  var p=els[els.length-1].parentElement;
  if(p){try{p.click();}catch(e){}}}
return els.length;})()""")
        time.sleep(1.5)
    finally:
        ws.close()


def now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------------- 主循环 ----------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=int, default=30,
                    help="轮询间隔秒数（默认30，用户 2026-09-15 指定）")
    ap.add_argument("--once", action="store_true", help="只巡检一轮后退出")
    ap.add_argument("--dry", action="store_true", help="预演：只判断不发送")
    ap.add_argument("--report", action="store_true", help="立即生成一份运行报告后退出")
    ap.add_argument("--event-file", default=None, help="结构化事件 JSONL 输出路径（驾驶舱用）")
    args = ap.parse_args()

    global EVENT_FILE
    EVENT_FILE = args.event_file

    if args.report:
        write_hourly_report()
        print("报告已生成，见 logs/ 目录")
        return

    STATS["start"] = now()
    _event("status", state="running", interval=args.interval, dry=args.dry)
    log("=" * 56)
    log("🤖 全自动客服已启动｜间隔 %d 秒%s" % (args.interval, "｜预演模式" if args.dry else ""))
    log("   停止：在本窗口按 Ctrl+C")
    log("   敏感词过滤：已启用（极限词自动替换 / 高危词拦截）")
    log("   定期汇报：每整点生成 logs/report_YYYY-MM-DD.md")
    log("=" * 56)

    round_no = 0
    while True:
        round_no += 1
        round_start = time.time()          # 用于把本轮耗时从间隔里扣除
        try:
            n = run_once(dry=args.dry)
            if n:
                log("本轮完成，已自动回复 %d 个会话" % n)
        except KeyboardInterrupt:
            log("已手动停止。")
            _event("status", state="stopped")
            break
        except Exception as e:
            STATS["errors"] += 1
            log("⚠️ 本轮异常（将自动重试）：%s" % str(e)[:200])

        # 跨整点 → 输出上小时报告
        try:
            maybe_hourly_report()
        except Exception:
            pass

        if args.once:
            log("--once 模式，退出。")
            _event("status", state="stopped", reason="once")
            break

        # 目标节奏：每 args.interval 秒巡检一次 —— 本轮已用掉的时间从间隔里扣除，
        # 这样「巡检」是真正每 30 秒一次，而不是「耗时 + 30 秒」。
        # 下限 5 秒：万一某轮耗时超过间隔，也不能立刻连刷（防平台风控）。
        _elapsed = time.time() - round_start
        _wait = max(5.0, args.interval - _elapsed)
        try:
            time.sleep(_wait)
        except KeyboardInterrupt:
            log("已手动停止。")
            _event("status", state="stopped")
            break


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已停止。")
