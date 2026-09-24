# -*- coding: utf-8 -*-
"""
商品款式识别 & 素材路由模块
============================
客户从商品详情页进线时，会话顶部会显示当前咨询的商品。
本模块负责：识别客户咨询的是哪一款 → 返回该款对应的实拍图/实拍视频/安装视频目录。

款式视觉特征（⭐ 2026-09-14 实战纠正，以【实测素材图】为准）：
  A款脚踏：品牌标【MOTO-MOAK】（白字黑底方块）；板面为密集【斜向防滑条纹】；
           四角圆润的加大椭圆板；板面斜向银色/镂空装饰条；亮光黑金属边框；
           通常为【单独脚踏】，不含前后踩挡杆。
           ※ 素材：实拍图/A款实拍图（MOTO-MOAK 斜纹，与 CU625 AMT亮光黑 主图一致）
  B款脚踏：品牌标【MOOKO】；板面为直纹 + 长条凹槽造型；
           通常以【脚踏 + 前后踩挡杆】整套总成形式呈现；亮光黑。
           ※ 素材：实拍图/B款实拍图（MOOKO 直纹，带前后踩挡杆总成）

一句话区分：斜纹防滑条 + MOTO-MOAK 标 = A款；直纹凹槽 + MOOKO 标 + 带前后踩挡杆总成 = B款。

⚠️ 重要教训（2026-09-14 实战踩坑）：
   不能仅凭规格文字里的「亮光黑」「AMT自动挡」等关键词判款！
   客户咨询商品「无极CU625脚踏AMT自动挡款（亮光黑）」，主图实为 MOTO-MOAK 斜纹款 = A款，
   但旧逻辑见"亮光黑/AMT"就判 B款，导致连发 B款素材，客户两次反馈"这不是我要的那款脚踏"。
   ✅ 正确做法：进线后**先目视会话顶部商品主图的花纹**，按花纹/品牌标判款，规格文字只作辅助。

用法：
    from 款式识别 import identify_by_title, get_media_dirs
    style = identify_by_title("魔克无极CU625改装加大防滑脚踏 前后踩挡杆加宽配件脚踩踏板")
    dirs = get_media_dirs(style)
"""
import json
import os

# 程序目录 / 素材根目录：优先用 asset_path（支持打包成 exe、支持换电脑回退到 素材/ 目录）。
# 万一 asset_path.py 不在（被单独拷走某个文件），退回原来的本机绝对路径，保证不崩。
try:
    import asset_path
    BASE_DIR = asset_path.app_dir()
    CUSTOMER_DATA_ROOT = asset_path.data_root()
    KB_FILE = asset_path.kb_path()
except Exception:                                   # pragma: no cover
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    # 客服资料根目录（用户 2026-09-14 新建）
    CUSTOMER_DATA_ROOT = r"D:\work\客服资料"
    KB_FILE = os.path.join(BASE_DIR, "kb.json")


def _load_rules():
    with open(KB_FILE, encoding="utf-8") as f:
        return json.load(f).get("_商品识别规则", {})


def _match_style(title, rules):
    """按商品标题关键词判定款式。标题命中优先。"""
    t = (title or "").lower()

    # 1) 显式款式词
    if any(k in t for k in ("b款", "亮光黑", "亮黑", "纯黑", "am t", "amt")):
        # AMT/自动挡款 对应亮光黑 B款
        if "b款" in t or "亮光黑" in t or "亮黑" in t or "纯黑" in t or "amt" in t:
            return "B款脚踏"
    if any(k in t for k in ("a款", "硅胶")):
        return "A款脚踏"

    # 2) 按标题里的材质/结构描述推断
    if any(k in t for k in ("亮光黑", "亮面", "光面")):
        return "B款脚踏"
    if any(k in t for k in ("防滑", "硅胶")):
        return "A款脚踏"

    # 3) 黑旗600 专属
    if "黑旗" in t or "黑600" in t:
        return "黑旗600脚踏挡杆"

    # 4) 兜底：加大铝合金脚踏默认按 A 款
    if "脚踏" in t or "脚蹬" in t or "踏板" in t:
        return "A款脚踏"
    return None


def identify_by_title(title, spec=""):
    """
    根据商品【标题】+【规格文字】返回款式名。

    ⚠️ 注意：本函数只做「文字兜底」判断，准确率有限！
    实战证明规格里的「亮光黑/AMT自动挡」与款式（A/B）**没有必然对应关系**
    （CU625 AMT亮光黑 主图实为 A款）。因此：
      - 首选：进线后目视会话顶部商品主图，按版花/品牌标判款（准确）
      - 本函数：仅当拿不到主图时兜底，且默认偏向 A款（单独脚踏，最常见）

    title: 商品标题
    spec:  会话中显示的商品规格，例如「无极CU625脚踏AMT自动挡款（亮光黑）」
    返回：B款脚踏 / A款脚踏 / 黑旗600脚踏挡杆 / None
    """
    combined = ((title or "") + " " + (spec or "")).lower()

    # 黑旗600 专属（标题明确命中）
    if "黑旗" in combined or "黑600" in combined:
        return "黑旗600脚踏挡杆"

    # 只有标题/规格里**显式**写了 "b款"，才敢判 B款
    if "b款" in combined:
        return "B款脚踏"
    if "a款" in combined:
        return "A款脚踏"

    # 其余一律兜底 A款（A款是单独脚踏款，覆盖大多数常规咨询）
    if any(k in combined for k in ("脚踏", "脚蹬", "踏板")):
        return "A款脚踏"
    return None


def get_media_dirs(style):
    """返回该款式对应的素材目录字典"""
    if not style:
        return {}
    rules = _load_rules()
    info = rules.get(style) or {}
    return {
        "style": style,
        "实拍图": info.get("实拍图") or info.get("素材目录", {}).get("实拍图", ""),
        "实拍视频": info.get("实拍视频") or info.get("素材目录", {}).get("实拍视频", ""),
        "安装视频": info.get("安装视频") or info.get("素材目录", {}).get("安装视频", ""),
        "视觉特征": info.get("视觉特征", ""),
        "区分要点": info.get("区分要点", ""),
    }


def list_media(style):
    """列出该款式目录下的实际文件（实拍图/实拍视频/安装视频）"""
    dirs = get_media_dirs(style)
    out = {"style": style, "实拍图": [], "实拍视频": [], "安装视频": []}
    for label in ("实拍图", "实拍视频", "安装视频"):
        d = dirs.get(label)
        if d and os.path.isdir(d):
            out[label] = sorted(
                f for f in os.listdir(d)
                if os.path.isfile(os.path.join(d, f))
                and not f.startswith(".")
            )
    return out


# ---------------- 规格话术（A/B 两款一致） ----------------
SPEC_TEXT = "规格：长 21cm × 10cm，净重约 1100g，含快递箱约 1290g。"

# 款式未明时先发的对比图目录
MIX_DIR = os.path.join(CUSTOMER_DATA_ROOT, "实拍图", "A B混合")
MIX_IMAGES = ["A款脚踏实拍图1.jpg", "B款脚踏挡杆实拍 (4).jpg"]

# 客户选定后的款名 → 实拍图目录
STYLE_IMAGE_DIR = {
    "A款脚踏": os.path.join(CUSTOMER_DATA_ROOT, "实拍图", "A款实拍图"),
    "B款脚踏": os.path.join(CUSTOMER_DATA_ROOT, "实拍图", "B款实拍图"),
}

# 款名 → 本地实拍视频目录（用于自动上传到素材库）
A_VIDEO_DIR = os.path.join(CUSTOMER_DATA_ROOT, "实拍视频", "A款脚踏实拍视频")
B_VIDEO_DIR = os.path.join(CUSTOMER_DATA_ROOT, "实拍视频", "B款脚踏实拍视频")
STYLE_VIDEO_DIR = {
    "A款脚踏": A_VIDEO_DIR,
    "B款脚踏": B_VIDEO_DIR,
}


def get_mix_images():
    """返回「A B混合」对比图的绝对路径列表（款式未明时先发）"""
    return [os.path.join(MIX_DIR, f) for f in MIX_IMAGES
            if os.path.isfile(os.path.join(MIX_DIR, f))]


def ask_style_reply():
    """客户咨询但款式未明时的开场：发对比图 + 询问要哪款"""
    return ("亲，咱家脚踏有 A款 和 B款 两个款式哦～ 我发您两张对比图，"
            "您看下更喜欢哪一款，告诉我就行～")


def pick_style_images(style, n=2, seed=None):
    """
    按客户选定的款式，从对应实拍图目录随机取 n 张。
    style: 'A款脚踏' / 'B款脚踏'
    返回：绝对路径列表
    """
    import random
    d = STYLE_IMAGE_DIR.get(style)
    if not d or not os.path.isdir(d):
        return []
    files = sorted(
        f for f in os.listdir(d)
        if os.path.isfile(os.path.join(d, f)) and not f.startswith(".")
        and f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
    )
    if not files:
        return []
    rng = random.Random(seed)
    picked = rng.sample(files, min(n, len(files)))
    return [os.path.join(d, f) for f in picked]


def style_chosen_reply(style, media="video"):
    """
    客户选定款式后的回复话术（含规格）。
    media="video" → 发视频场景（默认）；media="image" → 发图片场景。
    """
    if style == "A款脚踏":
        head = "好嘞～ 这是咱们 A款 MOTO-MOAK 亮光黑加大脚踏，板面斜纹防滑条设计，抓脚防滑，加宽加大踩着更稳更舒服。"
    elif style == "B款脚踏":
        head = "好嘞～ 这是咱们 B款亮光黑加大脚踏（带前后踩挡杆总成），直纹凹槽板面，质感强、耐脏好打理。"
    else:
        head = "好嘞～"
    tail = ("我发您一段这款的实拍视频看下效果～ 您是什么车型？我帮您确认能不能装。"
            if media == "video" else
            "我发您两张实拍图看下细节～ 您是什么车型？我帮您确认能不能装。")
    return head + SPEC_TEXT + tail


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        title = sys.argv[1]
    else:
        title = "魔克无极CU625改装加大防滑脚踏 前后踩挡杆加宽配件脚踩踏板"
    style = identify_by_title(title)
    print("标题：", title)
    print("识别款式：", style)
    print(json.dumps(list_media(style), ensure_ascii=False, indent=2))
