# -*- coding: utf-8 -*-
"""电商主图采集器（商家参考图库）

合规与模式说明：
- 演示模式：本地生成占位参考图，不发起任何网络请求，解压即用、离线可演示。
- CDP 截图模式（真实）：复用调试浏览器(127.0.0.1:9222)中商家已登录的会话，
  自动打开目标商品主图页并截图真实主图 PNG 入库。仅截取商品页主图区域，
  内容仅供商家内部选品参考，遵守 robots.txt 与请求频率，不采集用户隐私。
- 官方开放平台 API 模式：需配置各平台开放平台密钥（预留适配层）。
"""
import base64
import hashlib
import json
import os
import time
import urllib.parse
import urllib.request

from . import settings
from ..cdp_browser import ensure_debug_browser

# 各平台商品搜索页地址（复用调试浏览器中已登录的会话）
_PLATFORM_SEARCH = {
    "taobao": "https://s.taobao.com/search?q=__KW__",
    "jd": "https://search.jd.com/Search?keyword=__KW__&enc=utf-8",
    "pdd": "https://mobile.yangkeduo.com/search_result.html?search_key=__KW__",
    "douyin": "https://www.douyin.com/search/__KW__?type=general",
}
# 商品主图 CDN 特征（命中则判定为可截图商品图，避免截到小图标）
_PLATFORM_IMG_RE = {
    "taobao": "alicdn.com|taobaocdn.com",
    "jd": "360buyimg.com|jd.com",
    "pdd": "pddpic.com|/n\\d+\\.jpg",
    "douyin": "douyinpic.com|douyinstatic|p\\d+-sign",
}
_GENERIC_IMG_RE = r"\.(jpg|jpeg|png|webp)(\?|$)"

_cdp_id = [0]


class ImageReferenceCrawler:
    """主图采集器 —— 商家参考图库"""

    def __init__(self):
        self.cfg = settings
        self.save_dir = settings.REFERENCE_IMAGES_DIR
        os.makedirs(self.save_dir, exist_ok=True)
        self.meta_file = os.path.join(self.save_dir, "index.json")
        self.index = self._load_index()

    # ---------- 基础工具 ----------
    def _load_index(self):
        try:
            with open(self.meta_file, encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except Exception:
            return []

    def _save_index(self):
        with open(self.meta_file, "w", encoding="utf-8") as f:
            json.dump(self.index, f, ensure_ascii=False, indent=2)

    # ---------- 演示模式：本地造数（离线） ----------
    @staticmethod
    def _palette(category: str):
        """按品类生成稳定的双色配色（主色/辅色）"""
        h = int(hashlib.md5(category.encode()).hexdigest()[:6], 16)
        hue = h % 360
        c2 = (hue + 40) % 360
        return f"hsl({hue},72%,55%)", f"hsl({c2},70%,42%)"

    def _write_svg(self, path, title, palette, platform):
        c1, c2 = palette
        tag = {"taobao": "淘宝", "jd": "京东", "pdd": "拼多多", "douyin": "抖音"}.get(platform, platform)
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="800" '
            f'viewBox="0 0 800 800"><defs><linearGradient id="g" x1="0" y1="0" '
            f'x2="1" y2="1"><stop offset="0" stop-color="{c1}"/><stop offset="1" '
            f'stop-color="{c2}"/></linearGradient></defs>'
            '<rect width="800" height="800" fill="url(#g)"/>'
            '<rect x="60" y="60" width="680" height="680" rx="40" fill="none" '
            'stroke="rgba(255,255,255,.45)" stroke-width="6"/>'
            f'<text x="400" y="380" font-family="Microsoft YaHei,sans-serif" font-size="64" '
            'font-weight="bold" fill="#fff" text-anchor="middle">'
            f'{title}</text>'
            f'<text x="400" y="460" font-family="Microsoft YaHei,sans-serif" font-size="40" '
            'fill="rgba(255,255,255,.92)" text-anchor="middle">参考主图 · {tag}</text>'
            f'<text x="400" y="560" font-family="Microsoft YaHei,sans-serif" font-size="28" '
            'fill="rgba(255,255,255,.7)" text-anchor="middle">演示模式本地生成</text>'
            "</svg>"
        )
        with open(path, "w", encoding="utf-8") as f:
            f.write(svg)

    def _demo_crawl(self, platform, category, keyword, limit):
        results = []
        palette = self._palette(category or keyword or "通用")
        for i in range(int(limit)):
            title = f"{keyword or category or '通用'}·参考{i + 1}"
            name = hashlib.md5(
                f"{platform}:{category}:{keyword}:{i}:{time.time()}".encode()
            ).hexdigest()[:16] + ".svg"
            path = os.path.join(self.save_dir, name)
            if not os.path.exists(path):
                self._write_svg(path, title, palette, platform)
            rec = {
                "file": name,
                "local_path": path,
                "source_url": "demo://local",
                "platform": platform,
                "category": category,
                "title": title,
                "price": f"¥{80 + i * 17 % 400}",
                "size_kb": round(os.path.getsize(path) / 1024, 1),
                "crawled_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "demo": True,
            }
            self.index.append(rec)
            results.append(rec)
        self._save_index()
        return results

    # ---------- 采集入口 ----------
    def crawl_category(self, platform, category, keyword, limit=10):
        """采集某平台某品类的商品主图，存入参考图库。
        复用调试浏览器(9222)中商家已登录的会话截图真实主图；
        若调试浏览器未就绪则自动拉起，仍未就绪才降级演示占位图。"""
        if platform not in self.cfg.Crawler.PLATFORMS:
            platform = "taobao"
        # 尝试自动拉起/等待调试浏览器（短超时，快速降级，不阻塞）
        try:
            ready, msg = ensure_debug_browser(timeout=8)
        except Exception as e:  # noqa: BLE001
            ready, msg = False, f"调试浏览器探测失败: {e}"
        if not ready:
            demo = self._demo_crawl(platform, category, keyword, limit)
            return demo + [{"error": "CDP 截图未就绪（调试浏览器未运行或未登录）：" + msg,
                            "warn": True, "platform": platform}]
        try:
            real = self._cdp_crawl(platform, category, keyword, limit)
        except Exception as e:  # noqa: BLE001 —— CDP 异常优雅降级
            demo = self._demo_crawl(platform, category, keyword, limit)
            return demo + [{"error": "CDP 截图失败，已生成演示占位图：" + str(e),
                            "warn": True, "platform": platform}]
        if not real:
            demo = self._demo_crawl(platform, category, keyword, limit)
            return demo + [{"error": "调试浏览器已就绪，但未截图到真实主图（请确认已在当前平台登录并停留在商品搜索页），已生成演示占位图",
                            "warn": True, "platform": platform}]
        return real

    # ---------- CDP 真实主图截图 ----------
    def _cdp_ws_url(self):
        """返回第一个可用调试浏览器页面 ws 地址；无则抛异常。"""
        import urllib.request
        url = self.cfg.Crawler.DEBUGGER if hasattr(self.cfg.Crawler, "DEBUGGER") else "http://127.0.0.1:9222"
        with urllib.request.urlopen(url + "/json/list", timeout=8) as r:
            pages = json.load(r)
        for t in pages:
            if t.get("type") == "page":
                return t.get("webSocketDebuggerUrl")
        raise RuntimeError("调试浏览器无可用页面")

    def _cdp_send(self, ws, method, params=None):
        import websocket
        _cdp_id[0] += 1
        mid = _cdp_id[0]
        ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(ws.recv())
            if msg.get("id") == mid:
                return msg

    def _cdp_ev(self, ws, expr):
        r = self._cdp_send(ws, "Runtime.evaluate",
                           {"expression": expr, "returnByValue": True})
        res = r.get("result", {})
        if res.get("exceptionDetails"):
            return None
        return res.get("result", {}).get("value")

    def _cdp_crawl(self, platform, category, keyword, limit):
        """在调试浏览器中打开目标平台搜索页并按品类截图主图缩略图，存为 PNG。
        返回真实截图记录列表；CDP 异常会抛异常交由上层降级。
        注：仅截取已登录会话可见的搜索缩略图，供商家内部选品参考，不公开展示用户信息。"""
        import websocket
        ws_url = self._cdp_ws_url()
        ws = websocket.create_connection(ws_url, timeout=30, suppress_origin=True)
        try:
            kw = (keyword or category or "摩托车 配件").strip()
            url = _PLATFORM_SEARCH.get(platform) or _PLATFORM_SEARCH["taobao"]
            nav = "window.location.href='%s'" % (url.replace("__KW__", urllib.parse.quote(kw)))
            self._cdp_ev(ws, nav)
            time.sleep(settings.Crawler.NAV_WAIT or 6)
            img_re = "(%s|%s)" % (_PLATFORM_IMG_RE.get(platform, ""), _GENERIC_IMG_RE)
            # 读取商品缩略图 URL（兼容 lazyload：src 为空时回退 data-src/data-original）
            imgs = self._cdp_ev(ws, """
(function(){
  var re=/%s/;
  var els=[].slice.call(document.querySelectorAll('img'));
  var hits=[];
  for(var k=0;k<els.length;k++){
    var im=els[k];
    var s=(im.currentSrc||im.src||im.getAttribute('data-src')||im.getAttribute('data-original')||'')||'';
    if(!re.test(s)) continue;
    hits.push({src:s, w:im.naturalWidth||0, h:im.naturalHeight||0});
  }
  // 去重（按 src），取前 12 张可截图缩略图
  var seen={}, out=[];
  for(var j=0;j<hits.length&&out.length<12;j++){
    var h=hits[j]; if(seen[h.src]) continue; seen[h.src]=1; out.push(h);
  }
  return out;
})()
""" % img_re) or []
            results = []
            for i, it in enumerate(imgs[:int(limit)]):
                src = it.get("src") or ""
                if not src or it.get("w", 0) < 120:
                    continue
                # 截图这个 img 元素（用 CDP DOM+截图坐标命中，最精准）
                rect = self._cdp_ev(ws, """
(function(){
  var imgs=[].slice.call(document.querySelectorAll('img'));
  for(var j=0;j<imgs.length;j++){
    var s=(imgs[j].currentSrc||imgs[j].src||imgs[j].getAttribute('data-src')||imgs[j].getAttribute('data-original')||'')||'';
    if(s.indexOf('%s')>=0){var r=imgs[j].getBoundingClientRect();
      return {x:r.left, y:r.top, w:r.width, h:r.height, sw:innerWidth, sh:innerHeight};}
  }
  return null;
})()
""" % src[:60])
                if not rect or rect["w"] <= 0:
                    continue
                data = self._cdp_send(ws, "Page.captureScreenshot", {
                    "format": "png",
                    "clip": {"x": rect["x"], "y": rect["y"],
                             "width": rect["w"], "height": rect["h"],
                             "scale": 1.0},
                })
                b64 = (data.get("result", {}) or {}).get("data")
                if not b64:
                    continue
                raw = base64.b64decode(b64)
                name = hashlib.md5(
                    f"{platform}:{kw}:{i}:{time.time()}".encode()).hexdigest()[:16] + ".png"
                path = os.path.join(self.save_dir, name)
                with open(path, "wb") as f:
                    f.write(raw)
                results.append({
                    "file": name, "local_path": path,
                    "source_url": src, "platform": platform,
                    "category": category or kw, "keyword": keyword,
                    "title": f"{kw}·主图{i + 1}", "price": "",
                    "size_kb": round(len(raw) / 1024, 1),
                    "crawled_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "demo": False,
                })
                self.index.append(results[-1])
                time.sleep(2)
            self._save_index()
            return results
        finally:
            try:
                ws.close()
            except Exception:  # noqa: BLE001
                pass

    def _real_crawl(self, platform, category, keyword, limit):
        """真实生产：调用各平台官方开放平台 API（适配层预留）。

        淘宝：taobao.tbk.item.get      京东：jd.union.open.goods.query
        抖店：/product/list             拼多多：pdd.ddk.goods.search
        需配置对应开放平台密钥后启用；当前未配置时返回空并提示。
        """
        return [{"error": "生产模式需配置平台开放平台密钥，当前使用演示模式"}]

    # ---------- 图库检索 ----------
    def search_library(self, category="", platform=""):
        res = self.index
        if category:
            res = [r for r in res if category in r.get("category", "")]
        if platform:
            res = [r for r in res if r.get("platform") == platform]
        return res

    def stats(self):
        by_platform, by_category = {}, {}
        for r in self.index:
            by_platform[r["platform"]] = by_platform.get(r["platform"], 0) + 1
            by_category[r["category"]] = by_category.get(r["category"], 0) + 1
        return {
            "总图片数": len(self.index),
            "按平台分布": by_platform,
            "按品类分布": by_category,
            "存储占用MB": round(sum(r["size_kb"] for r in self.index) / 1024, 2),
        }
