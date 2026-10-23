# -*- coding: utf-8 -*-
"""生成 E3 避障评测的标注模板。

从 6 条路线的节点图中抽样，生成待标注清单。
标注项：最安全通行方向（left/ahead/right/none）+ 是否有楼梯。

用法：
    python make_labels.py --out 论文/_素材/obstacle_eval --per-route 20
"""
import argparse
import json
import os
import random
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


ROUTES_DIR = ROUTES_DIR
ROUTES = ["1", "2-2", "1-2", "2-6", "1-3", "2-7"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=LABELS_DIR)
    ap.add_argument("--per-route", type=int, default=20, help="每条路线抽多少张")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    random.seed(args.seed)
    img_dir = os.path.join(args.out, "images")
    os.makedirs(img_dir, exist_ok=True)

    labels = []
    stats = {}
    for r in ROUTES:
        d = os.path.join(ROUTES_DIR, r)
        if not os.path.isdir(d):
            print(f"跳过 {r}")
            continue
        files = sorted([f for f in os.listdir(d)
                        if f.lower().endswith((".jpg", ".jpeg", ".png"))
                        and f.split(".")[0].isdigit()],
                       key=lambda x: int(x.split(".")[0]))
        if not files:
            continue
        # 均匀抽样（覆盖整条路线，而不是随机）
        n = min(args.per_route, len(files))
        idx = [int(i * (len(files) - 1) / max(1, n - 1)) for i in range(n)] if n > 1 else [0]
        picked = [files[i] for i in idx]

        for f in picked:
            src = os.path.join(d, f)
            # 新文件名带路线前缀，避免重名
            newname = f"{r}_{f}"
            dst = os.path.join(img_dir, newname)
            shutil.copy2(src, dst)
            labels.append({
                "file": newname,
                "route": r,
                "orig_index": int(f.split(".")[0]),
                "passable": "",      # 待填: left / ahead / right / none
                "stairs": None,      # 待填: true / false
                "note": "",
            })
        stats[r] = len(picked)
        print(f"  {r}: 抽 {len(picked)} 张（原 {len(files)} 张）")

    label_path = os.path.join(args.out, "labels.json")
    with open(label_path, "w", encoding="utf-8") as fp:
        json.dump(labels, fp, ensure_ascii=False, indent=2)

    print(f"\n共 {len(labels)} 张待标注")
    print(f"图片目录: {os.path.abspath(img_dir)}")
    print(f"标注文件: {os.path.abspath(label_path)}")
    print("\n标注方法：")
    print("  1. 打开 labels.json（或下面的 HTML 工具）")
    print("  2. 对每张图判断：人站在此处，最安全的通行方向")
    print("     left=向左  ahead=向前  right=向右  none=无路可走")
    print("  3. stairs 填 true/false（画面中是否有楼梯）")
    print("  4. 保存后运行 exp_obstacle_eval.py 评测")

    # 生成一个简易 HTML 标注工具（双击即可用）
    html_path = os.path.join(args.out, "label_tool.html")
    html = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>避障标注工具</title>
<style>
body{font-family:sans-serif;margin:20px;background:#f5f5f5}
.card{background:#fff;padding:16px;margin-bottom:16px;border-radius:8px;box-shadow:0 2px 6px rgba(0,0,0,.1)}
img{max-width:640px;max-height:480px;display:block;margin-bottom:12px;border:1px solid #ccc}
button{margin-right:8px;padding:8px 16px;font-size:15px;cursor:pointer;border:1px solid #888;border-radius:4px;background:#fff}
button.sel{background:#2b7;color:#fff;border-color:#2b7}
.row{margin:6px 0}
.progress{position:sticky;top:0;background:#333;color:#fff;padding:10px;border-radius:6px;margin-bottom:16px;z-index:10}
#out{width:100%;height:200px;margin-top:20px;font-family:monospace;font-size:12px}
</style></head><body>
<div class="progress">进度: <span id="prog">0</span> / <span id="total">0</span>
&nbsp;&nbsp;<button onclick="exportJSON()">导出标注结果</button></div>
<div id="list"></div>
<textarea id="out" placeholder="点击“导出标注结果”后，把这里的内容保存为 labels_filled.json"></textarea>
<script>
let LABELS = [];
let STATE = {};
fetch('labels.json').then(r=>r.json()).then(data=>{
  LABELS = data; document.getElementById('total').textContent = data.length;
  const list = document.getElementById('list');
  data.forEach((it, i) => {
    const card = document.createElement('div'); card.className='card';
    card.innerHTML = `<div class="row"><b>${i+1}. ${it.file}</b> (路线 ${it.route})</div>
      <img src="images/${it.file}">`;
    const dirs = [['left','向左'],['ahead','向前'],['right','向右'],['none','无路']];
    const dirRow = document.createElement('div'); dirRow.className='row';
    dirRow.innerHTML = '<span>通行方向: </span>';
    dirs.forEach(([v,label])=>{
      const b=document.createElement('button'); b.textContent=label;
      b.onclick=()=>{ STATE[it.file]=(STATE[it.file]||{}); STATE[it.file].passable=v;
        dirRow.querySelectorAll('button').forEach(x=>x.classList.remove('sel')); b.classList.add('sel'); update(); };
      dirRow.appendChild(b);
    });
    card.appendChild(dirRow);
    const stRow = document.createElement('div'); stRow.className='row';
    stRow.innerHTML = '<span>有楼梯: </span>';
    [['true','是'],['false','否']].forEach(([v,label])=>{
      const b=document.createElement('button'); b.textContent=label;
      b.onclick=()=>{ STATE[it.file]=(STATE[it.file]||{}); STATE[it.file].stairs=(v==='true');
        stRow.querySelectorAll('button').forEach(x=>x.classList.remove('sel')); b.classList.add('sel'); update(); };
      stRow.appendChild(b);
    });
    card.appendChild(stRow);
    list.appendChild(card);
  });
});
function update(){
  const n = Object.keys(STATE).filter(k=>STATE[k].passable).length;
  document.getElementById('prog').textContent = n;
}
function exportJSON(){
  const out = LABELS.map(it=>{
    const s = STATE[it.file] || {};
    return {...it, passable: s.passable||'', stairs: (s.stairs===undefined?null:s.stairs)};
  });
  document.getElementById('out').value = JSON.stringify(out, null, 2);
  alert('已生成，复制下方文本框内容保存为 labels_filled.json');
}
</script></body></html>"""
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n标注工具: {os.path.abspath(html_path)}（用浏览器打开）")


if __name__ == "__main__":
    main()
