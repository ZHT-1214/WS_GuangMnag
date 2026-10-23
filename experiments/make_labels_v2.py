# -*- coding: utf-8 -*-
"""生成 E3 避障评测的完整标注工具（数据内嵌，双击即用）。

改进点（相比 v1）：
  1. labels 数据直接嵌入 HTML，避免 file:// 下 fetch 被 CORS 拦截
  2. 全量 312 张图都纳入标注
  3. 标注粒度更细，符合会议论文要求：
     - 可通行方向（left/ahead/right/none）+ 置信度
     - 楼梯 / 台阶 / 障碍物类型多选
     - 场景类型（走廊/房间/大厅/门口/其他）
  4. 自动保存到 localStorage（关浏览器不丢）
  5. 支持键盘快捷键（1-4 方向，S 楼梯，空格下一张）
  6. 导出为 JSON + 一键复制
"""
import base64
import json
import os

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

    # 收集全部图片并复制
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
            src = os.path.join(d, f)
            dst = os.path.join(IMG_DIR, newname)
            if not os.path.exists(dst):
                import shutil
                shutil.copy2(src, dst)
            labels.append({
                "file": newname,
                "route": r,
                "orig_index": int(f.split(".")[0]),
                "passable": "",
                "conf": "",           # high / medium / low
                "stairs": None,
                "obstacles": [],      # ["person","furniture","wall",...]
                "scene": "",          # corridor / room / hall / doorway / outdoor
                "note": "",
            })

    # 图片转 base64 内嵌（312 张 × ~50KB ≈ 15MB，可接受）
    images_b64 = {}
    for it in labels:
        p = os.path.join(IMG_DIR, it["file"])
        with open(p, "rb") as f:
            images_b64[it["file"]] = base64.b64encode(f.read()).decode()

    data_json = json.dumps({"labels": labels, "images": images_b64},
                           ensure_ascii=False)

    html = HTML_TEMPLATE.replace("__DATA__", data_json)
    out_path = os.path.join(OUT_DIR, "label_tool_v2.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"待标注: {len(labels)} 张")
    print(f"工具已生成: {os.path.abspath(out_path)}")
    print(f"文件大小: {os.path.getsize(out_path)/1024/1024:.1f} MB（含内嵌图片）")


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>E3 避障标注工具 v2</title>
<style>
*{box-sizing:border-box}
body{font-family:"Microsoft YaHei",sans-serif;margin:0;background:#1e1e1e;color:#ddd}
#bar{position:sticky;top:0;background:#111;padding:10px 16px;z-index:10;display:flex;gap:12px;align-items:center;flex-wrap:wrap}
#bar b{color:#fff}
button{padding:6px 14px;cursor:pointer;border:1px solid #666;border-radius:4px;background:#2a2a2a;color:#ddd;font-size:14px}
button:hover{background:#3a3a3a}
button.sel{background:#2b7a4b;border-color:#2b7a4b;color:#fff}
button.warn{background:#7a4b2b;border-color:#7a4b2b}
#wrap{display:flex;height:calc(100vh - 52px)}
#side{width:280px;overflow-y:auto;background:#252525;padding:8px}
#side .it{padding:6px 10px;cursor:pointer;border-radius:4px;font-size:13px;display:flex;justify-content:space-between}
#side .it:hover{background:#333}
#side .it.cur{background:#2b7a4b}
#side .it.done{color:#7dcf9f}
#side .it .tag{opacity:.7;font-size:11px}
#main{flex:1;overflow-y:auto;padding:16px}
.card{background:#252525;padding:16px;border-radius:10px;max-width:900px;margin-bottom:20px}
.card img{width:100%;max-width:720px;display:block;border-radius:6px;margin:10px 0}
.q{margin:8px 0 4px;color:#8ecae6;font-size:14px}
.hint{color:#888;font-size:12px;margin:4px 0}
.kbd{background:#333;padding:1px 6px;border-radius:3px;font-family:monospace}
textarea{width:100%;height:140px;background:#111;color:#9f9;border:1px solid #444;font-family:monospace;font-size:12px;padding:8px}
input[type=text]{background:#111;color:#ddd;border:1px solid #444;padding:6px;border-radius:4px;width:300px}
.nav{display:flex;gap:8px;margin-top:10px}
</style></head><body>
<div id="bar">
  <b>进度: <span id="prog">0</span>/<span id="total">0</span></b>
  <span>当前: <span id="curName">-</span></span>
  <button onclick="exportJSON()">导出 JSON</button>
  <button onclick="copyJSON()">复制到剪贴板</button>
  <span class="hint">快捷键: <span class="kbd">1</span>左 <span class="kbd">2</span>前 <span class="kbd">3</span>右 <span class="kbd">4</span>无路 <span class="kbd">S</span>楼梯 <span class="kbd">→</span>下一张</span>
</div>
<div id="wrap">
  <div id="side"></div>
  <div id="main"></div>
</div>
<script>
const DATA = __DATA__;
const LABELS = DATA.labels;
const IMAGES = DATA.images;
const STATE = {};
let CUR = 0;

const DIRS = [["left","向左 (1)"],["ahead","向前 (2)"],["right","向右 (3)"],["none","无路 (4)"]];
const CONF = [["high","高"],["medium","中"],["low","低"]];
const OBSTACLES = ["person 人","chair/furniture 桌椅","wall/column 墙柱","door 门","plant 绿植","box 纸箱","stairs 楼梯","other 其他"];
const SCENES = [["corridor","走廊"],["room","房间"],["hall","大厅/开阔"],["doorway","门口/通道"],["outdoor","室外"],["other","其他"]];

function init(){
  document.getElementById('total').textContent = LABELS.length;
  // 恢复 localStorage
  try{
    const saved = JSON.parse(localStorage.getItem('e3_labels')||'{}');
    Object.assign(STATE, saved);
  }catch(e){}
  // 侧栏
  const side = document.getElementById('side');
  LABELS.forEach((it,i)=>{
    const d = document.createElement('div'); d.className='it'; d.id='side_'+i;
    d.innerHTML = `<span>${i+1}. ${it.file}</span><span class="tag">${it.route}</span>`;
    d.onclick = ()=>show(i);
    side.appendChild(d);
  });
  updateProgress();
  show(0);
}
function stateOf(it){ if(!STATE[it.file]) STATE[it.file]={}; return STATE[it.file]; }
function isDone(it){ const s=STATE[it.file]; return s && s.passable && s.stairs!==null && s.stairs!==undefined; }
function updateProgress(){
  const n = LABELS.filter(isDone).length;
  document.getElementById('prog').textContent = n;
  LABELS.forEach((it,i)=>{
    const el = document.getElementById('side_'+i);
    if(!el) return;
    el.classList.toggle('done', isDone(it));
    el.classList.toggle('cur', i===CUR);
  });
  localStorage.setItem('e3_labels', JSON.stringify(STATE));
}
function mkBtn(label, cur, cb){
  const b=document.createElement('button'); b.textContent=label;
  if(cur) b.classList.add('sel');
  b.onclick=cb; return b;
}
function show(i){
  CUR = i;
  const it = LABELS[i]; const s = stateOf(it);
  const m = document.getElementById('main');
  document.getElementById('curName').textContent = it.file;
  m.innerHTML = `<div class="card">
    <div><b>${i+1} / ${LABELS.length}</b> &nbsp; ${it.file} &nbsp; <span style="color:#888">路线 ${it.route} · 原始帧 ${it.orig_index}</span></div>
    <img src="data:image/jpeg;base64,${IMAGES[it.file]}">
    <div class="q">① 人站在此处，最安全的通行方向是？</div>
    <div id="dirRow"></div>
    <div class="q">② 该判断的置信度？</div>
    <div id="confRow"></div>
    <div class="q">③ 画面中是否有楼梯/台阶？</div>
    <div id="stRow"></div>
    <div class="q">④ 画面中的障碍物类型（可多选）</div>
    <div id="obRow"></div>
    <div class="q">⑤ 场景类型</div>
    <div id="scRow"></div>
    <div class="q">备注（可选）</div>
    <input type="text" id="noteBox" value="${(s.note||'').replace(/"/g,'&quot;')}" onchange="stateOf(LABELS[${i}]).note=this.value; updateProgress()">
    <div class="nav">
      <button onclick="show(${Math.max(0,i-1)})">← 上一张</button>
      <button onclick="show(${Math.min(LABELS.length-1,i+1)})">下一张 →</button>
    </div>
  </div>`;
  // 方向
  const dr = document.getElementById('dirRow');
  DIRS.forEach(([v,label])=>{
    dr.appendChild(mkBtn(label, s.passable===v, ()=>{ s.passable=v; show(i); }));
  });
  // 置信度
  const cr = document.getElementById('confRow');
  CONF.forEach(([v,label])=>{
    cr.appendChild(mkBtn(label, s.conf===v, ()=>{ s.conf = (s.conf===v?'':v); show(i); }));
  });
  // 楼梯
  const sr = document.getElementById('stRow');
  [['true','有'],['false','无']].forEach(([v,label])=>{
    sr.appendChild(mkBtn(label, s.stairs!==null&&s.stairs!==undefined&&(String(s.stairs)===v), ()=>{
      s.stairs = (v==='true'); show(i);
    }));
  });
  // 障碍物（多选）
  const or = document.getElementById('obRow');
  if(!s.obstacles) s.obstacles=[];
  OBSTACLES.forEach(o=>{
    const name = o.split(' ')[0];
    const b = mkBtn(o, s.obstacles.includes(name), ()=>{
      const idx = s.obstacles.indexOf(name);
      if(idx>=0) s.obstacles.splice(idx,1); else s.obstacles.push(name);
      show(i);
    });
    or.appendChild(b);
  });
  // 场景
  const scr = document.getElementById('scRow');
  SCENES.forEach(([v,label])=>{
    scr.appendChild(mkBtn(label, s.scene===v, ()=>{ s.scene=(s.scene===v?'':v); show(i); }));
  });
  // note 输入框变化保存
  document.getElementById('noteBox').onchange = function(){ s.note=this.value; updateProgress(); };
  updateProgress();
  m.scrollTop = 0;
  document.getElementById('side_'+i).scrollIntoView({block:'nearest'});
}
function exportJSON(){
  const out = LABELS.map(it=>{
    const s = STATE[it.file]||{};
    return {...it, passable:s.passable||'', conf:s.conf||'',
            stairs:(s.stairs===undefined||s.stairs===null)?null:s.stairs,
            obstacles:s.obstacles||[], scene:s.scene||'', note:s.note||''};
  });
  const done = out.filter(x=>x.passable && x.stairs!==null).length;
  const blob = {meta:{generated:new Date().toISOString(), total:out.length, completed:done}, labels:out};
  document.getElementById('main').querySelector('.card').insertAdjacentHTML('beforeend',
    `<div><textarea id="expBox" style="height:200px">${JSON.stringify(blob,null,2).replace(/</g,'&lt;')}</textarea>
     <div class="hint">已完成 ${done}/${out.length}。全选复制上方文本，保存为 labels_filled.json</div></div>`);
  document.getElementById('expBox').select();
}
function copyJSON(){
  const out = LABELS.map(it=>{
    const s = STATE[it.file]||{};
    return {...it, passable:s.passable||'', conf:s.conf||'',
            stairs:(s.stairs===undefined||s.stairs===null)?null:s.stairs,
            obstacles:s.obstacles||[], scene:s.scene||'', note:s.note||''};
  });
  const blob = {meta:{generated:new Date().toISOString(), total:out.length,
                completed:out.filter(x=>x.passable && x.stairs!==null).length}, labels:out};
  navigator.clipboard.writeText(JSON.stringify(blob,null,2))
    .then(()=>alert('已复制到剪贴板，粘贴保存为 labels_filled.json'))
    .catch(()=>alert('复制失败，请用“导出 JSON”按钮'));
}
document.addEventListener('keydown', e=>{
  if(e.target.tagName==='TEXTAREA'||e.target.tagName==='INPUT') return;
  const it = LABELS[CUR]; const s = stateOf(it);
  if(e.key==='1'){s.passable='left'; show(CUR);}
  else if(e.key==='2'){s.passable='ahead'; show(CUR);}
  else if(e.key==='3'){s.passable='right'; show(CUR);}
  else if(e.key==='4'){s.passable='none'; show(CUR);}
  else if(e.key==='s'||e.key==='S'){s.stairs=!s.stairs; show(CUR);}
  else if(e.key==='ArrowRight'){show(Math.min(LABELS.length-1,CUR+1));}
  else if(e.key==='ArrowLeft'){show(Math.max(0,CUR-1));}
});
init();
</script></body></html>"""


if __name__ == "__main__":
    main()
