# -*- coding: utf-8 -*-
"""
拼多多客服工作台 操作工具 (CDP 直连 127.0.0.1:9222, 全部方法实战验证通过)

用法:
  python pdd_send.py goto                   ★进入拼多多客服工作台(接管第一步)
  python pdd_send.py open 桦                打开某客户会话(按名字片段)
  python pdd_send.py text "要发送的文字"      发送文字(Enter 键方式)
  python pdd_send.py video "B款脚踏有声音版" [第几个,默认0]   从视频素材库发送
  python pdd_send.py read                   读取当前页面文本
  python pdd_send.py shot D:\\path\\x.png    截图
  python pdd_send.py videos                 列出视频素材库所有标题
  python pdd_send.py images a.jpg b.jpg     逐张发送本地图片(支持多张)
  python pdd_send.py mix                    发送「A B混合」目录内全部对比图
  python pdd_send.py goods                  读取当前会话咨询商品(标题/规格/主图)
  python pdd_send.py consult [--dry]        ★读取会话商品→按类目路由→发对应开场素材
                                            含「脚踏/挡杆」→ 自动发 A B混合 + 引导话术
                                            --dry 仅预演不发送
  python pdd_send.py syncchats              ★完整遍历所有客服会话（滚动加载+跨分组）：
                                            逐一打开读取完整聊天，提取「客户问题→客服回复」
                                            问答对，写入会话库 + 记忆库（供记忆系统学习）
  python pdd_send.py chosen A|B [--img]     ★客户选定款式后：默认只发该款实拍【视频】+规格
                                            （视频优先，不发图片；客户要图时加 --img）
  python pdd_send.py uploadvideo <路径...>  ★上传本地视频到素材库【客服专用视频】
  python pdd_send.py syncvideo A|B          ★把该款本地视频目录全部上传到素材库

关键经验(2026-09-10 实战):
- 文字发送 = textarea 填值(原生 setter) + Input.dispatchKeyEvent Enter
- div.click() / el.click() 对发送按钮与会话项无效, 必须用 Input.dispatchMouseEvent 真实鼠标
- 视频发送 = 点 .chat-icon-camera 开素材库面板, 点对应 .video-item 的 .send-video-btn
- 每发一个视频面板自动关闭, 需重新打开
- 弹窗(如"浏览器未开启通知")会拦截点击, 先关闭

关键经验(2026-09-15 实战):
- ⭐ 聊天窗口只能上传图片, 本地视频无法直接发; 视频只能从工作台素材库发送
- ⭐ 素材库数据源 = 图片空间『售后/客服/申诉专用视频』
  (https://mms.pinduoduo.com/material/service), 该页上传控件 accept=(any) 可用
  DOM.setFileInputFiles 注入, 自动上传后素材库标题 = 原文件名(去扩展名)
- 素材库面板懒加载(67项), 需轮询等 .video-item; 目标按钮常在可视区外(rect=0),
  须用 JS 派发完整事件序列点击, 且【不要】再调 .click()(会重复发送)
- 面板已打开时不可再点 camera(会把它关掉)
"""
import base64
import json
import os
import re
import sys
import time
import urllib.request
import urllib.parse

import websocket

DEBUGGER = "http://127.0.0.1:9222"

# ⭐ 拼多多客服工作台地址（用户指定，2026-09-15 确认）
#    每次启动 / 接管客服时，都要进入此页面。可用 `goto` 命令一键打开或激活。
WORKBENCH_URL = "https://mms.pinduoduo.com/chat-merchant/index.html#/"


def _kb_file():
    """kb.json 路径：优先 <程序目录>/kb.json，其次包内自带（打包成 exe 也能读到）。"""
    try:
        import asset_path
        return asset_path.kb_path()
    except Exception:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "kb.json")

_id = [0]


def _list_pages():
    """列出所有可用的 page 类型标签（不走 connect，用于导航/诊断）"""
    try:
        with urllib.request.urlopen(DEBUGGER + "/json/list", timeout=8) as r:
            return [t for t in json.load(r) if t.get("type") == "page"]
    except Exception:
        return []


def goto_workbench():
    """
    ★ 进入拼多多客服工作台（接管客服的第一步）。
    逻辑：① 已有工作台标签 → 激活置前；
          ② 没有 → 新建标签页打开；
          ③ 新建失败 → 用现有标签页导航过去。
    """
    pages = _list_pages()

    # ① 复用已存在的工作台标签
    for t in pages:
        if "chat-merchant" in (t.get("url") or ""):
            ws = websocket.create_connection(
                t["webSocketDebuggerUrl"], timeout=30, suppress_origin=True)
            try:
                send(ws, "Page.enable")
                send(ws, "Page.bringToFront")
            finally:
                ws.close()
            return "✅ 已找到并激活工作台页面（无需重新打开）"

    # ② 新建标签页打开（新版 Chrome 的 /json/new 需用 PUT）
    try:
        req = urllib.request.Request(
            DEBUGGER + "/json/new?" + urllib.parse.quote(WORKBENCH_URL, safe=":/?#=&"),
            method="PUT")
        with urllib.request.urlopen(req, timeout=10) as r:
            json.load(r)
        time.sleep(2)
        return "✅ 已新建标签页打开工作台：" + WORKBENCH_URL
    except Exception as e:
        # ③ 回退：用现有第一个标签导航
        if pages:
            t = pages[0]
            ws = websocket.create_connection(
                t["webSocketDebuggerUrl"], timeout=30, suppress_origin=True)
            try:
                send(ws, "Page.enable")
                send(ws, "Page.navigate", {"url": WORKBENCH_URL})
                time.sleep(2)
            finally:
                ws.close()
            return "✅ 已在现有标签页导航到工作台：" + WORKBENCH_URL
        return "❌ 无法打开工作台（无可用标签页）：%s" % e


def _find_workbench_ws(targets):
    """在标签列表中找工作台页面并建立 websocket 连接；找不到返回 None"""
    for t in targets:
        if t.get("type") == "page" and "chat-merchant" in (t.get("url") or ""):
            return websocket.create_connection(
                t["webSocketDebuggerUrl"], timeout=30, suppress_origin=True)
    return None


def connect():
    """
    连接客服工作台页面。
    ★ 若工作台未打开，会自动调用 goto_workbench() 打开后再重试一次，
      以符合『接管客服即进入工作台』的约定。
    """
    try:
        with urllib.request.urlopen(DEBUGGER + "/json/list", timeout=8) as r:
            targets = json.load(r)
    except Exception as e:
        raise RuntimeError(
            "无法连接 CDP 调试端口 %s —— 请先运行 start_chrome_debug.bat 启动带调试端口的浏览器。（%s）"
            % (DEBUGGER, e))

    ws = _find_workbench_ws(targets)
    if ws:
        return ws

    # 未找到工作台 → 自动打开，然后重试一次
    goto_workbench()
    time.sleep(3)
    try:
        with urllib.request.urlopen(DEBUGGER + "/json/list", timeout=8) as r:
            targets = json.load(r)
    except Exception:
        targets = []
    ws = _find_workbench_ws(targets)
    if ws:
        return ws

    titles = [(t.get("title") or t.get("url") or "?")[:40]
              for t in targets if t.get("type") == "page"]
    raise RuntimeError(
        "未找到拼多多客服工作台页面(chat-merchant)，自动打开失败。请手动打开 "
        "%s 后重试。\n当前已打开页面：%s" % (WORKBENCH_URL, " | ".join(titles)))


def send(ws, method, params=None):
    _id[0] += 1
    mid = _id[0]
    ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
    while True:
        msg = json.loads(ws.recv())
        if msg.get("id") == mid:
            return msg


def ev(ws, expr):
    r = send(ws, "Runtime.evaluate",
             {"expression": expr, "returnByValue": True, "awaitPromise": True})
    res = r.get("result", {})
    if res.get("exceptionDetails"):
        raise RuntimeError(
            json.dumps(res["exceptionDetails"], ensure_ascii=False)[:400])
    return res.get("result", {}).get("value")


def real_click(ws, x, y):
    send(ws, "Input.dispatchMouseEvent",
         {"type": "mouseMoved", "x": x, "y": y, "button": "none"})
    send(ws, "Input.dispatchMouseEvent",
         {"type": "mousePressed", "x": x, "y": y,
          "button": "left", "clickCount": 1})
    send(ws, "Input.dispatchMouseEvent",
         {"type": "mouseReleased", "x": x, "y": y,
          "button": "left", "clickCount": 1})


def click_el(ws, expr_get_pos):
    """expr_get_pos: JS 表达式, 返回 {x,y} 或 null"""
    pos = ev(ws, expr_get_pos)
    if not pos or pos.get("x", 0) <= 0:
        return "notfound"
    real_click(ws, pos["x"], pos["y"])
    return "clicked@(%d,%d)" % (pos["x"], pos["y"])


# ---------------- 功能 ----------------

def open_chat(name_hint):
    ws = connect()
    try:
        expr = """(function(){
var items=[...document.querySelectorAll('.chat-item-box')];
for(var i=0;i<items.length;i++){
  if((items[i].textContent||'').indexOf(%s)>=0){
    items[i].scrollIntoView({block:'center'});
    var r=items[i].getBoundingClientRect();
    return {x:Math.round(r.left+r.width/2),y:Math.round(r.top+r.height/2)};
  }
}
return null;})()""" % json.dumps(name_hint, ensure_ascii=False)
        r = click_el(ws, expr)
        time.sleep(3)
        ok = ev(ws, "!!document.querySelector('textarea.custom-scroll')")
        return "click=%s input_visible=%s" % (r, ok)
    finally:
        ws.close()


# 我方消息条数（用于判定「文字真的发出去了」）
_CS_COUNT_JS = ("[].slice.call(document.querySelectorAll('.msg-list .onemsg'))"
                ".filter(function(e){return !!e.querySelector('.cs-item');}).length")


def send_text(text):
    """
    发送文字（2026-09-17 加固）。

    ⚠️ 实测故障：**素材库面板开着时，回车会被面板拦掉** → 文字留在输入框没发出去，
    日志表现为 `话术=maybe-failed leftover='...'`，客户只收到视频、没收到文字。
    加固措施：
      ① 发送前若素材库面板真的开着，先关掉（避免抢焦点/拦回车）；
      ② 回车后用【我方消息条数是否增加】判定成功 —— 比看输入框是否清空更准：
         平台清空慢也不会误判失败，更不会重复发送；
      ③ 未成功则重新聚焦输入框再回车，最多 3 次；
      ④ 3 次仍失败 → 清空输入框（防止残留文字被后续动作误发）并返回 FAIL。
    """
    ws = connect()
    try:
        # ① 关掉素材库面板（camera 是开关键，只在真正可见时才点）
        try:
            if _panel_open(ws):
                _click_camera(ws)
                time.sleep(1.2)
        except Exception:
            pass

        set_expr = """(function(){
var t=document.querySelector('textarea.custom-scroll');
if(!t) return 'no-textarea';
var setter=Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype,'value').set;
setter.call(t, %s);
t.dispatchEvent(new Event('input',{bubbles:true}));
t.focus();
return 'filled';})()""" % json.dumps(text, ensure_ascii=False)
        r = ev(ws, set_expr)
        if r != "filled":
            return "FAIL fill: %s" % r
        time.sleep(0.5)

        n0 = int(ev(ws, _CS_COUNT_JS) or 0)
        for attempt in range(3):
            for t in ("rawKeyDown", "keyUp"):
                send(ws, "Input.dispatchKeyEvent",
                     {"type": t, "key": "Enter", "code": "Enter",
                      "windowsVirtualKeyCode": 13, "nativeVirtualKeyCode": 13})
            time.sleep(2.0)
            n1 = int(ev(ws, _CS_COUNT_JS) or 0)
            left = ev(ws, "(document.querySelector('textarea.custom-scroll')||{}).value||''")
            if n1 > n0 or left == "":
                return "sent" if attempt == 0 else "sent（第%d次回车才成功）" % (attempt + 1)
            # 没发出去 → 重新聚焦输入框再来一次
            ev(ws, "var t=document.querySelector('textarea.custom-scroll'); if(t){t.focus();}")
            time.sleep(0.4)

        # ④ 清空残留，避免被后续动作误发
        ev(ws, """(function(){var t=document.querySelector('textarea.custom-scroll');
if(!t) return 0;
var s=Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype,'value').set;
s.call(t,''); t.dispatchEvent(new Event('input',{bubbles:true})); return 1;})()""")
        return "FAIL 3次回车均未发出，已清空输入框（本条话术未送达）"
    finally:
        ws.close()


def _click_camera(ws):
    """强制点击相机图标（切换素材库面板开/关），不管当前状态"""
    expr = """(function(){
var b=document.querySelector('.chat-icon-camera');
if(!b) return null;
var r=b.getBoundingClientRect();
return {x:Math.round(r.left+r.width/2),y:Math.round(r.top+r.height/2)};})()"""
    r = click_el(ws, expr)
    time.sleep(2)
    return r


def _wait_video_items(ws, seconds=15):
    """轮询等待素材库视频项渲染（面板懒加载）。判定用【可见】而非 DOM 数量。"""
    for _ in range(seconds):
        if _panel_open(ws):
            return True
        time.sleep(1)
    return False


# ⚠️ 2026-09-17 实测铁律：素材库面板【关闭后 .video-item 仍留在 DOM 里】
#    实测：面板关闭时 total=63 / 可见=0。所以「面板是否打开」必须看**可见性**，
#    用 `length > 0` 判断会永远为真 → 误判"已打开"而不去点开 → 发视频静默失败。
_PANEL_OPEN_JS = ("[].slice.call(document.querySelectorAll('.video-item'))"
                  ".filter(function(e){return e.offsetParent!==null;}).length")


def _panel_open(ws):
    """素材库面板当前是否真的打开（可见的 .video-item 数量 > 0）"""
    try:
        return int(ev(ws, _PANEL_OPEN_JS) or 0) > 0
    except Exception:
        return False


def open_video_panel(ws):
    """
    打开素材库视频面板。
    ⚠️ 若面板已打开，不能再点 camera 图标——那样会把它关掉。
    故必须用【可见性】判断（见 _PANEL_OPEN_JS），不能用 DOM 数量。
    """
    if _panel_open(ws):
        return "already-open"
    return _click_camera(ws)


def send_video(title, occurrence=0):
    """
    从素材库发送视频（2026-09-15 修复）。
    ① 面板懒加载，需轮询等 .video-item 渲染；
    ② 标题先精确匹配，失败退化为包含匹配；
    ③ 目标按钮常在可视区外（rect 为 0），故先 scrollIntoView，
       再用**完整事件序列**直接派发点击（与图片 .btn-ok 同机制，不依赖坐标）。
    """
    ws = connect()
    try:
        r = open_video_panel(ws)
        if r == "notfound":
            return "FAIL: camera icon not found"

        # ① 等视频项渲染
        _wait_video_items(ws, 15)

        # ② 定位目标项并滚动到可视区
        js_find = """(function(){
var want=%(w)s, occ=%(o)d;
var all=[...document.querySelectorAll('.video-item')];
function T(e){var t=e.querySelector('.video-item-info-title');return t?t.textContent.trim():'';}
var hit=all.filter(function(e){return T(e)===want;});
var mode='exact';
if(hit.length<=occ){hit=all.filter(function(e){return T(e).indexOf(want)>=0;});mode='fuzzy';}
window.__v={total:all.length,mode:mode,n:hit.length,idx:-1};
if(hit.length<=occ) return JSON.stringify(window.__v);
var item=hit[occ];
var i=all.indexOf(item);
window.__v.idx=i;
item.scrollIntoView({block:'center'});
return JSON.stringify(window.__v);})()""" % {
            "w": json.dumps(title, ensure_ascii=False), "o": occurrence}
        info = json.loads(ev(ws, js_find) or "{}")

        # ②b 面板可能是旧缓存（新上传的视频不显示）→ 关闭重开刷新一次
        if info.get("idx", -1) < 0:
            _click_camera(ws)          # 关闭面板
            time.sleep(1.2)
            _click_camera(ws)          # 重新打开，拉取最新素材
            if _wait_video_items(ws, 15):
                info = json.loads(ev(ws, js_find) or "{}")

        if info.get("idx", -1) < 0:
            sample = ev(ws, r"""JSON.stringify([...document.querySelectorAll('.video-item')]
              .slice(0,10).map(function(e){var t=e.querySelector('.video-item-info-title');
              return t?t.textContent.trim():'';}))""")
            return "video '%s' #%d -> 未找到（mode=%s,total=%s）。库内标题示例：%s" % (
                title, occurrence, info.get("mode"), info.get("total"), sample)

        time.sleep(0.8)  # 等滚动后布局更新

        # ③ 派发完整事件序列点击发送按钮
        #   ⚠️ 只派发事件序列，不要再调用 b.click()——否则会重复发送两次！
        js_click = """(function(){
var i=window.__v.idx;
var item=[...document.querySelectorAll('.video-item')][i];
if(!item) return JSON.stringify({ok:false,reason:'item-gone'});
var b=item.querySelector('.send-video-btn');
if(!b) return JSON.stringify({ok:false,reason:'no-btn'});
b.scrollIntoView({block:'center'});
var r=b.getBoundingClientRect();
var o={bubbles:true,cancelable:true,view:window,
  clientX:r.left+(r.width||10)/2, clientY:r.top+(r.height||10)/2,
  button:0, buttons:1};
['pointerdown','mousedown','pointerup','mouseup','click'].forEach(function(t){
  var e2; try{e2=new PointerEvent(t,o);}catch(e){e2=new MouseEvent(t,o);}
  b.dispatchEvent(e2);
});
return JSON.stringify({ok:true,rect:[Math.round(r.left),Math.round(r.top),
  Math.round(r.width),Math.round(r.height)]});})()"""
        res = json.loads(ev(ws, js_click) or "{}")
        time.sleep(3)
        # 发送成功后素材库面板应自动关闭，据此二次校验。
        # ⚠️ 必须用可见性判断：面板关闭后 .video-item 仍在 DOM 里（数量不为 0），
        #    旧写法 `length===0` 永远为假 → 日志一直误报「仍打开」。
        closed = not _panel_open(ws)
        return "video '%s' #%d -> %s（%s｜面板%s）" % (
            title, occurrence, "已发送" if res.get("ok") else "失败:" + str(res.get("reason")),
            "精确匹配" if info.get("mode") == "exact" else "模糊匹配",
            "已关闭=已送达" if closed else "仍打开")
    finally:
        ws.close()


def list_videos():
    """列出素材库视频。返回 JSON 字符串（列表，每项 {t:标题, d:时长}）"""
    ws = connect()
    try:
        open_video_panel(ws)
        raw = ev(ws, """JSON.stringify([...document.querySelectorAll('.video-item')].map(function(e){
return {t:e.querySelector('.video-item-info-title').textContent.trim(),
d:(e.querySelector('.video-duration')||{}).textContent||''}}))""")
        # ⚠️ ev 返回的已是 JSON 字符串，不能再次 json.dumps（否则双重编码）
        return raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
    finally:
        ws.close()


def read_page():
    ws = connect()
    try:
        return ev(ws, 'document.body.innerText.replace(/\\n{2,}/g,"\\n").slice(0,3000)')
    finally:
        ws.close()


def shot(path):
    ws = connect()
    try:
        r = send(ws, "Page.captureScreenshot", {"format": "png"})
        with open(path, "wb") as f:
            f.write(base64.b64decode(r["result"]["data"]))
        return "saved " + path
    finally:
        ws.close()


# ---------------- 发送本地图片 ----------------
# 图片入口：点 .chat-icon-picture 会触发幻灯(lightbox)图片库；
# 若要发本地文件，需直接向 <input type=file accept=image/*> 注入文件后等上传完成再发送。
def probe_image_ui():
    """探查图片发送相关的 DOM 结构（调试用）"""
    ws = connect()
    try:
        return ev(ws, """JSON.stringify({
inputs:[...document.querySelectorAll('input[type=file]')].map(function(e,i){
  var p=e; for(var j=0;j<3&&p;j++) p=p.parentElement;
  return {i:i, accept:e.accept||'(any)', parentCls:p?String(p.className).slice(0,60):'', visible:e.offsetWidth>0};
}),
icons:[...document.querySelectorAll('.chat-icon-picture,.chat-icon-camera,.chat-icon')].map(function(e){
  return {cls:String(e.className)};
}),
editables:[...document.querySelectorAll('[contenteditable=true]')].length
})""")
    finally:
        ws.close()


def send_image(paths):
    """
    发送本地图片（实战验证通过 2026-09-14）。
    机制：向图片 input 注入文件 -> 弹出预览确认框 -> 点 .btn-ok 发送。
    关键：① 先移除遮挡层(.layer / z-index:2147483647)；
          ② 必须用完整鼠标事件序列派发到 .btn-ok，单纯 .click() 无效。
    """
    ws = connect()
    try:
        # 0) 清理遮挡层
        ev(ws, """(function(){var n=0;
document.querySelectorAll('.layer').forEach(function(e){e.remove();n++;});
document.querySelectorAll('div').forEach(function(e){var cs=getComputedStyle(e);if(cs.zIndex==='2147483647'){e.remove();n++;}});
return n;})()""")

        results = []
        for p in paths:
            p = os.path.abspath(p)
            if not os.path.isfile(p):
                results.append("SKIP(不存在) %s" % p)
                continue
            # 1) 定位图片 input
            send(ws, "DOM.enable")
            doc = send(ws, "DOM.getDocument", {"depth": -1})
            root = doc["result"]["root"]["nodeId"]
            q = send(ws, "DOM.querySelectorAll", {
                "nodeId": root,
                "selector": "input[type=file][accept*='image']"})
            nodes = q["result"].get("nodeIds", [])
            if not nodes:
                results.append("FAIL 未找到图片上传控件")
                break
            # 2) 注入文件
            send(ws, "DOM.setFileInputFiles", {"files": [p], "nodeId": nodes[0]})
            time.sleep(2.5)
            # 3) 等预览框出现
            ok = False
            for _ in range(10):
                n = ev(ws, "document.querySelectorAll('.btn-ok').length")
                if n:
                    ok = True
                    break
                time.sleep(1)
            if not ok:
                results.append("FAIL 预览框未出现: " + os.path.basename(p))
                continue
            # 4) 派发完整事件序列点击发送
            ev(ws, """(function(){
var b=document.querySelector('.btn-ok');
if(!b) return 'nf';
var r=b.getBoundingClientRect();
var o={bubbles:true,cancelable:true,view:window,
  clientX:r.left+r.width/2, clientY:r.top+r.height/2, button:0, buttons:1};
['pointerdown','mousedown','pointerup','mouseup','click'].forEach(function(t){
  var e2; try{e2=new PointerEvent(t,o);}catch(e){e2=new MouseEvent(t,o);}
  b.dispatchEvent(e2);
});
return 'ok';})()""")
            time.sleep(3.5)
            gone = ev(ws, "document.querySelectorAll('.btn-ok').length") == 0
            results.append(("OK 已发送 " if gone else "MAYBE ")+os.path.basename(p))
        return "\n".join(results)
    finally:
        ws.close()


def send_images_batch(paths):
    """
    逐张发送多张本地图片（实战验证通过 2026-09-14）。
    ⚠️ 关键：图片 input 的 multiple=false，一次只能选一张。
       因此必须「注入一张 -> 确认发送 -> 再注入下一张」循环。
    返回发送结果明细。
    """
    ws = connect()
    try:
        ev(ws, """(function(){var n=0;
document.querySelectorAll('.layer').forEach(function(e){e.remove();n++;});
document.querySelectorAll('div').forEach(function(e){var cs=getComputedStyle(e);if(cs.zIndex==='2147483647'){e.remove();n++;}});
return n;})()""")
        files = [os.path.abspath(p) for p in paths
                 if os.path.isfile(os.path.abspath(p))]
        missing = [p for p in paths if not os.path.isfile(os.path.abspath(p))]
        if not files:
            return "FAIL: 无有效文件"

        results = []
        for p in files:
            # 定位图片 input（每次重新查，避免 DOM 变动后 nodeId 失效）
            send(ws, "DOM.enable")
            doc = send(ws, "DOM.getDocument", {"depth": -1})
            root = doc["result"]["root"]["nodeId"]
            q = send(ws, "DOM.querySelectorAll", {
                "nodeId": root,
                "selector": "input[type=file][accept*='image']"})
            nodes = q["result"].get("nodeIds", [])
            if not nodes:
                results.append("FAIL(no-input) " + os.path.basename(p))
                continue
            # 注入单张
            send(ws, "DOM.setFileInputFiles", {"files": [p], "nodeId": nodes[0]})
            time.sleep(2.5)
            # 等预览框
            appeared = False
            for _ in range(12):
                if ev(ws, "document.querySelectorAll('.btn-ok').length"):
                    appeared = True
                    break
                time.sleep(1)
            if not appeared:
                results.append("FAIL(no-preview) " + os.path.basename(p))
                continue
            # 派发完整事件序列点击发送
            ev(ws, """(function(){
var b=document.querySelector('.btn-ok');
if(!b) return 'nf';
var r=b.getBoundingClientRect();
var o={bubbles:true,cancelable:true,view:window,
  clientX:r.left+r.width/2, clientY:r.top+r.height/2, button:0, buttons:1};
['pointerdown','mousedown','pointerup','mouseup','click'].forEach(function(t){
  var e2; try{e2=new PointerEvent(t,o);}catch(e){e2=new MouseEvent(t,o);}
  b.dispatchEvent(e2);
});
return 'ok';})()""")
            time.sleep(3.5)
            gone = ev(ws, "document.querySelectorAll('.btn-ok').length") == 0
            results.append(("OK " if gone else "MAYBE ") + os.path.basename(p))
            time.sleep(1)
        for m in missing:
            results.append("SKIP(不存在) " + os.path.basename(m))
        return "\n".join(results)
    finally:
        ws.close()


def send_mix_pair():
    r"""
    发送「A B混合」对比图（款式未明时的标准开场）。
    动态扫描「客服资料根目录\实拍图\A B混合」下所有图片并逐张发送，
    便于用户随时更换/增减对比图而无需改代码。
    若目录为空，回退到内置默认两张文件名。

    ⚠️ 路径经 asset_path.resolve()：本机绝对路径存在就用它；
    换电脑/拷给别人时自动改用「程序目录\素材\实拍图\A B混合」。
    """
    mix = os.path.join(r"D:\work\客服资料", "实拍图", "A B混合")
    try:
        import asset_path
        mix = asset_path.resolve(mix)
    except Exception:
        pass
    exts = (".jpg", ".jpeg", ".png", ".webp", ".bmp")
    if os.path.isdir(mix):
        imgs = sorted(f for f in os.listdir(mix)
                      if os.path.isfile(os.path.join(mix, f))
                      and f.lower().endswith(exts))
    else:
        imgs = []
    if not imgs:
        imgs = ["A款脚踏实拍图1.jpg", "B款脚踏挡杆实拍 (4).jpg"]
    paths = [os.path.join(mix, f) for f in imgs]
    return "【A B混合】共 %d 张\n%s" % (len(paths), send_images_batch(paths))


# ---------------- 自动巡检支持（全自动客服用） ----------------

# ⚠️ 会话项筛选规则（list_pending_chats / open_chat_by_index 必须完全一致！）
#
# 2026-09-15 实测定论（三次踩坑后的最终结论）：
#   拼多多「今日接待」页的待回复会话**不在固定的一个容器里**：
#     - 已回复过、客户又发消息的会话 → UL.already-unreply（标题『已回复』）
#     - 新进线、5 分钟内未回复的会话 → 分组 class 是 `five-minute`，
#       **类名不含 unreply**，条目预览里带『已等待X分钟』。
#   旧实现用 `[class*=unreply]` 选容器 —— 直接漏掉 five-minute 分组，
#   导致客户发的『老板有没有安装视频』根本没进入巡检列表、视频一直发不出去。
#
# 现在的做法（与分组名解耦，抗改版）：
#   扫描 .chat-list-box（当前激活的会话面板）下**可见**的全部 .chat-item，
#   再排除「全部会话 / 标记 / 收藏 / 垃圾消息」等非目标分组。
#   是否真需要回复，仍由调用方打开会话后看 get_last_customer_msg()。
_CHAT_ITEMS_JS = r"""
function _ciItems(){
  var out=[];
  var root=document.querySelector('.left-panel')||document;
  root.querySelectorAll('.chat-item').forEach(function(c){
    if(c.offsetParent===null) return;          // 只取当前激活面板里的会话
    if(c.closest('.all-chat-list')) return;    // 排除「全部会话」tab
    if(c.closest('.mark-chat-list')) return;   // 排除 收藏/咨询未下单/垃圾消息 等分组
    var lines=(c.innerText||'').split('\n').map(function(s){return s.trim();}).filter(Boolean);
    if(!lines.length) return;
    var name=(lines[0]||'').replace(/\s+/g,'');
    if(!name || name==='游客') return;
    // 侧栏每条结构不固定：[昵称, (下单数标签), 消息, (时间), 转移会话(悬停按钮)]
    // 故把「转移会话」「时间」「下单数」都剥离，剩下的才是真正的消息预览。
    var rest=lines.slice(1).filter(function(s){ return s!=='转移会话'; });
    var time='';
    for(var i=rest.length-1;i>=0;i--){
      if(/^(\d{1,2}:\d{2}|昨天|星期.|刚刚|已等待\s*\d+\s*分钟)$/.test(rest[i])){
        time=rest.splice(i,1)[0]; break;
      }
    }
    var tag='';
    if(rest.length>1 && /下单数|已下单|咨询未下单/.test(rest[0])) tag=rest.shift();
    var msg=rest.join(' ');
    out.push({el:c, name:name, msg:msg, time:time, tag:tag, lines:lines});
  });
  return out;
}
function _ciGroup(c){
  var e=c.parentElement;
  for(var k=0;k<4&&e;k++){
    var cl=(e.className||'').toString();
    if(cl.indexOf('unreply')>=0 || cl.indexOf('five-minute')>=0) return cl;
    e=e.parentElement;
  }
  return '';
}
function _ciTitle(c){
  var e=c.parentElement;
  for(var k=0;k<4&&e;k++){
    var t=e.querySelector('.chat-list-title');
    if(t) return (t.innerText||'').trim();
    e=e.parentElement;
  }
  return '';
}
"""


def list_pending_chats():
    """
    列出【当前激活面板中需要关注的会话】（用于全自动客服巡检）。
    返回 [{'idx':序号, 'name':昵称, 'preview':最后消息, 'time':时间,
           'group':分组class, 'title':分组标题}]
    是否真的需要回复，由调用方打开会话后用 get_last_customer_msg() 判定。
    """
    ws = connect()
    try:
        js = ("(function(){" + _CHAT_ITEMS_JS + r"""
var its=_ciItems(), out=[];
its.forEach(function(it,i){
  out.push({idx:i, name:it.name, preview:it.msg, time:it.time, tag:it.tag,
            group:_ciGroup(it.el), title:_ciTitle(it.el)});
});
return JSON.stringify(out);})()""")
        return json.loads(ev(ws, js) or "[]")
    finally:
        ws.close()


def open_chat_by_index(idx):
    """
    按 list_pending_chats() 返回的序号打开会话。
    ⚠️ 两者必须使用**完全相同的筛选与顺序**（共用 _CHAT_ITEMS_JS），否则会点错会话。
    客户昵称被平台掩码（如 ** / 错**），无法唯一识别，故用序号定位。
    """
    ws = connect()
    try:
        js = ("(function(){" + _CHAT_ITEMS_JS + r"""
var its=_ciItems(), i=%d;
if(i<0 || i>=its.length) return null;
var b=its[i].el;
b.scrollIntoView({block:'center'});
var r=b.getBoundingClientRect();
return {x:Math.round(r.left+r.width/2), y:Math.round(r.top+r.height/2)};})()""" % int(idx))
        r = click_el(ws, js)
        time.sleep(2.5)
        ok = ev(ws, "!!document.querySelector('textarea.custom-scroll')")
        return {"click": r, "input_ready": bool(ok)}
    finally:
        ws.close()


def open_chat_by_match(name, preview=""):
    """
    按【昵称 + 预览文本】打开会话（比序号更稳）。

    为什么需要它：巡检时若按序号定位，**回复完一条后侧栏会重排**
    （会话移到『已回复』组顶部/顺序变化），后续序号就会指向别的客户，
    有发错人的风险。改为回复前重新定位「昵称+预览」都匹配的那一条。
    返回 {'ok':bool, 'click':str, 'input_ready':bool}
    """
    ws = connect()
    try:
        js = ("(function(){" + _CHAT_ITEMS_JS + r"""
var want=%(n)s, pv=%(p)s;
var its=_ciItems();
function score(it){
  if(it.name!==want) return -1;
  var p=it.msg||'';
  if(!pv) return 1;
  if(p===pv) return 2;                  // 预览完全一致最佳
  if(p.indexOf(pv)>=0 || pv.indexOf(p)>=0) return 1;   // 前缀被截断时退化为包含
  return 0;
}
var best=-1, bs=-1;
its.forEach(function(it,i){ var s=score(it); if(s>bs){bs=s; best=i;} });
if(bs<=0) return null;
var b=its[best].el;
b.scrollIntoView({block:'center'});
var r=b.getBoundingClientRect();
return {x:Math.round(r.left+r.width/2), y:Math.round(r.top+r.height/2)};})()""" % {
            "n": json.dumps(name, ensure_ascii=False),
            "p": json.dumps(preview[:60], ensure_ascii=False)})
        r = click_el(ws, js)
        time.sleep(2.2)
        ok = ev(ws, "!!document.querySelector('textarea.custom-scroll')")
        return {"ok": r != "notfound", "click": r, "input_ready": bool(ok)}
    finally:
        ws.close()


def is_bot_paused():
    """当前会话是否被平台暂停机器人接待（需人工恢复接待）"""
    ws = connect()
    try:
        t = ev(ws, "document.body.innerText") or ""
        return "立即恢复接待" in t
    finally:
        ws.close()


# 系统/机器人提示（不算客户消息）
_SYS_MSG_RE = ("您接待过此消费者", "机器人已暂停接待", "消费者多次触发",
               "机器人回复纠错", "纠错", "转接", "请提供热线电话",
               "已退出接待", "邀请关注", "邀请下单",
               # ── 2026-09-19 实测补充（都是平台系统消息，不是客户打的字）──
               # 订单/物流通知：曾导致「只是改收货地址的客户」被当成咨询客户、
               # 并按错误的商品（右侧面板的店铺待支付订单）走品类路由发素材。
               "买家申请修改", "收货地址修改成功", "同意修改", "配送至",
               "收件人", "联系电话", "订单编号", "待支付",
               # 进店来源提示：是【唯一与会话绑定的商品来源】，但本身不是客户消息
               "当前用户来自", "商品详情页",
               # 机器人暂停 / 平台风控警告
               "已暂停接待", "诱导第三方", "保证金")


def get_last_customer_msg():
    """
    读取【当前已打开会话】的最后一条真实消息。
    返回 {'found':bool, 'is_me':bool, 'text':str}
      is_me=True  → 最后一条是我方发的（无需回复）
      is_me=False → 最后一条是客户发的（需要回复）

    ⚠️ 2026-09-15 实测修正（重要）：
      归属**不能**再用「文本里有没有『主账号』」判断！
      客户发的【引用消息】文本里会带『主账号：』（引用了我方消息），
      导致客户消息被误判成我方消息 → 程序直接跳过不回复（本次实测踩坑）。
      ✅ 正确判据（DOM 结构）：
         我方消息容器 = `.cs-item`（内含 .nickname『主账号』）
         客户消息容器 = `.buyer-item`（内含 .avatar，无 nickname）
      另：引用消息真正的新内容在 `.quote-new-msg`，需剔除被引用的旧消息文本。
    """
    ws = connect()
    try:
        js = r"""(function(){
var msgs=[].slice.call(document.querySelectorAll('.msg-list .onemsg'));
// 需要剔除的噪声节点：昵称、时间、被引用的旧消息、视频角标
var DROP='.nickname,.message-time,.be-quote,.be-quote-user,.be-quote-content,'
       + '.quote-video-content,.video-duration,.video-play-button';
function txt(e){
  var q=e.querySelector('.quote-new-msg');
  if(q) return (q.innerText||'').replace(/\n+/g,' ').trim();
  var c=e.cloneNode(true);
  try{ c.querySelectorAll(DROP).forEach(function(n){ n.remove(); }); }catch(x){}
  return (c.innerText||'').replace(/\n+/g,' ').trim();
}
var bad=%(bad)s;
function isSys(t){for(var i=0;i<bad.length;i++){if(t.indexOf(bad[i])>=0)return true;}return false;}
// ⚠️ 2026-09-19 实测（重要，防发错素材）：
//   系统消息（订单/物流/进店提示/平台风控）的 .onemsg 内层
//   **既没有 .buyer-item / .cs-item，也没有 .msg-content 气泡**。
//   旧逻辑在这种情况下走兜底分支 me=false → 被误判成「客户发了消息」，
//   于是给「只是修改收货地址」的客户走品类路由发素材（实测踩坑）。
//   ✅ 新判据：内层没有任何气泡容器的 .onemsg 一律视为系统消息，直接跳过。
function hasBubble(e){
  return !!(e.querySelector('.buyer-item') || e.querySelector('.cs-item')
         || e.querySelector('.msg-content') || e.querySelector('.msg-content-box'));
}
var real=msgs.filter(function(e){
  if(!hasBubble(e)) return false;
  var t=txt(e);
  if(!t) return false;
  if(/^\d{4}年\d{2}月\d{2}日[\s\S]*$/.test(t) && t.length<40) return false;
  return !isSys(t);});
if(!real.length) return JSON.stringify({found:false});
var last=real[real.length-1], t=txt(last);
t=t.replace(/^\d{4}年\d{2}月\d{2}日\s*\d{2}:\d{2}:\d{2}\s*/,'');
t=t.replace(/^主账号[：:]\s*/,'');
// 归属判定：① class（.buyer-item=客户 / .cs-item=我方）
//           ② 类名缺失时用【气泡左右位置】兜底（靠右=我方，2026-09-15 实测）
var me;
if(last.querySelector('.buyer-item')) me=false;
else if(last.querySelector('.cs-item')) me=true;
else {
  var box=last.querySelector('.msg-content')||last.querySelector('.msg-content-box');
  if(box){
    var br=box.getBoundingClientRect(), rr=last.getBoundingClientRect();
    me = (br.left-rr.left) > rr.width*0.4;
  } else me=false;
}
return JSON.stringify({found:true, is_me:me, text:t.slice(0,400)});})()""" % {
            "bad": json.dumps(list(_SYS_MSG_RE), ensure_ascii=False)}
        return json.loads(ev(ws, js) or "{}")
    finally:
        ws.close()


# ---------------- 全量会话遍历（记忆同步 / syncchats） ----------------
#
# ⚠️ 为什么需要这一套：普通巡检 list_pending_chats() 只读取「当前激活面板里
# 可见」的会话（offsetParent!==null），而大量的历史客服、其它分组、还没滚动
# 加载出来的会话根本不会被扫到 —— 这就是「很多客服没同步到记忆库」的根因。
# 这里提供「像自动检索一样逐一读取」的能力：滚动触发懒加载 → 跨分组收集全部
# 会话 → 逐一打开读完整聊天 → 由调用方提取问答对入库。
_ALL_CHAT_JS = r"""
function _acContainers(){
  // 覆盖所有可能的会话容器（分组不定名，宽匹配再排除非目标分组）
  var containers=[];
  var seen=new Set();
  function add(el){
    if(!el||seen.has(el)) return;
    seen.add(el); containers.push(el);
  }
  document.querySelectorAll('[class*="chat-list-box"],[class*="chat-list"],[class*="unreply"],[class*="five-minute"]')
    .forEach(add);
  // 兜底：把含 .chat-item 的元素也纳入
  document.querySelectorAll('.chat-item').forEach(function(c){ add(c.parentElement); });
  return containers;
}
function _acItems(opts){
  opts=opts||{};
  var out=[];
  _acContainers().forEach(function(root){
    root.querySelectorAll('.chat-item').forEach(function(c){
      if(opts.invisible===false && c.offsetParent===null) return;  // 只要可见
      var lines=(c.innerText||'').split('\n').map(function(s){return s.trim();}).filter(Boolean);
      if(!lines.length) return;
      var name=(lines[0]||'').replace(/\s+/g,'');
      if(!name || name==='游客') return;
      var rest=lines.slice(1).filter(function(s){ return s!=='转移会话'; });
      var ttime='';
      for(var i=rest.length-1;i>=0;i--){
        if(/^(\d{1,2}:\d{2}|昨天|星期.|刚刚|已等待\s*\d+\s*分钟)$/.test(rest[i])){
          ttime=rest.splice(i,1)[0]; break;
        }
      }
      var tag='';
      if(rest.length>1 && /下单数|已下单|咨询未下单/.test(rest[0])) tag=rest.shift();
      out.push({name:name, preview:rest.join(' '), time:ttime, tag:tag});
    });
  });
  // 去重（昵称+预览+时间都相同视为同一会话）
  var dedup=[], key=new Set();
  out.forEach(function(it){
    var k=(it.name||'')+'|'+(it.preview||'')+'|'+(it.time||'');
    if(key.has(k)) return; key.add(k); dedup.push(it);
  });
  return dedup;
}
function _acScrollLoad(){
  // 对含会话项的滚动容器反复滚到底，触发懒加载加载更多历史会话。
  // 返回本轮滚动是否可能还有更多（scrollTop 是否被推进）。
  var scrollers=[];
  var seen=new Set();
  _acContainers().forEach(function(root){
    var el=root;
    for(var k=0;k<5&&el;k++){
      var st=window.getComputedStyle(el);
      if(st.overflowY==='auto'||st.overflowY==='scroll'||
         st.overflow==='auto'||st.overflow==='scroll'){
        if(!seen.has(el)){seen.add(el); scrollers.push(el);}
        'break';
      }
      el=el.parentElement;
    }
  });
  var before=document.querySelectorAll('.chat-item').length;
  var moved=0;
  scrollers.forEach(function(s){
    var h=s.scrollHeight, t=s.scrollTop;
    s.scrollTop=h;               // 滚到底触发加载更多
    if(s.scrollTop>t) moved=1;
  });
  return {moved:moved, before:before, after:document.querySelectorAll('.chat-item').length};
}
"""


def collect_all_chats(max_rounds=40, rounds_each_sec=0.6):
    """
    ★ 完整遍历客服工作台会话（同步用）：
    反复滚动触发懒加载，跨全部分组容器收集所有会话项并去重。
    返回 [{'name','preview','time','tag'}, ...]。
    失败返回 []（绝不让调用方崩溃）。
    """
    ws = connect()
    try:
        # ① 先激活工作台，且尽量展开各分组
        try:
            goto_workbench()
        except Exception:
            pass
        # ② 反复滚动加载，直到数量不再增长
        prev_total = 0
        for _ in range(max_rounds):
            r = ev(ws, "(function(){" + _ALL_CHAT_JS + """
var res=_acScrollLoad();
return JSON.stringify({moved:res.moved,before:res.before,after:res.after});})()""")
            info = json.loads(r or "{}")
            after = int(info.get("after") or 0)
            if after <= prev_total and not info.get("moved"):
                break
            prev_total = after
            time.sleep(rounds_each_sec)
        # ③ 收集全部
        raw = ev(ws, "(function(){" + _ALL_CHAT_JS + """
return JSON.stringify(_acItems({invisible:false}));})()""")
        return json.loads(raw) if isinstance(raw, str) else (raw or [])
    except Exception:
        return []
    finally:
        ws.close()


def open_chat_scroll_match(name, preview=""):
    """
    按『昵称 + 预览』滚动定位并打开任意会话（不限当前面板可见范围）。
    返回 {'ok':bool, 'click':str, 'input_ready':bool}。
    """
    ws = connect()
    try:
        js = ("(function(){" + _ALL_CHAT_JS + r"""
var want=%(n)s, pv=%(p)s;
var its=[]; _acContainers().forEach(function(root){
  root.querySelectorAll('.chat-item').forEach(function(c){
    var lines=(c.innerText||'').split('\n').map(function(s){return s.trim();}).filter(Boolean);
    if(!lines.length) return;
    var name=(lines[0]||'').replace(/\s+/g,'');
    if(!name||name==='游客') return;
    var rest=lines.slice(1).filter(function(s){ return s!=='转移会话'; });
    var pv2=''; 
    for(var i=rest.length-1;i>=0;i--){
      if(/^(\d{1,2}:\d{2}|昨天|星期.|刚刚|已等待\s*\d+\s*分钟)$/.test(rest[i])){rest.splice(i,1);}
    }
    pv2=rest.join(' ');
    its.push({c:c, name:name, pv:pv2});
  });
});
function score(it){
  if(it.name!==want) return -1;
  if(!pv) return 1;
  if(it.pv===pv) return 2;
  a=(it.pv||'').indexOf(pv)>=0; b=pv.indexOf(it.pv||'')>=0;
  if(a||b) return 1;
  return 0;
}
var best=-1,bs=-1;
its.forEach(function(it,i){var s=score(it); if(s>bs){bs=s;best=i;}});
if(best<0) return null;
var c=its[best].c;
c.scrollIntoView({block:'center'});
var r=c.getBoundingClientRect();
return {x:Math.round(r.left+r.width/2), y:Math.round(r.top+r.height/2)};})()""" % {
            "n": json.dumps(name, ensure_ascii=False),
            "p": json.dumps(preview[:60], ensure_ascii=False)})
        r = click_el(ws, js)
        time.sleep(2.5)
        ok = ev(ws, "!!document.querySelector('textarea.custom-scroll')")
        return {"ok": r != "notfound", "click": r, "input_ready": bool(ok)}
    finally:
        ws.close()


def read_chat_messages():
    """
    读取【当前已打开会话】的完整真实消息序列（记忆同步用）。
    返回 [{'role':'user'|'assistant', 'text':str}, ...] 旧→新。
    复用 get_last_customer_msg 相同的清洗与归属逻辑，但返回全部消息。
    """
    ws = connect()
    try:
        js = r"""(function(){
var DROP='.nickname,.message-time,.be-quote,.be-quote-user,.be-quote-content,'
       + '.quote-video-content,.video-duration,.video-play-button';
var bad=%(bad)s;
function isSys(t){for(var i=0;i<bad.length;i++){if(t.indexOf(bad[i])>=0)return true;}return false;}
function hasBubble(e){
  return !!(e.querySelector('.buyer-item') || e.querySelector('.cs-item')
         || e.querySelector('.msg-content') || e.querySelector('.msg-content-box'));
}
function txt(e){
  var q=e.querySelector('.quote-new-msg');
  if(q) return (q.innerText||'').replace(/\n+/g,' ').trim();
  var c=e.cloneNode(true);
  try{ c.querySelectorAll(DROP).forEach(function(n){ n.remove(); }); }catch(x){}
  return (c.innerText||'').replace(/\n+/g,' ').trim();
}
var out=[];
[].slice.call(document.querySelectorAll('.msg-list .onemsg')).forEach(function(e){
  if(!hasBubble(e)) return;
  var t=txt(e);
  if(!t) return;
  if(/^\d{4}年\d{2}月\d{2}日[\s\S]*$/.test(t) && t.length<40) return;
  if(isSys(t)) return;
  t=t.replace(/^\d{4}年\d{2}月\d{2}日\s*\d{2}:\d{2}:\d{2}\s*/,'');
  t=t.replace(/^主账号[：:]\s*/,'');
  var me;
  if(e.querySelector('.buyer-item')) me=false;
  else if(e.querySelector('.cs-item')) me=true;
  else {
    var box=e.querySelector('.msg-content')||e.querySelector('.msg-content-box');
    if(box){
      var br=box.getBoundingClientRect(), rr=e.getBoundingClientRect();
      me=(br.left-rr.left)>rr.width*0.4;
    } else me=false;
  }
  if(!t) return;
  out.push({role: me?'assistant':'user', text:t.slice(0,400)});
});
return JSON.stringify(out);})()""" % {"bad": json.dumps(list(_SYS_MSG_RE), ensure_ascii=False)}
        raw = ev(ws, js)
        return json.loads(raw) if isinstance(raw, str) else (raw or [])
    finally:
        ws.close()


# ---------------- 商品类目路由（新命令 consult 的核心） ----------------

def get_consult_goods():
    """
    读取【当前已打开会话】的咨询商品信息。
    返回 dict: {title, spec, price, img, source} ；读取不到返回 {}

    ⚠️⚠️ 2026-09-19 实测重写（高危缺陷修复，改代码前必读）：
      旧实现只读 `.order-goods-box` —— 那是**右侧面板『店铺待支付订单』**里的卡片，
      **完全不跟随会话**！实测切换 3 个不同会话，读到的永远是同一笔订单：
        #1（黑旗600脚踏 ￥138 订单通知）→ 春风500SR定风翼堵盖 ￥95.58
        #2（无极CU530脚踏 ￥198 咨询）  → 春风500SR定风翼堵盖 ￥95.58
        #0（刹车踏板 ￥45.60 咨询）      → 春风500SR定风翼堵盖 ￥95.58
      后果：所有走『品类路由』的会话都会按定风翼堵盖发开场素材
            → 给咨询脚踏/挡杆/刹车的客户发错货品。

    ✅ 新判据（分层，source 字段标明来源）：
      1) `enter_hint`（首选）：会话消息里最近一条「当前用户来自 商品详情页」系统提示，
         它与会话**强绑定**，是唯一可信的咨询商品来源。
      2) `order_box`（兜底）：右侧订单卡片，但**必须**其商品名片段出现在本会话消息文本中
         （一致性校验），否则丢弃 —— 防止再拿别人的待支付订单当咨询商品。
      3) 都读不到 → 返回 {}，由调用方用『客户消息文本』兜底判类目。
    """
    ws = connect()
    try:
        js = r"""(function(){
var out={title:'',spec:'',price:'',img:'',source:''};
var msgs=[].slice.call(document.querySelectorAll('.msg-list .onemsg'));

var hint=null;
for(var i=msgs.length-1;i>=0;i--){
  var t=(msgs[i].innerText||'');
  if(t.indexOf('当前用户来自')>=0 || t.indexOf('商品详情页')>=0){ hint=msgs[i]; break; }
}
if(hint){
  var lines=(hint.innerText||'').split('\n').map(function(x){return x.trim();}).filter(Boolean);
  var price='', title='';
  lines.forEach(function(L){
    if(L.indexOf('当前用户来自')>=0) return;
    if(L.indexOf('商品详情页')>=0) return;
    if(L.indexOf('来自手机端')>=0) return;
    if(/^[￥¥]/.test(L)){ if(!price) price=L; return; }
    if(L.length>title.length) title=L;
  });
  if(title){
    out.title=title; out.price=price; out.source='enter_hint';
    var im=hint.querySelector('img'); out.img=im?im.src:'';
    return JSON.stringify(out);
  }
}

var box=document.querySelector('.order-goods-box');
if(!box) return JSON.stringify(out);
var n=box.querySelector('.goods-name'), p=box.querySelector('.goods-price');
var t2=n?(n.innerText||'').trim():'', p2=p?(p.innerText||'').trim():'';
if(!t2) return JSON.stringify(out);
var blob=msgs.map(function(e){return e.innerText||'';}).join(' ');
var probe=t2.slice(0, Math.min(8, t2.length));
if(probe && blob.indexOf(probe)>=0){
  var s=box.querySelector('.goods-spec');
  out.title=t2; out.spec=s?(s.innerText||'').trim():''; out.price=p2;
  var im2=box.querySelector('img'); out.img=im2?im2.src:''; out.source='order_box';
}
return JSON.stringify(out);})()"""
        raw = ev(ws, js)
        return json.loads(raw) if raw else {}
    finally:
        ws.close()


def load_category_routes():
    """从 kb.json 读取可扩展的『商品类目路由』表（用户后续补充类目只需改 json）"""
    kb = _kb_file()
    with open(kb, encoding="utf-8") as f:
        data = json.load(f)
    routes = data.get("_商品类目路由", {})
    return {k: v for k, v in routes.items() if not k.startswith("_")}


def match_category(title, spec=""):
    """按关键词匹配类目路由，返回 (类目名, 路由配置) 或 (None, None)"""
    text = ((title or "") + " " + (spec or "")).lower()
    for name, cfg in load_category_routes().items():
        for kw in cfg.get("关键词", []):
            if kw.lower() in text:
                return name, cfg
    return None, None


def consult_route(auto_send=True, goods=None):
    """
    【新命令 consult】读取当前会话咨询商品 → 按类目路由 → 执行对应开场动作。

    路由规则（可在 kb.json 的 `_商品类目路由` 中扩展）：
      - 含「脚踏」「挡杆」等 → 发 `实拍图/A B混合` 全部图片 + 引导话术（走选款流程）
      - 含「定风翼堵盖」「短尾」等 → 资料待补充，返回提示（预留槽位）

    auto_send=False 时仅返回决策结果，不实际发送（预演用）。
    """
    goods = goods or get_consult_goods()
    title = goods.get("title", "")
    spec = goods.get("spec", "")
    cat, cfg = match_category(title, spec)

    head = "【会话商品】%s | %s" % (title or "(未读到)", spec or "-")

    if not cat:
        return (head + "\n【路由】未匹配到已知类目 → 走人工/兜底话术。\n"
                "提示：可在 kb.json 的 `_商品类目路由` 中新增该类目关键词。")

    action = cfg.get("动作", "")
    status = cfg.get("状态", "")
    lines = [head, "【匹配类目】%s" % cat, "【动作】%s（%s）" % (action, status or "-")]

    # 待配置类目：资料未到，只提示
    if action in ("待配置", "pending") or (status and status.startswith("pending")):
        lines.append("【结果】该品类素材尚未配置（%s）。"
                     "素材目录：%s" % (status or "资料待补充", cfg.get("素材目录", "-")))
        return "\n".join(lines)

    if not auto_send:
        lines.append("【结果】预演模式，未实际发送。")
        return "\n".join(lines)

    # ---- 执行发送 ----
    reply = cfg.get("话术", "")
    if reply:
        lines.append("【话术】%s" % send_text(reply))
    if action == "send_mix_pair":
        lines.append("【素材】\n" + send_mix_pair())
    elif action == "send_images":
        d = cfg.get("素材目录", "")
        exts = (".jpg", ".jpeg", ".png", ".webp")
        imgs = sorted(os.path.join(d, f) for f in os.listdir(d)
                      if f.lower().endswith(exts)) if os.path.isdir(d) else []
        lines.append("【素材】\n" + (send_images_batch(imgs) if imgs else "目录为空: " + d))
    else:
        lines.append("【结果】未知动作 '%s'，未发送。" % action)
    return "\n".join(lines)


def _load_style_module():
    """
    加载「款式识别」模块。
      · 常规：同目录下的 款式识别.py（中文模块名，用 importlib 动态加载）
      · 单文件版 / exe 打包版：该模块已在 sys.modules 里（同一命名空间）→ 直接复用
    """
    m = sys.modules.get("款式识别")
    if m is not None:
        return m
    import importlib.util
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "款式识别.py")
    spec = importlib.util.spec_from_file_location("kps_style", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ---------------- 素材库上传（图片空间 → 客服专用视频） ----------------
# ⭐ 重要发现（2026-09-15）：拼多多「图片空间」的『售后/客服/申诉专用视频』
#    就是聊天窗口『请选择视频』面板的数据源。
#    该页面上传控件 accept=(any), multiple=true —— 可用 CDP 注入本地 mp4 自动上传，
#    上传成功后素材库标题 = 原文件名（去扩展名）。
#    这打通了『本地视频 → 素材库 → 发给客户』的完整链路。
MATERIAL_URL = "https://mms.pinduoduo.com/material/service"


def connect_page(kw, auto_open_url=None):
    """连接 URL 含 kw 的标签页；不存在时用 auto_open_url 新建标签打开"""
    def _find():
        with urllib.request.urlopen(DEBUGGER + "/json/list", timeout=8) as r:
            ts = json.load(r)
        for t in ts:
            if t.get("type") == "page" and kw in (t.get("url") or ""):
                return t
        return None

    t = _find()
    if t is None and auto_open_url:
        # 新建标签页打开（CDP /json/new 需 PUT）
        try:
            req = urllib.request.Request(
                DEBUGGER + "/json/new?" + urllib.parse.quote(auto_open_url, safe=":/?#=&"),
                method="PUT")
            with urllib.request.urlopen(req, timeout=10) as r:
                json.load(r)
            for _ in range(15):
                time.sleep(1)
                t = _find()
                if t:
                    break
        except Exception:
            pass
    if t is None:
        raise RuntimeError("未找到页面(%s)，请手动打开 %s" % (kw, auto_open_url or ""))
    return websocket.create_connection(
        t["webSocketDebuggerUrl"], timeout=120, suppress_origin=True)


def upload_videos(paths, timeout=180):
    """
    把本地视频上传到拼多多素材库【客服专用视频】。
    上传完成后素材库标题 = 原文件名（去扩展名），可被 send_video 按标题发送。
    返回上传结果摘要。
    """
    files = [os.path.abspath(p) for p in paths if os.path.isfile(os.path.abspath(p))]
    missing = [p for p in paths if not os.path.isfile(os.path.abspath(p))]
    if not files:
        return "FAIL: 无有效视频文件\n" + "\n".join("SKIP " + os.path.basename(m) for m in missing)

    ws = connect_page("material", MATERIAL_URL)
    try:
        # 关闭可能残留的弹窗
        ev(ws, """(function(){var n=0;
document.querySelectorAll('.el-dialog__close,[class*=dialog] [class*=close]').forEach(function(e){
  try{e.click();n++;}catch(x){}});return n;})()""")
        time.sleep(1)

        send(ws, "DOM.enable")
        doc = send(ws, "DOM.getDocument", {"depth": -1})
        root = doc["result"]["root"]["nodeId"]
        q = send(ws, "DOM.querySelectorAll", {"nodeId": root, "selector": "input[type=file]"})
        nodes = q["result"].get("nodeIds", [])
        if not nodes:
            return "FAIL: 未找到图片空间的上传控件"
        # 注入全部文件（该控件 multiple=true，可一次多选）
        send(ws, "DOM.setFileInputFiles", {"files": files, "nodeId": nodes[0]})

        # 轮询等待上传完成弹窗
        done = False
        tip = ""
        for _ in range(max(1, timeout // 2)):
            time.sleep(2)
            t = ev(ws, "document.body.innerText") or ""
            if "上传完成" in t or "本次成功上传" in t:
                done = True
                m = (re.search(r"本次成功上传\s*(\d+)\s*个文件", t)
                     or re.search(r"上传完成\s*\((\d+)\s*/\s*(\d+)\)", t))
                n_ok = m.group(1) if m else "?"
                tip = "成功上传 %s/%d 个文件" % (n_ok, len(files))
                break
            if "上传失败" in t or "失败" in t.split("上传完成")[0][-200:]:
                tip = "上传出现失败提示"
                break

        # 关闭弹窗
        ev(ws, """(function(){var n=0;
[...document.querySelectorAll('button,span,div')].forEach(function(e){
  if((e.innerText||'').trim()==='关闭' && e.offsetHeight>0){try{e.click();n++;}catch(x){}}});return n;})()""")
        time.sleep(0.8)

        names = [os.path.basename(f) for f in files]
        head = ("✅ " + tip) if done else ("⚠️ 未检测到完成提示（可能仍在处理，请稍后在素材库确认）")
        out = [head, "素材库标题（=文件名去扩展名）："]
        for nm in names:
            out.append("  · " + os.path.splitext(nm)[0])
        for m in missing:
            out.append("  SKIP(不存在) " + os.path.basename(m))
        return "\n".join(out)
    finally:
        ws.close()


def sync_videos(style_key):
    """
    【命令 syncvideo】把某款式本地文件夹里的视频**全部上传**到素材库，
    并返回上传后的素材库标题（供配置 _视频映射）。
    style_key: A / B
    """
    m = _load_style_module()
    k = (style_key or "").strip().upper()
    if k.startswith("A"):
        style, folder = "A款脚踏", m.A_VIDEO_DIR
    elif k.startswith("B"):
        style, folder = "B款脚踏", m.B_VIDEO_DIR
    else:
        return "未知款式 '%s'，请用 A 或 B。" % style_key

    if not folder or not os.path.isdir(folder):
        return "❌ 本地视频目录不存在：%s" % folder
    exts = (".mp4", ".mov", ".m4v", ".avi")
    vids = sorted(os.path.join(folder, f) for f in os.listdir(folder)
                  if f.lower().endswith(exts))
    if not vids:
        return "❌ 目录内无视频文件：%s" % folder

    res = upload_videos(vids)
    return "【%s】本地目录：%s\n%s" % (style, folder, res)


def load_video_map():
    """从 kb.json 读取『款式 → 素材库视频标题』映射（_视频映射）"""
    kb = _kb_file()
    with open(kb, encoding="utf-8") as f:
        data = json.load(f)
    return {k: v for k, v in data.get("_视频映射", {}).items()
            if not k.startswith("_")}


def get_video_titles(style):
    """取某款式对应的素材库视频标题列表"""
    info = load_video_map().get(style) or {}
    titles = info.get("素材库标题") or []
    return titles if isinstance(titles, list) else [titles]


def send_chosen_style(key, with_images=False):
    """
    【命令 chosen】客户选定款式后执行（consult 流程的第二步）。

    ⭐ 默认：只发该款【实拍视频】（从工作台素材库发送）+ 规格话术，**不发图片**。
    with_images=True（CLI 加 --img）：客户明确要图片时，才发实拍图随机 2 张。

    key: 'A' / 'B' / 'A款脚踏' / 'B款脚踏'
    """
    m = _load_style_module()
    k = (key or "").strip().upper()
    if k.startswith("A") or "A款" in (key or ""):
        style = "A款脚踏"
    elif k.startswith("B") or "B款" in (key or ""):
        style = "B款脚踏"
    else:
        return "未知款式 '%s'，请用 A 或 B。" % key

    out = ["【款式】%s" % style]

    # ---- 模式二：客户要图片 → 发实拍图随机2张 ----
    if with_images:
        reply = m.style_chosen_reply(style, media="image")
        imgs = m.pick_style_images(style, 2)
        out.append("【话术】%s" % send_text(reply))
        if imgs:
            out.append("【实拍图 %d 张】\n%s" % (len(imgs), send_images_batch(imgs)))
        else:
            out.append("【实拍图】目录为空或不存在，请检查素材")
        return "\n".join(out)

    # ---- 模式一（默认）：只发视频，不发图片 ----
    titles = get_video_titles(style)
    reply = m.style_chosen_reply(style, media="video")

    if not titles:
        out.append("⚠️ 未配置该款的素材库视频（kb.json 的 _视频映射），已回退为发图片。")
        imgs = m.pick_style_images(style, 2)
        out.append("【话术】%s" % send_text(m.style_chosen_reply(style, media="image")))
        if imgs:
            out.append("【实拍图 %d 张】\n%s" % (len(imgs), send_images_batch(imgs)))
        return "\n".join(out)

    out.append("【话术】%s" % send_text(reply))
    for t in titles:
        out.append("【视频】" + send_video(t))
    out.append("（已按规则只发视频，未发图片；客户要图片时用 chosen %s --img）"
               % ("A" if style == "A款脚踏" else "B"))
    return "\n".join(out)


def cleanup_overlays():
    """清除工作台上遮挡点击的弹层（.layer / 最大 z-index 蒙层）"""
    ws = connect()
    try:
        n = ev(ws, """(function(){var n=0;
document.querySelectorAll('.layer').forEach(function(e){e.remove();n++;});
document.querySelectorAll('div').forEach(function(e){var cs=getComputedStyle(e);if(cs.zIndex==='2147483647'){e.remove();n++;}});
return n;})()""")
        return "cleared %s overlays" % n
    finally:
        ws.close()


def click_picture_icon():
    """点图片图标（打开图片选择面板）"""
    ws = connect()
    try:
        expr = """(function(){
var b=document.querySelector('.chat-icon-picture');
if(!b) return null;
var r=b.getBoundingClientRect();
return {x:Math.round(r.left+r.width/2),y:Math.round(r.top+r.height/2)};})()"""
        return click_el(ws, expr)
    finally:
        ws.close()


def _main():
    cmd = sys.argv[1]
    if cmd == "open":
        print(open_chat(sys.argv[2]))
    elif cmd == "text":
        print(send_text(sys.argv[2]))
    elif cmd == "video":
        occ = int(sys.argv[3]) if len(sys.argv) > 3 else 0
        print(send_video(sys.argv[2], occ))
    elif cmd == "image":
        print(send_image(sys.argv[2:]))
    elif cmd == "images":
        print(send_images_batch(sys.argv[2:]))
    elif cmd == "mix":
        print(send_mix_pair())
    elif cmd == "goods":
        print(json.dumps(get_consult_goods(), ensure_ascii=False, indent=2))
    elif cmd == "consult":
        # consult [--dry]  读取当前会话商品→按类目路由→执行开场动作
        dry = "--dry" in sys.argv[2:]
        print(consult_route(auto_send=not dry))
    elif cmd == "chosen":
        # chosen A|B [--img]  客户选定后：默认只发实拍【视频】；--img 才发实拍图
        args = sys.argv[2:]
        with_img = "--img" in args
        key = next((a for a in args if not a.startswith("--")), "")
        print(send_chosen_style(key, with_images=with_img))
    elif cmd == "goto":
        # goto  进入拼多多客服工作台（接管第一步）
        print(goto_workbench())
    elif cmd == "uploadvideo":
        # uploadvideo <路径...>  上传本地视频到素材库【客服专用视频】
        print(upload_videos(sys.argv[2:]))
    elif cmd == "syncvideo":
        # syncvideo A|B  把该款本地视频目录全部上传到素材库
        print(sync_videos(sys.argv[2] if len(sys.argv) > 2 else ""))
    elif cmd == "clean":
        print(cleanup_overlays())
    elif cmd == "probe":
        print(probe_image_ui())
    elif cmd == "picicon":
        print(click_picture_icon())
    elif cmd == "videos":
        print(list_videos())
    elif cmd == "read":
        print(read_page())
    elif cmd == "shot":
        print(shot(sys.argv[2]))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)
    try:
        _main()
    except (RuntimeError, IndexError) as e:
        print("❌ " + str(e))
        sys.exit(1)
