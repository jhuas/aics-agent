# -*- coding: utf-8 -*-
"""诊断：查看当前拼多多商家后台页面有哪些表格、表头列名是什么，定位列匹配失败原因。"""
import json, urllib.request, websocket

DEBUGGER = "http://127.0.0.1:9222"

def pages():
    with urllib.request.urlopen(DEBUGGER + "/json/list", timeout=8) as r:
        return [t for t in json.load(r) if t.get("type") == "page"]

_id=[0]
def send(ws, method, params=None):
    _id[0]+=1; mid=_id[0]
    ws.send(json.dumps({"id":mid,"method":method,"params":params or{}}))
    while True:
        m=json.loads(ws.recv())
        if m.get("id")==mid: return m

def ev(ws, expr):
    r=send(ws,"Runtime.evaluate",{"expression":expr,"returnByValue":True,"awaitPromise":True})
    res=r.get("result",{})
    if res.get("exceptionDetails"): return "EXC:"+json.dumps(res["exceptionDetails"],ensure_ascii=False)[:300]
    return res.get("result",{}).get("value")

def main():
    print("== pages ==")
    for t in pages():
        print("  title=%s | url=%s" % (t.get("title"), t.get("url")))
    mms=[t for t in pages() if "mms.pinduoduo.com" in (t.get("url") or "")]
    if not mms:
        print("!! no mms page"); return
    t=mms[0]
    print("\n== using page: %s ==" % t.get("url"))
    ws=websocket.create_connection(t["webSocketDebuggerUrl"],timeout=40,suppress_origin=True)
    try:
        # 页面内所有表格：位置、表头
        js=r"""(function(){
var out=[];
var tables=document.querySelectorAll('table');
for(var i=0;i<tables.length;i++){
  var t=tables[i],trs=t.querySelectorAll('tr');
  if(!trs.length) continue;
  var ths=trs[0].querySelectorAll('th');
  var cells=ths.length?ths:trs[0].querySelectorAll('td');
  var hd=[];
  for(var j=0;j<cells.length;j++) hd.push((cells[j].innerText||'').trim());
  out.push({table:i, headers:hd, rows:trs.length-1});
}
// 也收集含「商品」关键字的文本区块
var texts=[];
document.querySelectorAll('div,span,th,td').forEach(function(e){
  if(e.children.length===0){ var tx=(e.innerText||'').trim(); if(tx && tx.length<20) texts.push(tx); }
});
return JSON.stringify({tables:out, sampleTexts:texts.slice(0,80)});})()"""
        r=json.loads(ev(ws,js) or "{}")
        print("\n== tables ==")
        for tb in r.get("tables",[]):
            print("  table#%d rows=%d headers=%s" % (tb["table"],tb["rows"],[h for h in tb["headers"]]))
        print("\n== sample short texts ==")
        print(r.get("sampleTexts"))
        # 页面位置标题
        print("\n== current tab label ==")
        print(ev(ws, "document.title + ' | ' + location.href"))
    finally:
        ws.close()

if __name__=="__main__":
    main()