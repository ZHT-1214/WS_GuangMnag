# -*- coding: utf-8 -*-
"""分析手机端自采拓扑图的采集质量，用于论文 B 层数据说明。

输入：从手机导出的 topology_maps/<map>/ 目录（节点按序号命名）
输出：采集质量指标（分辨率、节点间距估计、相邻/远端相似度、朝向变化代理指标）

与 exp_topomap_analysis.py 的区别：本脚本面向"手机自采数据"，只依赖图像，
不需要位姿；用图像相似度序列的变化率作为"场景推进速度"的代理。
"""
import argparse
import glob
import json
import os
import statistics

import numpy as np
from PIL import Image


def load_gray(path, size=(64, 48)):
    return np.asarray(Image.open(path).convert("L").resize(size), dtype=np.float32) / 255.0


def sim(a, b):
    return max(0.0, 1.0 - float(np.mean((a - b) ** 2)))


def analyse(d):
    files = sorted([f for f in glob.glob(os.path.join(d, "*"))
                    if os.path.basename(f).split(".")[0].isdigit()],
                   key=lambda p: int(os.path.basename(p).split(".")[0]))
    imgs = [load_gray(f) for f in files]
    n = len(imgs)
    adj = [sim(imgs[i], imgs[i + 1]) for i in range(n - 1)]
    far = [sim(imgs[i], imgs[j]) for i in range(n) for j in range(i + 1, n) if j - i >= max(3, n // 2)]
    sizes = {}
    for f in files:
        s = Image.open(f).size
        sizes[str(s)] = sizes.get(str(s), 0) + 1
    kbs = [os.path.getsize(f) / 1024 for f in files]
    return {
        "map_dir": os.path.basename(d.rstrip("/\\")),
        "n_nodes": n,
        "resolutions": sizes,
        "file_kb": {"min": round(min(kbs), 1), "median": round(statistics.median(kbs), 1),
                    "max": round(max(kbs), 1)},
        "adjacent_similarity": {
            "mean": round(statistics.mean(adj), 4),
            "min": round(min(adj), 4),
            "max": round(max(adj), 4),
        },
        "far_similarity_mean": round(statistics.mean(far), 4) if far else None,
        "discriminability_gap": round(statistics.mean(adj) - statistics.mean(far), 4) if far else None,
        "adjacent_similarity_p10": round(sorted(adj)[max(0, int(len(adj) * 0.1) - 1)], 4),
        "note": "adjacent 越高说明相邻帧越像（采集越密/走得越慢）；gap 越大拓扑图越可区分",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--map-dir", required=True)
    ap.add_argument("--out", default="phone_map_analysis.json")
    args = ap.parse_args()
    res = analyse(args.map_dir)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    json.dump(res, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
