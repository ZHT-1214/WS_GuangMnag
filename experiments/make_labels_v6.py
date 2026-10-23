# -*- coding: utf-8 -*-
"""生成 E3 标注工具 v6：精简模式。

核心改动（相比 v5）：
  - ①②（可通行方向 + 楼梯）为核心项，展开显示
  - ③④⑤（置信度/障碍物/场景）默认折叠为"进阶标注"，点一下展开
  - 新增"快速模式"：Enter = 确认正确并下一张；数字键直接改方向并自动确认进下一张
  - 这样最快的流程：看一眼 -> 对则 Enter / 错则按数字 -> 自动下一张
"""
import base64
import json
import os
import shutil

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
RESULTS_DIR = os.path.join(_REPO, "data", "results")
LABELS_DIR = os.path.join(_REPO, "data", "labels")
ROUTES_DIR = os.path.join(_REPO, "data", "routes")
FIGS_DIR = os.path.join(_REPO, "figures")


BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(BASE, "_素材", "obstacle_eval")
IMG_DIR = os.path.join(OUT_DIR, "images_e3")

PRED_SOURCES = [
    (os.path.join(OUT_DIR, "yoso_predictions.json"), "", None),
    (os.path.join(OUT_DIR, "indoor_turn_predictions.json"), "indoor_", "室内"),
    (os.path.join(OUT_DIR, "new28_predictions.json"), "new28_", "2-8"),
    (os.path.join(OUT_DIR, "newlr2_predictions.json"), "newlr2_", "左右-2"),
]

ROUTE_DIRS = {
    "1": os.path.join(ROUTES_DIR, "1"),
    "2-2": os.path.join(ROUTES_DIR, "2-2"),
    "1-2": os.path.join(ROUTES_DIR, "1-2"),
    "2-6": os.path.join(ROUTES_DIR, "2-6"),
    "1-3": os.path.join(ROUTES_DIR, "1-3"),
    "2-7": os.path.join(ROUTES_DIR, "2-7"),
    "室内": os.path.join(ROUTES_DIR, "室内"),
    "2-8": os.path.join(ROUTES_DIR, "2-8"),
    "左右-2": os.path.join(ROUTES_DIR, "左右-2"),
}
QUOTA = {"forward": 50, "left": 11, "right": 11, "unknown": 5, "stairs": 10}


def load_predictions():
    merged = {}
    for path, prefix, forced_route in PRED_SOURCES:
        if not os.path.exists(path):
            continue
        d = json.load(open(path, encoding="utf-8"))
        for p in d.get("predictions", []):
            fname = p["file"]
            rest = fname[len(prefix):] if prefix and fname.startswith(prefix) else fname
            if forced_route is not None:
                route, orig = forced_route, rest
            else:
                route, orig = rest.rsplit("_", 1) if "_" in rest else ("unknown", rest)
            merged[f"{route}/{orig}"] = {
                "route": route, "orig": orig,
                "pred": p.get("pred_passable"), "stairs": p.get("pred_stairs"),
            }
    return merged


def balanced_select(buckets):
    selected = []
    for cat, n in QUOTA.items():
        pool = buckets.get(cat, [])
        by_route = {}
        for it in pool:
            by_route.setdefault(it["route"], []).append(it)
        routes = sorted(by_route.keys())
        picked, idx = [], 0
        while len(picked) < min(n, len(pool)):
            added = False
            for r in routes:
                if idx < len(by_route[r]) and len(picked) < n:
                    picked.append(by_route[r][idx]); added = True
            if not added: break
            idx += 1
        selected.extend(picked)
    return selected


def main():
    os.makedirs(IMG_DIR, exist_ok=True)
    preds = load_predictions()
    buckets = {"forward": [], "left": [], "right": [], "unknown": [], "stairs": []}
    for key, p in preds.items():
        route = p["route"]
        if route not in ROUTE_DIRS: continue
        src = os.path.join(ROUTE_DIRS[route], p["orig"])
        if not os.path.exists(src): continue
        item = {"key": key, "route": route, "orig": p["orig"], "src": src,
                "pred": p["pred"], "pred_stairs": p["stairs"]}
        if p["stairs"]: buckets["stairs"].append(item)
        elif p["pred"] in ("forward","left","right"): buckets[p["pred"]].append(item)
        else: buckets["unknown"].append(item)

    selected = balanced_select(buckets)

    labels = []
    for i, it in enumerate(selected):
        ext = os.path.splitext(it["orig"])[1] or ".jpg"
        newname = f"e3_{i:03d}{ext}"
        dst = os.path.join(IMG_DIR, newname)
        shutil.copy2(it["src"], dst)
        labels.append({
            "file": newname, "route": it["route"],
            "orig_index": int(os.path.splitext(it["orig"])[0]) if os.path.splitext(it["orig"])[0].isdigit() else 0,
            "yoso_passable": it["pred"] if it["pred"] in ("forward","left","right","unknown") else "unknown",
            "yoso_stairs": bool(it["pred_stairs"]),
            "passable": it["pred"] if it["pred"] in ("forward","left","right") else "unknown",
            "stairs": bool(it["pred_stairs"]),
            "conf": "", "obstacles": [], "scene": "", "note": "",
            "verified": False, "changed": False,
        })

    images_b64 = {}
    for it in labels:
        with open(os.path.join(IMG_DIR, it["file"]), "rb") as f:
            images_b64[it["file"]] = base64.b64encode(f.read()).decode()

    data_json = json.dumps({"labels": labels, "images": images_b64}, ensure_ascii=False)
    html = TEMPLATE.replace("__DATA__", data_json)

    # 自动检查：getElementById 引用的静态 id 是否都存在
    import re as _re
    ids_in_html = set(_re.findall(r'id="([^"]+)"', html))
    static_refs = set(_re.findall(
        r"getElementById\(\s*['\"]([a-zA-Z_][a-zA-Z0-9_]*)['\"]\s*\)", html))
    missing = static_refs - ids_in_html
    if missing:
        raise SystemExit(f"HTML 缺少以下 id（会导致 null 错误）: {missing}")

    out = os.path.join(OUT_DIR, "label_tool_v6.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"共 {len(labels)} 张 -> {out} ({os.path.getsize(out)/1024/1024:.1f} MB)")
    print(f"id 检查通过（{len(static_refs)} 个静态引用全部存在）")


TEMPLATE = r"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>E3 校正工具 v6</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%;overflow:hidden;font-family:"Microsoft YaHei",sans-serif;background:#1a1a1a;color:#ddd}
#top{height:50px;background:#111;display:flex;align-items:center;gap:12px;padding:0 14px;border-bottom:1px solid #333;flex-wrap:wrap}
#top b{color:#fff;font-size:14px}
#top .sp{flex:1}
button{padding:6px 12px;cursor:pointer;border:1px solid #666;border-radius:4px;background:#2a2a2a;color:#ddd;font-size:13px}
button:hover{background:#3a3a3a}
button.sel{background:#2b7a4b;border-color:#2b7a4b;color:#fff;font-weight:bold}
button.chg{background:#8a5a1a;border-color:#c90;color:#fff}
button.ok{background:#1a6a3a;border-color:#2b7a4b;color:#fff;font-size:15px;padding:9px 24px;font-weight:bold}
#body{display:flex;height:calc(100% - 50px)}
#left{width:170px;overflow-y:auto;background:#202020;border-right:1px solid #333;flex-shrink:0}
#left .it{padding:4px 8px;font-size:11px;cursor:pointer;border-left:3px solid transparent;display:flex;justify-content:space-between}
#left .it:hover{background:#2a2a2a}
#left .it.cur{background:#2b7a4b;border-left-color:#5fd;color:#fff}
#left .it.ver{color:#6c9}
#left .it.chg{color:#f9c74f}
#center{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:10px;overflow:hidden;min-width:0}
#imgbox{flex:1;display:flex;align-items:center;justify-content:center;width:100%;overflow:hidden}
#img{max-width:100%;max-height:100%;object-fit:contain;border-radius:6px;box-shadow:0 4px 20px rgba(0,0,0,.6)}
#imgmeta{margin-top:6px;font-size:12px;color:#999}
#navrow{margin-top:8px;display:flex;gap:8px}
#right{width:330px;overflow-y:auto;background:#222;border-left:1px solid #333;padding:12px;flex-shrink:0}
.yoso{background:#1a3a2a;border:1px solid #2b7a4b;border-radius:6px;padding:9px 12px;font-size:13px;line-height:1.7;margin-bottom:12px}
.yoso b{color:#7dcf9f;font-size:14px}
.q{color:#8ecae6;font-size:12.5px;margin:10px 0 5px;font-weight:bold}
.opts{display:flex;flex-wrap:wrap;gap:5px}
.opts button{padding:6px 11px;font-size:12.5px}
#adv{display:none;background:#1a1a2a;border:1px solid #444;border-radius:6px;padding:10px;margin-top:12px}
#adv .q{margin-top:8px}
.hint{color:#888;font-size:11px;margin-top:6px;line-height:1.5}
#note{width:100%;background:#111;color:#ddd;border:1px solid #444;padding:5px;border-radius:4px;font-size:12.5px}
#exportArea{width:100%;height:60px;background:#111;color:#6c9;border:1px solid #444;font-family:monospace;font-size:10px;padding:5px;display:none;margin-top:8px}
.mode{font-size:12px;color:#888;margin-top:8px}
</style></head><body>

<div id="top">
  <b>核对 <span id="nVer">0</span>/<span id="nTot">0</span></b>
  <span style="color:#f9c74f;font-size:13px">修改 <span id="nChg">0</span></span>
  <span id="curName" style="color:#8ecae6;font-size:13px">-</span>
  <span class="sp"></span>
  <button onclick="toggleMode()" id="modeBtn">只看未核对</button>
  <button onclick="exportJSON()">导出 JSON</button>
  <button onclick="copyJSON()">复制</button>
</div>

<div id="body">
  <div id="left"></div>
  <div id="center">
    <div id="imgbox"><img id="img" src="" alt=""></div>
    <div id="imgmeta"></div>
    <div id="navrow">
      <button onclick="go(CUR-1)">← 上一张</button>
      <button class="ok" onclick="markCorrect()">✓ 正确（Enter）</button>
      <button onclick="go(CUR+1)">跳过 →</button>
    </div>
  </div>
  <div id="right">
    <div class="yoso">
      YOSO 预测：<b id="yosoDir">-</b><br>
      楼梯：<b id="yosoSt">-</b>
    </div>

    <div class="q">① 可通行方向（点 = 改，改完自动进下一张）</div>
    <div class="opts" id="oDir"></div>
    <div class="q">② 楼梯</div>
    <div class="opts" id="oStairs"></div>

    <div class="mode" style="margin-top:14px">
      最快用法：看图 → 对则 <b style="color:#6c9">Enter</b> / 错则点方向按钮（自动进下一张）
    </div>

    <button onclick="document.getElementById('adv').style.display =
      document.getElementById('adv').style.display==='none'?'block':'none'"
      style="margin-top:14px;width:100%">
      ▶ 进阶标注（置信度 / 障碍物 / 场景，可选）
    </button>
    <div id="adv">
      <div class="q">置信度</div><div class="opts" id="oConf"></div>
      <div class="q">障碍物（多选）</div><div class="opts" id="oObs"></div>
      <div class="q">场景</div><div class="opts" id="oScene"></div>
      <div class="q">备注</div><input type="text" id="note" placeholder="可选">
    </div>
    <textarea id="exportArea" readonly></textarea>
  </div>
</div>

<script>
const DATA = __DATA__;
const LABELS = DATA.labels;
const IMAGES = DATA.images;
let STATE = {}, CUR = 0, onlyUnverified = false, autoNext = true;

const DIRS = [["left","左"],["ahead","前"],["right","右"],["none","无路"],["unknown","不确定"]];
const CONFS = [["high","高"],["medium","中"],["low","低"]];
const STAIRS = [[true,"有"],[false,"无"]];
const OBSTACLES = ["person 人","furniture 桌椅","wall 墙柱","door 门","plant 绿植","box 纸箱","stairs 楼梯","other 其他"];
const SCENES = [["corridor","走廊"],["room","房间"],["hall","大厅"],["doorway","门口"],["outdoor","室外"],["other","其他"]];

function st(it){
  if(!STATE[it.file]) STATE[it.file] = {
    passable: it.passable, stairs: it.stairs, conf:"", obstacles:[], scene:"",
    note:"", verified:false, changed:false };
  return STATE[it.file];
}
function curList(){ return onlyUnverified ? LABELS.filter(x=>!st(x).verified) : LABELS; }

function init(){
  document.getElementById('nTot').textContent = LABELS.length;
  try{ const sv = localStorage.getItem('e3_v6'); if(sv) STATE = JSON.parse(sv); }catch(e){}
  const left = document.getElementById('left');
  LABELS.forEach((it,i)=>{
    const d = document.createElement('div'); d.className='it'; d.id='li_'+i;
    d.innerHTML = `<span>${it.file}</span>`;
    d.onclick = ()=>go(i);
    left.appendChild(d);
  });
  buildOptions(); go(0);
}

function buildOptions(){
  const mk = (cid, items, onPick)=>{
    items.forEach(([v,label])=>{
      const b = document.createElement('button');
      b.textContent = label; b.dataset.val = String(v);
      b.onclick = ()=>{ onPick(v); refresh(); if(autoNext) nextUnverified(); };
      document.getElementById(cid).appendChild(b);
    });
  };
  mk('oDir', DIRS, v=>{
    const s=st(LABELS[CUR]);
    if(s.passable!==v){ s.passable=v; s.changed=(v!==LABELS[CUR].yoso_passable); s.verified=true; }
  });
  mk('oStairs', STAIRS, v=>{
    const s=st(LABELS[CUR]);
    if(s.stairs!==v){ s.stairs=v; s.changed=(v!==LABELS[CUR].yoso_stairs); s.verified=true; }
  });
  mk('oConf', CONFS, v=>{ const s=st(LABELS[CUR]); s.conf=(s.conf===v?'':v); });
  mk('oObs', OBSTACLES.map(o=>[o.split(' ')[0], o]), v=>{
    const s=st(LABELS[CUR]);
    const i=s.obstacles.indexOf(v);
    if(i>=0) s.obstacles.splice(i,1); else s.obstacles.push(v);
  });
  mk('oScene', SCENES, v=>{ const s=st(LABELS[CUR]); s.scene=(s.scene===v?'':v); });
  document.getElementById('note').oninput = function(){
    st(LABELS[CUR]).note = this.value; save();
  };
}

function nextUnverified(){
  const l = LABELS;
  for(let k=1;k<=l.length;k++){
    const idx = (CUR+k) % l.length;
    if(!st(l[idx]).verified){ go(idx); return; }
  }
  go((CUR+1)%l.length);
}

function go(i){
  const list = curList();
  if(!list.length) return;
  i = Math.max(0, Math.min(i, list.length-1));
  CUR = LABELS.indexOf(list[i]);
  const it = LABELS[CUR]; const s = st(it);
  document.getElementById('curName').textContent = it.file + (s.verified?' ✓':' (待核对)');
  document.getElementById('img').src = 'data:image/jpeg;base64,' + IMAGES[it.file];
  document.getElementById('imgmeta').textContent =
    `${list.indexOf(it)+1} / ${list.length}（总 ${LABELS.length}）· ${it.route} · 帧 ${it.orig_index}`;
  document.getElementById('yosoDir').textContent = it.yoso_passable;
  document.getElementById('yosoSt').textContent = it.yoso_stairs ? '有' : '无';
  document.getElementById('note').value = s.note||'';
  refresh();
  const el = document.getElementById('li_'+CUR);
  if(el) el.scrollIntoView({block:'nearest'});
}

function refresh(){
  const it = LABELS[CUR]; const s = st(it);
  document.querySelectorAll('#oDir button').forEach(b=>{
    b.classList.toggle('sel', s.passable===b.dataset.val);
    b.classList.toggle('chg', s.passable===b.dataset.val && s.passable!==it.yoso_passable);
  });
  document.querySelectorAll('#oStairs button').forEach(b=>{
    const sel = s.stairs===JSON.parse(b.dataset.val);
    b.classList.toggle('sel', sel);
    b.classList.toggle('chg', sel && s.stairs!==it.yoso_stairs);
  });
  document.querySelectorAll('#oConf button').forEach(b=>{
    b.classList.toggle('sel', s.conf===b.dataset.val);
  });
  document.querySelectorAll('#oObs button').forEach(b=>{
    b.classList.toggle('sel', (s.obstacles||[]).includes(b.dataset.val));
  });
  document.querySelectorAll('#oScene button').forEach(b=>{
    b.classList.toggle('sel', s.scene===b.dataset.val);
  });
  let nv=0, nc=0;
  LABELS.forEach((x,i)=>{
    const ss = STATE[x.file];
    const isv = ss && ss.verified;
    if(isv) nv++;
    if(ss && ss.changed) nc++;
    const el = document.getElementById('li_'+i);
    if(el){
      el.classList.toggle('ver', !!isv);
      el.classList.toggle('chg', !!(ss && ss.changed));
      el.classList.toggle('cur', i===CUR);
    }
  });
  document.getElementById('nVer').textContent = nv;
  document.getElementById('nChg').textContent = nc;
  save();
}
function save(){ try{ localStorage.setItem('e3_v6', JSON.stringify(STATE)); }catch(e){} }

function markCorrect(){
  const s = st(LABELS[CUR]);
  s.verified = true;
  refresh();
  nextUnverified();
}
function toggleMode(){
  onlyUnverified = !onlyUnverified;
  document.getElementById('modeBtn').textContent =
    onlyUnverified ? '显示全部' : '只看未核对';
  go(0);
}
function buildResult(){
  return {
    meta:{generated:new Date().toISOString(), total:LABELS.length,
          verified:LABELS.filter(x=>st(x).verified).length,
          changed:LABELS.filter(x=>st(x).changed).length,
          task:"traversability_direction"},
    labels: LABELS.map(it=>{
      const s = st(it);
      return {...it, passable:s.passable||'', stairs:s.stairs,
              conf:s.conf||'', obstacles:s.obstacles||[], scene:s.scene||'',
              note:s.note||'', verified:!!s.verified, changed:!!s.changed};
    })
  };
}
function exportJSON(){
  const b = buildResult();
  const ta = document.getElementById('exportArea');
  ta.style.display='block'; ta.value = JSON.stringify(b,null,2); ta.select();
  alert(`核对 ${b.meta.verified}/${b.meta.total}，修改 ${b.meta.changed} 张。\nCtrl+C 复制，保存为 labels_filled.json`);
}
function copyJSON(){
  const b = buildResult();
  navigator.clipboard.writeText(JSON.stringify(b,null,2))
    .then(()=>alert(`已复制（${b.meta.verified}/${b.meta.total}）`))
    .catch(()=>exportJSON());
}
document.addEventListener('keydown', e=>{
  if(e.target.tagName==='INPUT'||e.target.tagName==='TEXTAREA') return;
  const s = st(LABELS[CUR]); const it = LABELS[CUR]; const k = e.key;
  if(k==='1'){ s.passable='left'; s.changed=(s.passable!==it.yoso_passable); s.verified=true; refresh(); nextUnverified(); }
  else if(k==='2'){ s.passable='ahead'; s.changed=(s.passable!==it.yoso_passable); s.verified=true; refresh(); nextUnverified(); }
  else if(k==='3'){ s.passable='right'; s.changed=(s.passable!==it.yoso_passable); s.verified=true; refresh(); nextUnverified(); }
  else if(k==='4'){ s.passable='none'; s.changed=(s.passable!==it.yoso_passable); s.verified=true; refresh(); nextUnverified(); }
  else if(k==='5'){ s.passable='unknown'; s.changed=(s.passable!==it.yoso_passable); s.verified=true; refresh(); nextUnverified(); }
  else if(k==='s'||k==='S'){ s.stairs=!s.stairs; s.changed=(s.stairs!==it.yoso_stairs); s.verified=true; refresh(); nextUnverified(); }
  else if(k==='Enter'){ markCorrect(); }
  else if(k==='ArrowRight'){ const l=curList(); const i=l.indexOf(it); if(i<l.length-1) go(i+1); }
  else if(k==='ArrowLeft'){ const l=curList(); const i=l.indexOf(it); if(i>0) go(i-1); }
});
init();
</script></body></html>"""


if __name__ == "__main__":
    main()
