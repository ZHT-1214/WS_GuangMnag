# -*- coding: utf-8 -*-
"""生成 E3 标注工具 v5：YOSO 预填 + 人工校正。

核心设计：
  - 每个样本的选项已按 YOSO 预测预选好（绿色高亮）
  - 你只需：正确的点「✓ 正确」跳过，错误的改选后自动进下一张
  - 顶部显示「已核对 / 总数」与「已修改数」
  - 支持"只看未核对"模式
  - 导出时带上 yoso_pred 字段，便于分析模型错误

数据集构成（类别平衡）：
  forward 50 + left 11 + right 11 + unknown 5 + stairs 6 = 83 张
  其中 stairs 样本从左右-2 抽取，其余从全部路线均衡抽取
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

# 各路线 YOSO 预测结果文件（合并使用）
# 格式：(文件路径, 文件名前缀, 对应的路线目录名)
PRED_SOURCES = [
    # 旧 6 条路线：文件名形如 "1-2_0.jpg"，前缀为空，路线名从文件名解析
    (os.path.join(OUT_DIR, "yoso_predictions.json"), "", None),
    # 室内转弯：文件名 "indoor_0.jpg" -> 路线 "室内"
    (os.path.join(OUT_DIR, "indoor_turn_predictions.json"), "indoor_", "室内"),
    # 2-8：文件名 "new28_0.jpg" -> 路线 "2-8"
    (os.path.join(OUT_DIR, "new28_predictions.json"), "new28_", "2-8"),
    # 左右-2：文件名 "newlr2_0.jpg" -> 路线 "左右-2"
    (os.path.join(OUT_DIR, "newlr2_predictions.json"), "newlr2_", "左右-2"),
]

# 路线 -> 本地目录
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

# 配额
QUOTA = {"forward": 50, "left": 11, "right": 11, "unknown": 5, "stairs": 10}


def load_predictions():
    """合并所有 YOSO 预测，返回 {key: {route, orig, pred, stairs}}"""
    merged = {}
    for path, prefix, forced_route in PRED_SOURCES:
        if not os.path.exists(path):
            print(f"  [跳过] {path}")
            continue
        d = json.load(open(path, encoding="utf-8"))
        n_added = 0
        for p in d.get("predictions", []):
            fname = p["file"]
            # 去掉前缀
            if prefix and fname.startswith(prefix):
                rest = fname[len(prefix):]
            else:
                rest = fname

            if forced_route is not None:
                route = forced_route
                orig = rest
            else:
                # 旧路线：文件名形如 "1-2_0.jpg" 或 "1_0.jpg"
                # 用最后一个下划线分割（路线名本身可能不含下划线）
                if "_" in rest:
                    route, orig = rest.rsplit("_", 1)
                else:
                    route, orig = "unknown", rest

            key = f"{route}/{orig}"
            merged[key] = {
                "route": route,
                "orig": orig,
                "pred": p.get("pred_passable"),
                "stairs": p.get("pred_stairs"),
            }
            n_added += 1
        print(f"  {os.path.basename(path)}: {n_added} 条 (route={forced_route or 'auto'})")
    return merged


def main():
    os.makedirs(IMG_DIR, exist_ok=True)
    preds = load_predictions()
    print(f"合并预测: {len(preds)} 条")

    # 按类别分组
    buckets = {"forward": [], "left": [], "right": [], "unknown": [], "stairs": []}
    for key, p in preds.items():
        route = p["route"]
        if route not in ROUTE_DIRS:
            continue
        src = os.path.join(ROUTE_DIRS[route], p["orig"])
        if not os.path.exists(src):
            continue
        item = {"key": key, "route": route, "orig": p["orig"],
                "src": src, "pred": p["pred"], "pred_stairs": p["stairs"]}
        if p["stairs"]:
            buckets["stairs"].append(item)
        elif p["pred"] in ("forward", "left", "right"):
            buckets[p["pred"]].append(item)
        else:
            buckets["unknown"].append(item)

    print("\n可用样本池:")
    for k, v in buckets.items():
        print(f"  {k:9s}: {len(v)}")

    # 抽取：每个类别内按路线轮询，保证路线多样性
    selected = []
    for cat, n in QUOTA.items():
        pool = buckets.get(cat, [])
        # 按路线分组
        by_route = {}
        for it in pool:
            by_route.setdefault(it["route"], []).append(it)
        # 轮询抽取
        routes = sorted(by_route.keys())
        picked = []
        idx = 0
        while len(picked) < min(n, len(pool)):
            added = False
            for r in routes:
                if idx < len(by_route[r]) and len(picked) < n:
                    picked.append(by_route[r][idx])
                    added = True
            if not added:
                break
            idx += 1
        print(f"  抽 {cat:9s}: {len(picked)}/{n}  路线分布={dict(__import__('collections').Counter(x['route'] for x in picked))}")
        selected.extend(picked)

    # 复制图片并构建 labels
    labels = []
    for i, it in enumerate(selected):
        ext = os.path.splitext(it["orig"])[1] or ".jpg"
        newname = f"e3_{i:03d}{ext}"
        dst = os.path.join(IMG_DIR, newname)
        shutil.copy2(it["src"], dst)
        labels.append({
            "file": newname,
            "route": it["route"],
            "orig_index": int(os.path.splitext(it["orig"])[0]) if os.path.splitext(it["orig"])[0].isdigit() else 0,
            # YOSO 预填（作为初始值，供人工校正）
            "yoso_passable": it["pred"] if it["pred"] in ("forward","left","right","unknown") else "unknown",
            "yoso_stairs": bool(it["pred_stairs"]),
            # 最终标注（初始等于 YOSO 预测，人工可改）
            "passable": it["pred"] if it["pred"] in ("forward","left","right") else "unknown",
            "stairs": bool(it["pred_stairs"]),
            "conf": "",
            "obstacles": [],
            "scene": "",
            "note": "",
            "verified": False,
            "changed": False,
        })

    images_b64 = {}
    for it in labels:
        with open(os.path.join(IMG_DIR, it["file"]), "rb") as f:
            images_b64[it["file"]] = base64.b64encode(f.read()).decode()

    data_json = json.dumps({"labels": labels, "images": images_b64}, ensure_ascii=False)
    html = TEMPLATE.replace("__DATA__", data_json)
    out = os.path.join(OUT_DIR, "label_tool_v5.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n共 {len(labels)} 张，已预填 YOSO 预测")
    print(f"工具: {out}")
    print(f"大小: {os.path.getsize(out)/1024/1024:.1f} MB")


TEMPLATE = r"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>E3 标注（YOSO 预填 + 人工校正）</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%;overflow:hidden;font-family:"Microsoft YaHei",sans-serif;background:#1a1a1a;color:#ddd}
#top{height:50px;background:#111;display:flex;align-items:center;gap:14px;padding:0 16px;border-bottom:1px solid #333}
#top b{color:#fff;font-size:14px}
#top .sp{flex:1}
button{padding:6px 13px;cursor:pointer;border:1px solid #666;border-radius:4px;background:#2a2a2a;color:#ddd;font-size:13px}
button:hover{background:#3a3a3a}
button.sel{background:#2b7a4b;border-color:#2b7a4b;color:#fff;font-weight:bold}
button.chg{background:#8a5a1a;border-color:#c90;color:#fff}
button.ok{background:#1a6a3a;border-color:#2b7a4b;color:#fff;font-size:15px;padding:9px 22px;font-weight:bold}
#body{display:flex;height:calc(100% - 50px)}
#left{width:180px;overflow-y:auto;background:#202020;border-right:1px solid #333;flex-shrink:0}
#left .it{padding:4px 9px;font-size:11px;cursor:pointer;border-left:3px solid transparent;display:flex;justify-content:space-between}
#left .it:hover{background:#2a2a2a}
#left .it.cur{background:#2b7a4b;border-left-color:#5fd;color:#fff}
#left .it.ver{color:#6c9}
#left .it.chg{color:#f9c74f}
#center{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:10px;overflow:hidden;min-width:0}
#imgbox{flex:1;display:flex;align-items:center;justify-content:center;width:100%;overflow:hidden}
#img{max-width:100%;max-height:100%;object-fit:contain;border-radius:6px;box-shadow:0 4px 20px rgba(0,0,0,.6)}
#imgmeta{margin-top:6px;font-size:12px;color:#999;text-align:center}
#navrow{margin-top:8px;display:flex;gap:8px;align-items:center}
#right{width:330px;overflow-y:auto;background:#222;border-left:1px solid #333;padding:12px;flex-shrink:0}
.q{color:#8ecae6;font-size:12.5px;margin:11px 0 5px;font-weight:bold}
.q:first-child{margin-top:0}
.opts{display:flex;flex-wrap:wrap;gap:5px}
.opts button{padding:5px 10px;font-size:12.5px}
.yoso{background:#1a3a2a;border:1px solid #2b7a4b;border-radius:6px;padding:9px;margin-bottom:10px;font-size:12.5px;line-height:1.6}
.yoso b{color:#7dcf9f}
.hint{color:#888;font-size:11px;margin-top:4px;line-height:1.5}
#note{width:100%;background:#111;color:#ddd;border:1px solid #444;padding:5px;border-radius:4px;font-size:12.5px}
#exportArea{width:100%;height:60px;background:#111;color:#6c9;border:1px solid #444;font-family:monospace;font-size:10px;padding:5px;display:none;margin-top:8px}
</style></head><body>

<div id="top">
  <b>已核对 <span id="nVer">0</span>/<span id="nTot">0</span></b>
  <span style="color:#f9c74f;font-size:13px">已修改 <span id="nChg">0</span></span>
  <span id="curName" style="color:#8ecae6;font-size:12px">-</span>
  <span class="sp"></span>
  <button onclick="onlyUnverified=!onlyUnverified;go(CUR);this.textContent=onlyUnverified?'显示全部':'只看未核对'">
    <span id="modeBtn">显示全部</span></button>
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
      <button class="ok" onclick="markCorrect()">✓ YOSO 正确，下一张</button>
      <button onclick="go(CUR+1)">下一张 →</button>
    </div>
  </div>
  <div id="right">
    <div class="yoso">
      <b>YOSO 预测：</b><span id="yosoDir">-</span><br>
      <b>楼梯：</b><span id="yosoSt">-</span><br>
      <span class="hint">若预测正确，直接点下方「✓ YOSO 正确」；错误则改选后自动进下一张。</span>
    </div>

    <div class="q">① 可通行方向</div>
    <div class="opts" id="oDir"></div>
    <div class="q">② 是否有楼梯</div>
    <div class="opts" id="oStairs"></div>
    <div class="q">③ 置信度</div>
    <div class="opts" id="oConf"></div>
    <div class="q">④ 障碍物（多选）</div>
    <div class="opts" id="oObs"></div>
    <div class="q">⑤ 场景</div>
    <div class="opts" id="oScene"></div>
    <div class="q">⑥ 备注</div>
    <input type="text" id="note" placeholder="可选">
    <div class="hint" style="margin-top:10px">
      快捷键：<b>1</b>左 <b>2</b>前 <b>3</b>右 <b>4</b>无路 <b>5</b>不确定
      <b>S</b>切楼梯 <b>Enter</b>确认正确 <b>←→</b>翻页
    </div>
    <textarea id="exportArea" readonly></textarea>
  </div>
</div>

<script>
const DATA = __DATA__;
const LABELS = DATA.labels;
const IMAGES = DATA.images;
let STATE = {};
let CUR = 0;
let onlyUnverified = false;

const DIRS = [["left","左"],["ahead","前"],["right","右"],["none","无路"],["unknown","不确定"]];
const CONFS = [["high","高"],["medium","中"],["low","低"]];
const STAIRS = [[true,"有"],[false,"无"]];
const OBSTACLES = ["person 人","furniture 桌椅","wall 墙柱","door 门","plant 绿植","box 纸箱","stairs 楼梯","other 其他"];
const SCENES = [["corridor","走廊"],["room","房间"],["hall","大厅"],["doorway","门口"],["outdoor","室外"],["other","其他"]];

function st(it){
  if(!STATE[it.file]) STATE[it.file] = {
    passable: it.passable, stairs: it.stairs, conf: "", obstacles: [], scene: "",
    note: "", verified: false, changed: false
  };
  return STATE[it.file];
}
function curList(){
  return onlyUnverified ? LABELS.filter(it=>!st(it).verified) : LABELS;
}
function init(){
  document.getElementById('nTot').textContent = LABELS.length;
  try{ const sv = localStorage.getItem('e3_v5'); if(sv) STATE = JSON.parse(sv); }catch(e){}
  const left = document.getElementById('left');
  LABELS.forEach((it,i)=>{
    const d = document.createElement('div');
    d.className='it'; d.id='li_'+i;
    d.innerHTML = `<span>${it.file}</span>`;
    d.onclick = ()=>go(i);
    left.appendChild(d);
  });
  buildOptions();
  go(0);
}

function buildOptions(){
  const mk = (container, items, onPick)=>{
    const box = document.getElementById(container);
    items.forEach(([v,label])=>{
      const b = document.createElement('button');
      b.textContent = label; b.dataset.val = String(v);
      b.onclick = ()=>{ onPick(v); refresh(); };
      box.appendChild(b);
    });
  };
  mk('oDir', DIRS, v=>{
    const s = st(LABELS[CUR]);
    s.passable = v;
    s.changed = (v !== LABELS[CUR].yoso_passable);
    if(!s.verified){ /* 未确认，等用户点确认 */ }
  });
  mk('oStairs', STAIRS, v=>{
    const s = st(LABELS[CUR]);
    s.stairs = v;
    s.changed = (v !== LABELS[CUR].yoso_stairs);
  });
  mk('oConf', CONFS, v=>{ const s=st(LABELS[CUR]); s.conf = (s.conf===v?'':v); });
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

function go(i){
  const list = curList();
  if(list.length===0) return;
  if(i<0) i=0;
  if(i>=list.length) i=list.length-1;
  // 找到在完整列表中的索引
  const target = list[i];
  CUR = LABELS.indexOf(target);
  const it = LABELS[CUR];
  const s = st(it);
  document.getElementById('curName').textContent = it.file + (s.verified?' ✓':'');
  document.getElementById('img').src = 'data:image/jpeg;base64,' + IMAGES[it.file];
  document.getElementById('imgmeta').textContent =
    `${list.indexOf(it)+1} / ${list.length}（总 ${LABELS.length}） · 路线 ${it.route} · 原始帧 ${it.orig_index}`;
  document.getElementById('yosoDir').textContent = it.yoso_passable;
  document.getElementById('yosoSt').textContent = it.yoso_stairs ? '有' : '无';
  document.getElementById('note').value = s.note || '';
  refresh();
  const el = document.getElementById('li_'+CUR);
  if(el) el.scrollIntoView({block:'nearest'});
}

function refresh(){
  const it = LABELS[CUR]; const s = st(it);
  document.querySelectorAll('#oDir button').forEach(b=>{
    b.classList.toggle('sel', s.passable === b.dataset.val);
    b.classList.toggle('chg', s.passable === b.dataset.val && s.passable !== it.yoso_passable);
  });
  document.querySelectorAll('#oStairs button').forEach(b=>{
    const sel = (s.stairs!==null && s.stairs!==undefined) && (String(s.stairs)===b.dataset.val);
    b.classList.toggle('sel', sel);
    b.classList.toggle('chg', sel && s.stairs !== it.yoso_stairs);
  });
  document.querySelectorAll('#oConf button').forEach(b=>{
    b.classList.toggle('sel', s.conf === b.dataset.val);
  });
  document.querySelectorAll('#oObs button').forEach(b=>{
    b.classList.toggle('sel', (s.obstacles||[]).includes(b.dataset.val));
  });
  document.querySelectorAll('#oScene button').forEach(b=>{
    b.classList.toggle('sel', s.scene === b.dataset.val);
  });
  // 统计
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

function save(){
  try{ localStorage.setItem('e3_v5', JSON.stringify(STATE)); }catch(e){}
}

function markCorrect(){
  const s = st(LABELS[CUR]);
  s.verified = true;
  // 若未修改，保持 YOSO 预测
  if(!s.changed){ s.passable = LABELS[CUR].yoso_passable; s.stairs = LABELS[CUR].yoso_stairs; }
  refresh();
  const list = curList();
  const idx = list.indexOf(LABELS[CUR]);
  if(idx>=0 && idx<list.length-1) go(idx+1);
}

function buildResult(){
  return {
    meta:{generated:new Date().toISOString(), total:LABELS.length,
          verified:LABELS.filter(x=>STATE[x.file]&&STATE[x.file].verified).length,
          changed:LABELS.filter(x=>STATE[x.file]&&STATE[x.file].changed).length,
          task:"traversability_direction"},
    labels: LABELS.map(it=>{
      const s = STATE[it.file] || st(it);
      return {...it,
        passable: s.passable||'', stairs: s.stairs,
        conf: s.conf||'', obstacles: s.obstacles||[], scene: s.scene||'',
        note: s.note||'', verified: !!s.verified, changed: !!s.changed};
    })
  };
}

function exportJSON(){
  const blob = buildResult();
  const ta = document.getElementById('exportArea');
  ta.style.display='block'; ta.value = JSON.stringify(blob,null,2); ta.select();
  alert(`已核对 ${blob.meta.verified}/${blob.meta.total}，修改 ${blob.meta.changed} 张。\n已全选，Ctrl+C 复制保存为 labels_filled.json`);
}
function copyJSON(){
  const blob = buildResult();
  navigator.clipboard.writeText(JSON.stringify(blob,null,2))
    .then(()=>alert(`已复制（核对 ${blob.meta.verified}/${blob.meta.total}）`))
    .catch(()=>exportJSON());
}

document.addEventListener('keydown', e=>{
  if(e.target.tagName==='INPUT'||e.target.tagName==='TEXTAREA') return;
  const s = st(LABELS[CUR]);
  const k = e.key;
  if(k==='1'){ s.passable='left'; s.changed=(s.passable!==LABELS[CUR].yoso_passable); refresh(); }
  else if(k==='2'){ s.passable='ahead'; s.changed=(s.passable!==LABELS[CUR].yoso_passable); refresh(); }
  else if(k==='3'){ s.passable='right'; s.changed=(s.passable!==LABELS[CUR].yoso_passable); refresh(); }
  else if(k==='4'){ s.passable='none'; s.changed=(s.passable!==LABELS[CUR].yoso_passable); refresh(); }
  else if(k==='5'){ s.passable='unknown'; s.changed=(s.passable!==LABELS[CUR].yoso_passable); refresh(); }
  else if(k==='s'||k==='S'){ s.stairs = !s.stairs; s.changed=(s.stairs!==LABELS[CUR].yoso_stairs); refresh(); }
  else if(k==='Enter'){ markCorrect(); }
  else if(k==='ArrowRight'){ const l=curList(); const i=l.indexOf(LABELS[CUR]); if(i<l.length-1) go(i+1); }
  else if(k==='ArrowLeft'){ const l=curList(); const i=l.indexOf(LABELS[CUR]); if(i>0) go(i-1); }
});

init();
</script></body></html>"""


if __name__ == "__main__":
    main()
