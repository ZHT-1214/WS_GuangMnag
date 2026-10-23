# -*- coding: utf-8 -*-
"""生成 E3 标注工具 v4：明确区分"可通行方向"与"路线方向"。

v4 修正的核心问题：
  原问题"最安全的通行方向"存在歧义，可能被理解为：
    (a) 去哪最安全（导航/路线方向）
    (b) 哪里能走（避障/可通行方向）
  本工具只标注 (b)，与 YOSO 的 Navigater 模块定义一致。

标注项：
  1. 可通行方向：左/前/右/无路/无法判断（核心）
  2. 楼梯：有/无
  3. 置信度：高/中/低
  4. 障碍物类型（多选）
  5. 场景类型
"""
import base64
import json
import os
import shutil

# ===== 仓库路径定义（自动插入，适配 GitHub 仓库结构）=====
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)          # 仓库根目录
BASE_DIR = _REPO
RESULTS_DIR = os.path.join(_REPO, "data", "results")
LABELS_DIR = os.path.join(_REPO, "data", "labels")
ROUTES_DIR = os.path.join(_REPO, "data", "routes")
FIGS_DIR = os.path.join(_REPO, "figures")
# =========================================================


BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(BASE, "_素材", "obstacle_eval")
IMG_DIR = os.path.join(OUT_DIR, "images")
ROUTES = ["1", "2-2", "1-2", "2-6", "1-3", "2-7"]


def main():
    os.makedirs(IMG_DIR, exist_ok=True)
    labels = []
    for r in ROUTES:
        d = os.path.join(ROUTES_DIR, r)
        if not os.path.isdir(d):
            continue
        files = sorted([f for f in os.listdir(d)
                        if f.lower().endswith((".jpg", ".jpeg", ".png"))
                        and f.split(".")[0].isdigit()],
                       key=lambda x: int(x.split(".")[0]))
        for f in files:
            newname = f"{r}_{f}"
            dst = os.path.join(IMG_DIR, newname)
            if not os.path.exists(dst):
                shutil.copy2(os.path.join(d, f), dst)
            labels.append({
                "file": newname, "route": r,
                "orig_index": int(f.split(".")[0]),
                # 核心字段：可通行方向（避障通道的 ground truth）
                "passable": "",       # left / ahead / right / none / unclear
                "conf": "",           # high / medium / low
                "stairs": None,       # true / false
                "obstacles": [],      # 障碍物类型
                "scene": "",          # 场景类型
                "note": "",
            })

    images_b64 = {}
    for it in labels:
        with open(os.path.join(IMG_DIR, it["file"]), "rb") as f:
            images_b64[it["file"]] = base64.b64encode(f.read()).decode()

    data_json = json.dumps({"labels": labels, "images": images_b64}, ensure_ascii=False)
    html = TEMPLATE.replace("__DATA__", data_json)
    out = os.path.join(OUT_DIR, "label_tool_v4.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"待标注 {len(labels)} 张 -> {out}")
    print(f"大小 {os.path.getsize(out)/1024/1024:.1f} MB")


TEMPLATE = r"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>E3 避障标注工具 v4</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%;overflow:hidden;font-family:"Microsoft YaHei",sans-serif;background:#1a1a1a;color:#ddd}
#top{height:48px;background:#111;display:flex;align-items:center;gap:14px;padding:0 16px;border-bottom:1px solid #333}
#top b{color:#fff;font-size:15px}
#top .sp{flex:1}
button{padding:5px 12px;cursor:pointer;border:1px solid #666;border-radius:4px;background:#2a2a2a;color:#ddd;font-size:13px}
button:hover{background:#3a3a3a}
button.sel{background:#2b7a4b;border-color:#2b7a4b;color:#fff;font-weight:bold}
#body{display:flex;height:calc(100% - 48px)}
#left{width:190px;overflow-y:auto;background:#202020;border-right:1px solid #333;flex-shrink:0}
#left .it{padding:5px 10px;font-size:12px;cursor:pointer;border-left:3px solid transparent;display:flex;justify-content:space-between}
#left .it:hover{background:#2a2a2a}
#left .it.cur{background:#2b7a4b;border-left-color:#5fd;color:#fff}
#left .it.done{color:#6c9}
#center{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:12px;overflow:hidden;min-width:0}
#imgbox{flex:1;display:flex;align-items:center;justify-content:center;width:100%;overflow:hidden}
#img{max-width:100%;max-height:100%;object-fit:contain;border-radius:6px;box-shadow:0 4px 20px rgba(0,0,0,.6)}
#imgmeta{margin-top:6px;font-size:13px;color:#999}
#navrow{margin-top:8px;display:flex;gap:10px}
#right{width:340px;overflow-y:auto;background:#222;border-left:1px solid #333;padding:12px;flex-shrink:0}
.q{color:#8ecae6;font-size:13px;margin:12px 0 6px;font-weight:bold}
.q:first-child{margin-top:0}
.opts{display:flex;flex-wrap:wrap;gap:6px}
.opts button{padding:6px 11px;font-size:13px}
.hint{color:#888;font-size:11.5px;margin-top:5px;line-height:1.55}
.kbd{background:#333;padding:0 5px;border-radius:3px;font-family:monospace;font-size:11px}
#note{width:100%;background:#111;color:#ddd;border:1px solid #444;padding:6px;border-radius:4px;font-size:13px}
#exportArea{width:100%;height:70px;background:#111;color:#6c9;border:1px solid #444;font-family:monospace;font-size:11px;padding:6px;display:none;margin-top:8px}
.legend{background:#2a2a2a;border:1px solid #444;border-radius:6px;padding:10px;margin-bottom:10px;font-size:12px;line-height:1.7}
.legend b{color:#f9c74f}
.legend .row{display:flex;gap:8px;align-items:flex-start;margin-top:6px}
.legend .tag{background:#1a1a1a;border:1px solid #555;border-radius:3px;padding:1px 7px;font-weight:bold;white-space:nowrap}
</style></head><body>

<div id="top">
  <b>进度 <span id="prog">0</span> / <span id="total">0</span></b>
  <span id="curName" style="color:#8ecae6;font-size:13px">-</span>
  <span class="sp"></span>
  <span style="font-size:12px;color:#888">
    <span class="kbd">1</span>左 <span class="kbd">2</span>前 <span class="kbd">3</span>右 <span class="kbd">4</span>无路
    <span class="kbd">5</span>无法判断 <span class="kbd">S</span>楼梯 <span class="kbd">←</span><span class="kbd">→</span>翻页
  </span>
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
      <button onclick="go(CUR+1)">下一张 →</button>
    </div>
  </div>
  <div id="right">
    <div class="legend">
      <b>⚠ 只标注「哪里能走」，不要考虑「要去哪里」</b>
      <div class="row"><span class="tag">左</span><span>画面中可通行空间（地面/路面）主要从<b>左侧</b>延伸出去，或左侧明显更开阔</span></div>
      <div class="row"><span class="tag">前</span><span>可通行空间在<b>正前方</b>，两侧被墙/物挡住，只能直行</span></div>
      <div class="row"><span class="tag">右</span><span>可通行空间主要从<b>右侧</b>延伸出去，或右侧明显更开阔</span></div>
      <div class="row"><span class="tag">无路</span><span>可通行空间被<b>完全挡住</b>（面前是墙/整片障碍），无路可走</span></div>
      <div class="row"><span class="tag">无法判断</span><span>画面过暗、过曝、模糊，或完全看不出地面（如镜头朝天花板）</span></div>
      <div class="hint">判断依据：想象你是盲人，站在拍摄位置，只靠这一步画面决定往哪迈脚。</div>
    </div>

    <div class="q">① 可通行方向（核心）</div>
    <div class="opts" id="oDir"></div>
    <div class="q">② 是否有楼梯/台阶</div>
    <div class="opts" id="oStairs"></div>
    <div class="q">③ 判断置信度</div>
    <div class="opts" id="oConf"></div>
    <div class="q">④ 障碍物类型（可多选）</div>
    <div class="opts" id="oObs"></div>
    <div class="q">⑤ 场景类型</div>
    <div class="opts" id="oScene"></div>
    <div class="q">⑥ 备注（可选）</div>
    <input type="text" id="note" placeholder="特殊情况说明">
    <div class="hint" style="margin-top:12px">
      进度自动保存在浏览器，关闭不丢失。全部完成后点「导出 JSON」。
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

const DIRS = [["left","左"],["ahead","前"],["right","右"],["none","无路"],["unclear","无法判断"]];
const CONFS = [["high","高"],["medium","中"],["low","低"]];
const STAIRS = [[true,"有"],[false,"无"]];
const OBSTACLES = ["person 人","furniture 桌椅","wall 墙柱","door 门","plant 绿植","box 纸箱","stairs 楼梯","other 其他"];
const SCENES = [["corridor","走廊"],["room","房间"],["hall","大厅"],["doorway","门口"],["outdoor","室外"],["other","其他"]];

function st(it){ if(!STATE[it.file]) STATE[it.file]={obstacles:[]}; return STATE[it.file]; }
function done(it){ const s=STATE[it.file]; return !!(s && s.passable && s.stairs!==null && s.stairs!==undefined); }

function init(){
  document.getElementById('total').textContent = LABELS.length;
  try{ const sv = localStorage.getItem('e3_labels_v4'); if(sv) STATE = JSON.parse(sv); }catch(e){}
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
      b.textContent = label;
      b.dataset.val = String(v);
      b.onclick = ()=>{ onPick(v); refresh(); };
      box.appendChild(b);
    });
  };
  mk('oDir', DIRS, v=>{ const s=st(LABELS[CUR]); s.passable = (s.passable===v?'':v); });
  mk('oStairs', STAIRS, v=>{ const s=st(LABELS[CUR]); s.stairs = (s.stairs===v?null:v); });
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
  if(i<0||i>=LABELS.length) return;
  CUR = i;
  const it = LABELS[i];
  document.getElementById('curName').textContent = it.file;
  document.getElementById('img').src = 'data:image/jpeg;base64,' + IMAGES[it.file];
  document.getElementById('imgmeta').textContent =
    `第 ${i+1} / ${LABELS.length} 张 · 路线 ${it.route} · 原始帧 ${it.orig_index}`;
  document.getElementById('note').value = st(it).note || '';
  refresh();
  const el = document.getElementById('li_'+i);
  if(el) el.scrollIntoView({block:'nearest'});
}

function refresh(){
  const it = LABELS[CUR];
  const s = st(it);
  document.querySelectorAll('#oDir button').forEach(b=>{
    b.classList.toggle('sel', s.passable === b.dataset.val);
  });
  document.querySelectorAll('#oStairs button').forEach(b=>{
    const sel = (s.stairs!==null && s.stairs!==undefined) && (String(s.stairs)===b.dataset.val);
    b.classList.toggle('sel', sel);
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
  let n=0;
  LABELS.forEach((x,i)=>{
    const isd = done(x);
    if(isd) n++;
    const el = document.getElementById('li_'+i);
    if(el){ el.classList.toggle('done', isd); el.classList.toggle('cur', i===CUR); }
  });
  document.getElementById('prog').textContent = n;
  save();
}

function save(){
  try{ localStorage.setItem('e3_labels_v4', JSON.stringify(STATE)); }catch(e){}
}

function buildResult(){
  return {
    meta:{
      generated:new Date().toISOString(),
      total:LABELS.length,
      completed:LABELS.filter(done).length,
      task:"traversability_direction",
      note:"passable 表示画面中可通行空间的延伸方向，与导航目标无关"
    },
    labels: LABELS.map(it=>{
      const s = STATE[it.file]||{};
      return {...it,
        passable: s.passable||'', conf: s.conf||'',
        stairs: (s.stairs===undefined||s.stairs===null)?null:s.stairs,
        obstacles: s.obstacles||[], scene: s.scene||'', note: s.note||''};
    })
  };
}

function exportJSON(){
  const blob = buildResult();
  const ta = document.getElementById('exportArea');
  ta.style.display='block';
  ta.value = JSON.stringify(blob, null, 2);
  ta.select();
  alert(`已生成 JSON（已完成 ${blob.meta.completed}/${blob.meta.total}）。\n已全选，按 Ctrl+C 复制，保存为 labels_filled.json`);
}

function copyJSON(){
  const blob = buildResult();
  navigator.clipboard.writeText(JSON.stringify(blob,null,2))
    .then(()=>alert(`已复制（${blob.meta.completed}/${blob.meta.total}）`))
    .catch(()=>exportJSON());
}

document.addEventListener('keydown', e=>{
  if(e.target.tagName==='INPUT'||e.target.tagName==='TEXTAREA') return;
  const s = st(LABELS[CUR]);
  const k = e.key;
  if(k==='1'){ s.passable='left'; refresh(); }
  else if(k==='2'){ s.passable='ahead'; refresh(); }
  else if(k==='3'){ s.passable='right'; refresh(); }
  else if(k==='4'){ s.passable='none'; refresh(); }
  else if(k==='5'){ s.passable='unclear'; refresh(); }
  else if(k==='s'||k==='S'){ s.stairs = (s.stairs===true?false:true); refresh(); }
  else if(k==='ArrowRight'){ go(CUR+1); }
  else if(k==='ArrowLeft'){ go(CUR-1); }
});

init();
</script></body></html>"""


if __name__ == "__main__":
    main()
