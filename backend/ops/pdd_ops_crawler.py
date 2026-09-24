# -*- coding: utf-8 -*-
"""拼多多商家后台 经营数据 CDP 同步采集器

复用调试浏览器(127.0.0.1:9222)中商家已登录的会话，在商家后台数据页
自动抓取表格 → 按表头关键词模糊匹配列 → 落库到 store.py。

设计原则：
- 可配置：候选数据页地址集中在 settings.Crawler.OP_PAGES；列名关键词映射
  复用 store.LINK_COLS，改一处全局生效。
- 通用抓取：先做「整页表格全量提取」，再按表头关键词映射列，
  不依赖具体页面 DOM 结构（商家后台改版也能同步）。
- 优雅降级：CDP 不可达 / 无商家后台页面 / 页面无表格 / 列匹配失败，
  都返回结构化原因与修复提示，绝不抛异常。

用法（由 ops_api 调用）：
  sync(use_current=True)   # 默认：直接采集当前已打开的商家后台页
  sync(use_current=False)  # 找不到商家后台页时自动打开候选数据页
"""
import json
import re
import time
import datetime
import urllib.parse
import urllib.request

import websocket

from . import settings, store

DEBUGGER = "http://127.0.0.1:9222"

_id = [0]

# ⭐ spider-font 防爬图标字体解码：商品数据/交易数据页的「数字」用防爬字体渲染，
#    innerText 读出来是 PUA 乱码字形(如 \ue444)，无法直接读成真实数字。
#    解码器在浏览器内 canvas 逐像素比对字形与《0-9.%》，还原真实数字，按 (字体,字号)
#    一次性缓存到 window.__pddDec。对明文页面其结果是恒等变换，天然安全。
_DECODER_PREP_JS = r"""(function(){
if(window.__pddDec) { return; }
window.__pddDec=(function(){
  function makeDecoder(){
    var probe=document.querySelector('span.__spider_font');
    if(!probe) return function(t){return t;};
    var cs=getComputedStyle(probe),fam=cs.fontFamily||'sans-serif',size=cs.fontSize||'14px';
    function finger(ch){
      var S=150,c=document.createElement('canvas');c.width=c.height=S;var g=c.getContext('2d');
      try{g.font=size+' '+fam;}catch(e){return null;}
      g.clearRect(0,0,S,S);g.textBaseline='middle';g.textAlign='center';g.fillStyle='#000';
      g.fillText(ch,S/2,S/2);
      var d=g.getImageData(0,0,S,S).data,minx=S,miny=S,maxx=-1,maxy=-1;
      for(var y=0;y<S;y++)for(var x=0;x<S;x++)if(d[(y*S+x)*4+3]>8){if(x<minx)minx=x;if(x>maxx)maxx=x;if(y<miny)miny=y;if(y>maxy)maxy=y;}
      if(maxx<0)return null;
      var bw=maxx-minx+1,bh=maxy-miny+1,T=24;
      var c2=document.createElement('canvas');c2.width=c2.height=T;var g2=c2.getContext('2d');
      g2.clearRect(0,0,T,T);g2.drawImage(c,minx,miny,bw,bh,(T-bw*T/S)/2,0,bw*T/S,bh*T/S);
      var d2=g2.getImageData(0,0,T,T).data,f=[];
      for(var i=0;i<d2.length;i+=4)f.push(d2[i+3]>8?1:0);
      return f;
    }
    function cmp(a,b){var s=0;for(var i=0;i<a.length;i++)if(a[i]!==b[i])s++;return s;}
    var refStr='0123456789.%',pts=[],seen={};
    document.querySelectorAll('span.__spider_font').forEach(function(s){
      var t=s.innerText||'';for(var i=0;i<t.length;i++){var ch=t[i];if(ch.charCodeAt(0)>=0xE000&&!seen[ch]){seen[ch]=1;pts.push(ch);}}
    });
    var refF={};function getRef(r){if(!refF[r])refF[r]=finger(r);return refF[r];}
    var map={};
    for(var p=0;p<pts.length;p++){
      var fa=finger(pts[p]);if(!fa){map[pts[p]]=pts[p];continue;}
      var best=pts[p],bd=1e9;
      for(var r=0;r<refStr.length;r++){var fb=getRef(refStr[r]);if(!fb)continue;var d=cmp(fa,fb);if(d<bd){bd=d;best=refStr[r];}}
      map[pts[p]]=bd<=3?best:'?';
    }
    return function(t){if(!t)return t;var o='';for(var i=0;i<t.length;i++){var ch=t[i];o+=map[ch]!==undefined?map[ch]:ch;}return o;};
  }
  var _dec=makeDecoder();
  return function(t){return _dec(t);};
})();
})()"""

# 整页表格提取（所有 table：表头 + 数据行，仅保留非空行），先保证解码器就绪
_EXTRACT_JS = r"""(function(){
if(!window.__pddDec){ /* 确保解码器；正常应已在 _ensure_decoder 注入 */ }
function _pd(t){return window.__pddDec(t);}
function _pc(el){return _pd((el.innerText||'').trim());}
var out=[];
var tables=document.querySelectorAll('table');
for(var i=0;i<tables.length;i++){
  var t=tables[i], trs=t.querySelectorAll('tr');
  if(!trs.length) continue;
  var ths=trs[0].querySelectorAll('th');
  var cells=ths.length?ths:trs[0].querySelectorAll('td');
  var headers=[];
  for(var j=0;j<cells.length;j++) headers.push(_pc(cells[j]));
  var rows=[];
  for(var r=1;r<trs.length;r++){
    var tds=trs[r].querySelectorAll('td');
    if(!tds.length) continue;
    var row=[];
    for(var c=0;c<tds.length;c++) row.push(_pc(tds[c]));
    if(row.join('').replace(/\s/g,'')) rows.push(row);
  }
  if(rows.length) out.push({headers:headers, rows:rows});
}
return out;})()"""

#
# 交易数据页(stores_data/operation)「交易概况」卡片采集 —— 商店级权威日统计。
# 卡片取值为防爬字体，格式归一化为：标签 今日值 昨日 昨日值（部分为「昨日X」单值卡）。
# 这里按已知卡片标签找到最近同框容器，返回 标签 -> 解码后的整行文本。
_TRADE_CARDS_JS = r"""(function(){
function _pd(t){return window.__pddDec(t);}
function _cl(x){return (x||'').replace(/\n/g,' ').replace(/\s+/g,' ').trim();}
var LABELS=['成交金额','成交订单数','成交买家数','成交转化率','客单价','成交老买家占比',
            '店铺关注用户数','退款金额','退款单数','平均访客价值',
            '昨日退款金额','昨日退款单数','昨日访客价值','昨日关注用户数'];
var res={};
for(var i=0;i<LABELS.length;i++){
  var label=LABELS[i],best=null;
  document.querySelectorAll('span,div,p,li').forEach(function(e){
    if(e.children.length)return;
    if(_cl(e.innerText||e.textContent)===label){
      for(var up=e.parentElement,depth=0;up&&depth<8;up=up.parentElement,depth++){
        var ut=_cl(_pd(up.innerText));
        if(ut.indexOf(label)===0 && /[0-9]/.test(ut)){
          if(!best||ut.length<best.length)best=ut;
        }
      }
    }
  });
  res[label]=best;
}
return res;
})()"""


# ---------------- CDP 基础 ----------------
def _send(ws, method, params=None):
    _id[0] += 1
    mid = _id[0]
    ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
    while True:
        msg = json.loads(ws.recv())
        if msg.get("id") == mid:
            return msg


def _ensure_decoder(ws):
    """确保当前 tab 已注入 window.__pddDec 防爬字体解码器（只算一次）。"""
    try:
        _ev(ws, _DECODER_PREP_JS)
    except Exception:  # noqa: BLE001
        pass


def _ev(ws, expr):
    r = _send(ws, "Runtime.evaluate",
              {"expression": expr, "returnByValue": True, "awaitPromise": True})
    res = r.get("result", {})
    if res.get("exceptionDetails"):
        return None
    return res.get("result", {}).get("value")


def _connect(ws_url):
    return websocket.create_connection(ws_url, timeout=30, suppress_origin=True)


def _list_pages():
    with urllib.request.urlopen(DEBUGGER + "/json/list", timeout=8) as r:
        return [t for t in json.load(r) if t.get("type") == "page"]


def _open_page(url):
    req = urllib.request.Request(
        DEBUGGER + "/json/new?" + urllib.parse.quote(url, safe=":/?#=&"),
        method="PUT")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


# ---------------- 同步主流程 ----------------
def sync(use_current=True, page_url=""):
    """采集商家后台数据 → 落库。返回结构化结果，任何异常都优雅降级。"""
    try:
        pages = _list_pages()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": "cdp_offline",
                "message": f"调试浏览器(9222)未就绪：{e}。请先启动程序（引擎启动时会拉起调试浏览器），"
                           f"并在浏览器中登录拼多多商家后台。"}
    if not pages:
        return {"ok": False, "reason": "no_page",
                "message": "调试浏览器无任何页面，请先打开商家后台。"}

    mms = _find_mms_page(pages)
    if not mms:
        # 尝试自动打开候选数据页
        url = page_url or ((settings.Crawler.OP_PAGES or [""])[0] if use_current is False else "")
        if not url:
            return {"ok": False, "reason": "no_mms_page",
                    "message": "未找到商家后台(mms.pinduoduo.com)页面。请先在浏览器登录商家后台、"
                               "打开经营数据页，再点「同步」。"}
        try:
            _open_page(url)
            time.sleep(settings.Crawler.NAV_WAIT)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "reason": "open_fail",
                    "message": f"自动打开数据页失败：{e}"}
        try:
            pages = _list_pages()
        except Exception:  # noqa: BLE001
            pages = []
        mms = _find_mms_page(pages)
        if not mms:
            return {"ok": False, "reason": "no_mms_page",
                    "message": "自动打开数据页后仍未找到商家后台页面。"}

    ws = None
    try:
        ws = _connect(mms["webSocketDebuggerUrl"])
        _ensure_decoder(ws)                    # 防爬字体解码器（只算一次）
        url_now = mms.get("url") or ""
        # 非「当前页模式」且指定了页面地址 → 导航过去
        if not use_current and page_url and page_url not in url_now:
            _send(ws, "Page.enable")
            _send(ws, "Page.navigate", {"url": page_url})
            time.sleep(settings.Crawler.NAV_WAIT)
            url_now = page_url

        tables = _wait_tables(ws)
        if not tables:
            return {"ok": False, "reason": "no_table",
                    "message": "当前页面未检测到数据表格。请在商家后台打开『经营数据 / 商品数据 / 交易数据』页后重试。",
                    "page_url": url_now}

        rows, overviews, n_daily = [], [], 0
        for tb in tables:
            rows.extend(_table_to_rows(tb, url_now))
            ov = _extract_overview(tb)
            if ov and ov.get("rows"):
                overviews.append(ov)
        if overviews:
            try:
                store.save_overview(overviews, note="CDP 交易概况 · " + url_now[:40])
            except Exception:  # noqa: BLE001
                pass
        n_over = sum(len(b.get("rows", [])) for b in overviews)

        # 交易数据页顶部「交易概况」卡：商店级权威成交/订单/买家/退款/客单价，
        # 优先于商品页推算值，直接写入每日权威日统计(store.daily)。
        if "stores_data/operation" not in url_now:
            try:  # 导航到交易数据页（优先渠道）
                _send(ws, "Page.enable")
                _send(ws, "Page.navigate", {"url": (settings.Crawler.OP_PAGES or [""])[0]})
                time.sleep(settings.Crawler.NAV_WAIT)
                url_now = (settings.Crawler.OP_PAGES or [""])[0]
                _ensure_decoder(ws)
            except Exception:  # noqa: BLE001
                pass
        if "stores_data/operation" in url_now:
            n_daily = _collect_trade_daily(ws)

        if not rows:
            # 无商品链接行，但交易概况/交易数据卡已保存 → 视为成功
            if n_over or n_daily:
                got = ", ".join(x for x in (f"{n_over} 条交易概况" if n_over else "",
                                            f"{n_daily} 天交易数据" if n_daily else "") if x)
                return {"ok": True, "rows": 0, "overview_rows": n_over, "daily_days": n_daily,
                        "page_url": url_now, "tables_found": len(tables),
                        "message": f"CDP 同步成功：{got} 已入库（来源 {url_now[:50]}）"}
            return {"ok": False, "reason": "no_matched_row",
                    "message": "已检测到表格，但未匹配到「商品ID/花费/成交额」等列。"
                               "可能需要调整表头关键词（backend/ops/store.py 的 LINK_COLS），"
                               "或切换到『商品数据』页后重试。",
                    "page_url": url_now,
                    "tables_headers": [t.get("headers", []) for t in tables[:5]]}

        # 按 (商品,日期) 去重
        seen, uniq = set(), []
        for r in rows:
            key = (r["product_id"], r["date"])
            if key in seen:
                continue
            seen.add(key)
            uniq.append(r)

        out = store.save_sync_rows(uniq, note="CDP 同步 · " + url_now[:60])
        extra = ", ".join(x for x in (f"{len(uniq)} 条商品记录" if uniq else None,
                                      f"{n_over} 条交易概况" if n_over else None,
                                      f"{n_daily} 天交易数据" if n_daily else None) if x)
        out.update({"ok": True, "rows": len(uniq), "overview_rows": n_over, "daily_days": n_daily,
                    "tables_found": len(tables),
                    "page_url": url_now,
                    "message": f"CDP 同步成功：{extra or '无有效数据'}（来源 {url_now[:50]}）"})
        return out
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": "sync_error",
                "message": f"同步过程出错：{e}。可尝试刷新商家后台页面后重试。"}
    finally:
        if ws:
            try:
                ws.close()
            except Exception:  # noqa: BLE001
                pass


def _find_mms_page(pages):
    for t in pages:
        if "mms.pinduoduo.com" in (t.get("url") or ""):
            return t
    return None


def _wait_tables(ws, seconds=None):
    seconds = seconds or settings.Crawler.SYNC_TIMEOUT
    for _ in range(int(seconds)):
        _ensure_decoder(ws)
        try:
            tabs = _ev(ws, _EXTRACT_JS) or []
        except Exception:  # noqa: BLE001
            tabs = []
        if tabs:
            return tabs
        time.sleep(1)
    return []


def _norm(h):
    return re.sub(r"\s+", "", str(h or "")).lower()


def _today_val(v):
    """单元格常为「今日值\\n昨日 昨日值」的堆叠文本（如 '0.00\\n昨日 420.00'），
    只取「今日」段：换行前 / '昨日' 之前的部分，避免今日与昨日数字被拼接。"""
    s = str(v or "")
    for sep in ("昨日", "\n", "今日"):
        i = s.find(sep)
        if i >= 0:
            s = s[:i]
            break
    return s.strip()


# 交易概况卡标签 -> 日统计字段（商店级权威值，优先于商品页推算）
_CARD_FIELDS = {
    "成交金额": "revenue",
    "成交订单数": "orders",
    "成交买家数": "buyers",
    "成交转化率": "conversion_rate",
    "客单价": "customer_unit_price",
    "成交老买家占比": "old_buyer_rate",
    # 非「实时」维度（昨日/7日/30日/周/月）下，第二行卡片为当期值，无「昨日」前缀
    "店铺关注用户数": "followers",
    "退款金额": "refund_amount",
    "退款单数": "refund_orders",
    "平均访客价值": "visitor_value",
    "昨日退款金额": "refund_amount",
    "昨日退款单数": "refund_orders",
    "昨日访客价值": "visitor_value",
    "昨日关注用户数": "followers",
}
_NUM_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?%?")


def _num_float(s):
    """'1,120.00' / '5.31%' → 1120.0 / 5.31；'--' 或空 → None"""
    s = str(s or "").replace(",", "").replace("%", "").strip()
    if not s or s in ("--", "-"):
        return None
    try:
        return float(s)
    except Exception:  # noqa: BLE001
        return None


def _parse_daily_cards(cards):
    """把交易数据页交易概况卡文本解析为 {今日值, 昨日值} 两套商店级日统计。
    cards = {标签: '成交金额 0.00 昨日 1,120.00' / '昨日退款金额 0.00' / None}"""
    today, yday = {}, {}
    for label, field in _CARD_FIELDS.items():
        txt = re.sub(r"\s+", " ", str(cards.get(label) or "")).strip()
        if not txt or not txt.startswith(label):
            continue
        if label.startswith("昨日"):
            m = _NUM_RE.search(txt, len(label))
            if m:
                v = _num_float(m.group(0))
                if v is not None:
                    yday[field] = int(v) if field in ("refund_orders", "followers") else v
            continue
        rest = txt[len(label):].strip()
        hi = rest.find("昨日")
        head = rest[:hi].strip() if hi >= 0 else rest
        tail = rest[hi + 2:].strip() if hi >= 0 else ""
        h = _NUM_RE.search(head)
        t = _NUM_RE.search(tail) if tail else None
        if h and re.search(r"\d", h.group(0)):
            v = _num_float(h.group(0))
            if v is not None:
                today[field] = int(v) if field in ("orders", "buyers") else v
        if t and re.search(r"\d", t.group(0)):
            v = _num_float(t.group(0))
            if v is not None:
                yday[field] = int(v) if field in ("orders", "buyers", "refund_orders", "followers") else v
    return today, yday


def _date_str(days_back):
    """今天 / 昨天 等日期的 ISO 字符串"""
    return (datetime.date.today() - datetime.timedelta(days=days_back)).isoformat()


def _extract_overview(table):
    """识别交易数据页(stores_data)的「省份 / 月份」店铺级汇总表并结构化。
    与商品链接日指标独立（无商品ID），直接写入 overview。识别不到返回 None。"""
    headers = [_norm(h) for h in table.get("headers", [])]
    rows = table.get("rows", [])
    # ---- 省份交易分布表：含「省份/地区」列 ----
    if any(("省份" in h or "地区" in h) for h in headers):
        prov = []
        for r in rows:
            region = store._first_nonempty(headers, ["省份", "地区"], r)
            if not region:
                continue
            amount = _today_val(store._first_nonempty(headers, ["成交金额", "成交额"], r))
            orders = _today_val(store._first_nonempty(headers, ["成交订单数", "订单数"], r))
            buyers = _today_val(store._first_nonempty(headers, ["成交买家数", "买家数"], r))
            unit = _today_val(store._first_nonempty(headers, ["成交订单单价", "订单单价"], r))
            cust = _today_val(store._first_nonempty(headers, ["成交客单价", "客单价"], r))
            if amount or orders or buyers or unit or cust:
                prov.append({
                    "region": region,
                    "amount": store.to_float(amount),
                    "orders": store.to_int(orders),
                    "buyers": store.to_int(buyers),
                    "order_unit_price": store.to_float(unit),
                    "customer_unit_price": store.to_float(cust),
                })
        if prov:
            return {"kind": "provinces", "rows": prov}
    # ---- 月份完成度表：含「月份」列 ----
    if any("月份" in h for h in headers) or any("完成度" in h for h in headers):
        hl = table.get("headers", [])
        mon = []
        for r in rows:
            month = store._first_nonempty(headers, ["月份", "月"], r)
            if not month:
                continue
            metrics = {}
            for i, h in enumerate(hl):
                if i and i < len(r) and h:
                    metrics[str(h).strip()] = _today_val(r[i])
            mon.append({"month": month, "metrics": metrics})
        if mon:
            return {"kind": "months", "rows": mon}
    return None


def _table_to_rows(table, page_url=""):
    """一张表 → 商品链接日指标行（列按表头关键词映射）"""
    headers = [_norm(h) for h in table.get("headers", [])]
    today = time.strftime("%Y-%m-%d")
    out = []
    for r in table.get("rows", []):
        pid = store.norm_product_id(
            store._first_nonempty(headers, store.LINK_COLS["product_id"], r))
        if not pid or pid == "UNKNOWN":
            continue
        date = store.norm_date(
            store._first_nonempty(headers, store.LINK_COLS["date"], r)) or today
        name = store._first_nonempty(headers, store.LINK_COLS["name"], r)
        # 商品信息单元格形如「标题\nID:123」，只保留标题、去掉 ID 行
        if name:
            name = re.split(r"\s*ID[:：]?\s*\d+\s*", str(name))[0].strip()
        row = {"product_id": pid, "date": date, "name": name}
        for key, col in (("cost", "cost"), ("revenue", "revenue"), ("orders", "orders"),
                         ("clicks", "clicks"), ("impressions", "impressions"),
                         ("budget", "budget"), ("price", "price")):
            v = _today_val(store._first_nonempty(headers, store.LINK_COLS[col], r))
            if v != "":
                row[key] = store.to_float(v) if key not in ("orders", "clicks", "impressions") \
                    else store.to_int(v)
        out.append(row)
    return out


def probe():
    """连通性探测：返回调试浏览器与商家后台页面状态（供前端提示）"""
    try:
        pages = _list_pages()
    except Exception as e:  # noqa: BLE001
        return {"cdp_ok": False, "mms_open": False, "message": f"调试浏览器未就绪：{e}"}
    mms = _find_mms_page(pages)
    return {"cdp_ok": True, "mms_open": bool(mms),
            "page_count": len(pages),
            "message": "商家后台页面已就绪，可直接同步" if mms
                       else "调试浏览器已就绪，但未打开商家后台页面，请先登录"}


# ---------------- 实时同步（定时循环复用） ----------------
def _collect_trade_daily(ws):
    """当前页（应为交易数据页 stores_data/operation）抓「交易概况」卡 → 写权威日统计。
    返回写入的天数（0 = 未采到）。"""
    try:
        time.sleep(1)   # 等交易概况卡渲染
        cards = _ev(ws, _TRADE_CARDS_JS) or {}
        today_rec, yday_rec = _parse_daily_cards(cards)
        drecs = []
        if today_rec:
            drecs.append({"date": _date_str(0), "source": "交易数据-实时", **today_rec})
        if yday_rec:
            drecs.append({"date": _date_str(1), "source": "交易数据-昨日", **yday_rec})
        if drecs:
            store.save_daily(drecs, note="CDP 交易数据 · 权威日统计")
            return len(drecs)
    except Exception:  # noqa: BLE001
        pass
    return 0


# ---------------- 交易数据 · 多周期采集（自动点击时间按钮） ----------------
# 页面「交易概况」卡的时间筛选按钮（实时/昨日/7日/30日/周/月）点击后，卡片数值切换为
# 该时间维度对应取值。旧机制不做跳转、盲抓「当前选中维度」，常把 30 日/实时聚合值
# 当成单日权威日统计写入，导致与订单明细对不上。这里改为显式点击按钮后逐维度抓取。
# 「周」「月」维度的平台权威聚合直接供周报/月报使用，根治日统计覆盖不全导致的
# 周/月报表与平台对不上问题。
_PERIOD_SEQ = ("实时", "昨日", "7日", "30日", "周", "月")

# 抓取「交易概况」卡头部的「统计时间： 2026-09-01 ~ 2026-09-22」区间，
# 供报表侧校验平台聚合与请求周期是否吻合。取页面第一处匹配（交易概况在年度经营情况之前）。
_STAT_RANGE_JS = r"""(function(){
function _cl(x){return (x||'').replace(/\n/g,' ').replace(/\s+/g,' ').trim();}
var all=document.querySelectorAll('span,div,p,li,em');
for(var i=0;i<all.length;i++){
  var t=_cl(all[i].innerText||all[i].textContent);
  if(!t||t.length>60)continue;
  var m=t.match(/统计时间[::]\s*(\d{4}-\d{2}-\d{2})(?:\s*[~～\-至到]\s*(\d{4}-\d{2}-\d{2}))?/);
  if(m)return {start:m[1],end:m[2]||m[1],text:t};
}
return null;
})()"""


def _extract_cmp(cards):
    """从卡片文本提取平台官方环比「较前1月/较前1周 ↑x%」→ {"成交额":"+782.46%",...}。
    箭头转正负号，与报表环比格式一致（前端按是否以 - 开头判涨跌）。"""
    out = {}
    for label, cn in (("成交金额", "成交额"), ("成交订单数", "订单数"), ("客单价", "客单价")):
        txt = re.sub(r"\s+", " ", str(cards.get(label) or ""))
        m = re.search(r"较前\S{0,4}?\s*([↑↓])\s*([\d.]+)%", txt)
        if m:
            sign = "+" if m.group(1) == "↑" else "-"
            out[cn] = f"{sign}{m.group(2)}%"
    return out


def _click_period_src(label):
    """构建点击「实时/昨日/7日/30日」按钮的 JS。
    找到文本恰为 label 的叶子节点，向上取最近的可点击祖先，派发 pointer/mouse/click 事件。
    label 来自固定白名单，注入安全。"""
    # label 用 json 字面量转义，避免引号破坏 JS
    import json as _json
    lab = _json.dumps(label, ensure_ascii=False)
    return r"""(function(label){
function _cl(x){return (x||'').replace(/\n/g,' ').replace(/\s+/g,' ').trim();}
function fire(el){
  var r=(el.getBoundingClientRect&&el.getBoundingClientRect())||{x:0,y:0,cx:0,cy:0};
  var x=(r.x||r.left||0)+2, y=(r.y||r.top||0)+2;
  function mk(t){try{return new MouseEvent(t,{bubbles:true,cancelable:true,view:window,clientX:x,clientY:y});}catch(e){return null;}}
  ['pointerdown','mousedown','pointerup','mouseup','click'].forEach(function(t){var ev=mk(t);if(ev)el.dispatchEvent(ev);});
  try{el.click();}catch(e){}
  return r;
}
var all=document.querySelectorAll('div,span,li,a,button,em,strong,p');
for(var i=0;i<all.length;i++){
  var e=all[i];
  if(e.children&&e.children.length)continue;
  if(_cl(e.innerText||e.textContent)!==label)continue;
  var up=e,target=null;
  for(var d=0;up&&d<8;up=up.parentElement,d++){
    var tag=(up.tagName||'').toUpperCase(),cls=String(up.className||'');
    if(tag==='BUTTON'||tag==='A'||up.onclick||/btn|switch|tab|item/.test(cls)){target=up;break;}
  }
  fire(target||e);
  return {label:label,clicked:true,tag:(target||e).tagName};
}
return {label:label,clicked:false};
})(""" + lab + ")"


def _nav(ws, url):
    """把当前 tab 导航到指定页面，等待渲染并确保解码头就绪。返回实际地址。"""
    try:
        _send(ws, "Page.enable")
        _send(ws, "Page.navigate", {"url": url})
        time.sleep(settings.Crawler.NAV_WAIT)
    except Exception:  # noqa: BLE001
        time.sleep(2)
    _ensure_decoder(ws)
    return url


def collect_trade_periods():
    """多周期交易数据采集：导航到交易数据页，自动点击「实时/昨日/7日/30日」
    时间按钮，逐维度抓取「交易概况」卡并落库为多周期统计(store.periods)。

    用于解决旧机制盲抓「当前选中维度」导致 30 日/实时聚合值被当成单日口径、
    与订单明细对不上的问题。频率由 live 调度控制（默认 30 分钟一次）。
    任何失败都优雅降级，绝不抛异常。返回结构化摘要 dict。"""
    try:
        pages = _list_pages()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": "cdp_offline", "message": str(e)}
    mms = _find_mms_page(pages)
    if not mms:
        return {"ok": False, "reason": "no_mms_page",
                "message": "调试浏览器未打开商家后台(mms.pinduoduo.com)页面，多周期采集跳过"}
    ws = None
    collected = {}
    try:
        ws = _connect(mms["webSocketDebuggerUrl"])
        _ensure_decoder(ws)
        _nav(ws, (settings.Crawler.OP_PAGES or [""])[0])   # 交易数据页
        time.sleep(1)
        for label in _PERIOD_SEQ:
            try:
                _ev(ws, _click_period_src(label))
                time.sleep(1.6)   # 等卡片切换渲染
                cards = _ev(ws, _TRADE_CARDS_JS) or {}
                today_rec, yday_rec = _parse_daily_cards(cards)
                cmp_rec = _extract_cmp(cards)
                rng = _ev(ws, _STAT_RANGE_JS) or {}
            except Exception:  # noqa: BLE001
                continue
            # 合并：头部为当前维度主值，昨日单值卡（如昨日退款）并入
            merged = {**yday_rec, **today_rec}
            if cmp_rec:
                merged["_cmp"] = cmp_rec
            if isinstance(rng, dict):
                if rng.get("start"):
                    merged["range_start"] = rng["start"]
                if rng.get("end"):
                    merged["range_end"] = rng["end"]
            if not any(merged.get(k) is not None for k in
                       ("revenue", "orders", "buyers", "conversion_rate",
                        "customer_unit_price", "refund_amount", "refund_orders")):
                continue
            collected[label] = merged
        # 采集完回到「实时」维度方便驾驶舱关联
        try:
            _ev(ws, _click_period_src("实时"))
        except Exception:  # noqa: BLE001
            pass
        if collected:
            store.save_periods(collected, note="CDP 多周期 · 自动点击采集")
            return {"ok": True,
                    "periods": list(collected.keys()),
                    "message": f"多周期采集成功：{'、'.join(collected.keys())} 已入库"}
        return {"ok": False, "reason": "no_period_data",
                "message": "已进入交易数据页，但未识别到「实时/昨日/7日/30日/周/月」按钮或卡片数值，"
                           "请确认页面已登录且已展开经营数据卡片。"}
    finally:
        if ws:
            try:
                ws.close()
            except Exception:  # noqa: BLE001
                pass


def _extract_orders(table):
    """从一张含「订单号」列的表格提取逐单订单明细。识别不到则返回空，天然安全。"""
    headers = [_norm(h) for h in table.get("headers", [])]
    if not any(any(k in h for k in ("订单号", "订单编号", "订单id")) for h in headers):
        return []
    out = []
    for r in table.get("rows", []):
        oid = store._first_nonempty(headers, store.ORDER_COLS["order_id"], r)
        if not oid:
            continue
        date = store.norm_date(store._first_nonempty(headers, store.ORDER_COLS["date"], r))
        amount = store.to_float(_today_val(
            store._first_nonempty(headers, store.ORDER_COLS["amount"], r)))
        quantity = store.to_int(_today_val(
            store._first_nonempty(headers, store.ORDER_COLS["quantity"], r)))
        out.append({
            "order_id": str(oid).strip(),
            "date": date,
            "amount": amount,
            "quantity": quantity or 1,
            "buyer_id": store._first_nonempty(headers, store.ORDER_COLS["buyer_id"], r) or "买家",
            "product_id": store.norm_product_id(
                store._first_nonempty(headers, store.ORDER_COLS["product_id"], r)),
            "channel": store._first_nonempty(headers, store.ORDER_COLS["channel"], r) or "CDP",
        })
    return out


def live_refresh(orders_too=True):
    """实时同步一轮：用当前商家后台 tab 依次采集「交易数据页权威日统计」+「订单明细」。
    供定时循环复用；任何失败都优雅降级，绝不抛异常。返回采样摘要 dict。"""
    try:
        pages = _list_pages()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": "cdp_offline", "message": str(e)}
    mms = _find_mms_page(pages)
    if not mms:
        return {"ok": False, "reason": "no_mms_page",
                "message": "调试浏览器未打开商家后台(mms.pinduoduo.com)页面，实时同步跳过"}
    ws = None
    out = {"ok": True, "daily_days": 0, "orders": 0}
    try:
        ws = _connect(mms["webSocketDebuggerUrl"])
        _ensure_decoder(ws)
        # 1) 优先：交易数据页（图二的页面）权威日统计
        try:
            _nav(ws, (settings.Crawler.OP_PAGES or [""])[0])
            out["daily_days"] = _collect_trade_daily(ws)
        except Exception:  # noqa: BLE001
            pass
        # 2) 逐单订单明细：先试当前 tab 打开的表格，再按配置订单页
        if orders_too:
            batch = []
            try:
                for tb in _wait_tables(ws):
                    batch.extend(_extract_orders(tb) or [])
            except Exception:  # noqa: BLE001
                pass
            for url in (settings.Crawler.ORDER_PAGES or []):
                try:
                    _nav(ws, url)
                    time.sleep(1)
                    for tb in _wait_tables(ws):
                        batch.extend(_extract_orders(tb) or [])
                    break
                except Exception:  # noqa: BLE001
                    continue
            seen, uniq = set(), []
            for o in batch:
                if o["order_id"] not in seen:
                    seen.add(o["order_id"])
                    uniq.append(o)
            if uniq:
                out["orders"] = store.save_orders(uniq, note="CDP 实时订单")
        # 回到交易数据页，方便驾驶舱关联
        try:
            _nav(ws, (settings.Crawler.OP_PAGES or [""])[0])
        except Exception:  # noqa: BLE001
            pass
    finally:
        if ws:
            try:
                ws.close()
            except Exception:  # noqa: BLE001
                pass
    try:
        store.mark_live_synced(
            f"已采样 {out['daily_days']} 天权威日统计 + {out['orders']} 单"
            if (out["daily_days"] or out["orders"]) else "本轮无新数据")
    except Exception:  # noqa: BLE001
        pass
    return out
