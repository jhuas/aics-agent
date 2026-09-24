# -*- coding: utf-8 -*-
"""诊断：查看 商品数据 / 交易数据 页面表格表头列名。"""
import json, urllib.request, websocket

DEBUGGER="http://127.0.0.1:9222"
def pages():
    with urllib.request.urlopen(DEBUGGER+"/json/list",timeout=8) as r:
        return [t for t in json.load(r) if t.get("type")=="page"]
_id=[0]
def send(ws,m,p=None):
    _id[0]+=1;mid=_id[0];ws.send(json.dumps({"id":mid,"method":m,"params":p or{}}))
    while True:
        x=json.loads(ws.recv())
        if x.get("id")==mid:return x
def ev(ws,x):
    r=send(ws,"Runtime.evaluate",{"expression":x,"returnByValue":True,"awaitPromise":True})
    res=r.get("result",{})
    if res.get("exceptionDetails"):return "EXC:"+json.dumps(res["exceptionDetails"],ensure_ascii=False)[:200]
    return res.get("result",{}).get("value")
def main():
    for t in pages():
        u=t.get("url") or ""
        if not ("goods_effect" in u or "stores_data" in u): continue
        print("\n############ %s | %s" % (t.get("title"),u))
        ws=websocket.create_connection(t["webSocketDebuggerUrl"],timeout=40,suppress_origin=True)
        try:
            js=r"""(function(){
var out=[];
document.querySelectorAll('table').forEach(function(tb,i){
  var trs=tb.querySelectorAll('tr'); if(!trs.length)return;
  var ths=trs[0].querySelectorAll('th');
  var cells=ths.length?ths:trs[0].querySelectorAll('td');
  var hd=[]; for(var j=0;j<cells.length;j++)hd.push((cells[j].innerText||'').trim());
  out.push({table:i,headers:hd,rows:trs.length-1});
});
return JSON.stringify(out);})()"""
            tabs=json.loads(ev(ws,js) or "[]")
            if not tabs: print("  (无 table 标签，尝试 div 表格)")
            for tb in tabs:
                print("  table#%d rows=%d" % (tb["table"],tb["rows"]))
                print("    headers: %s" % (tb["headers"]))
            # 页面主文本（截断）
            b=ev(ws,"document.body.innerText.replace(/\\s+/g,' ').slice(0,800)")
            print("  body:", (b or '')[:500])
        finally:
            ws.close()
if __name__=="__main__":
    main()