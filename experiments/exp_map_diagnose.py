# -*- coding: utf-8 -*-
"""诊断：为什么增加节点数反而降低了区分间隔（gap）。

核心假设：gap 低不是"采得密"，而是"整条路线视觉太单一"——
即路线内所有地方看起来都像，这属于场景问题而非采集问题。

本脚本把相似度拆解为：
  1. 相邻节点相似度随距离的变化（相似度衰减曲线）
  2. 路线中是否存在"视觉重复段"（相似度局部峰值）
  3. 场景多样性指标（图像颜色/纹理的方差）
"""
import argparse
import glob
import json
import os
import statistics

import numpy as np
from PIL import Image


def load_feat(path, size=(32, 24)):
    im = Image.open(path).convert("RGB").resize(size)
    return np.asarray(im, dtype=np.float32) / 255.0


def sim(a, b):
    return max(0.0, 1.0 - float(np.mean((a - b) ** 2)))


def analyze(map_dir):
    files = sorted([f for f in glob.glob(os.path.join(map_dir, "*"))
                    if os.path.basename(f).split(".")[0].isdigit()],
                   key=lambda p: int(os.path.basename(p).split(".")[0]))
    feats = [load_feat(f) for f in files]
    n = len(feats)
    if n < 5:
        return {"error": "节点太少"}

    # 1. 相似度随间隔衰减
    decay = {}
    for lag in [1, 2, 3, 5, 10, 20, 30]:
        if lag >= n:
            continue
        vals = [sim(feats[i], feats[i + lag]) for i in range(n - lag)]
        decay[lag] = {
            "mean": round(statistics.mean(vals), 4),
            "min": round(min(vals), 4),
            "max": round(max(vals), 4),
        }

    # 2. 相邻相似度序列：找局部高峰（视觉重复）
    adj = [sim(feats[i], feats[i + 1]) for i in range(n - 1)]
    mean_adj = statistics.mean(adj)
    std_adj = statistics.pstdev(adj) if len(adj) > 1 else 0
    high_pairs = [(i, round(s, 4)) for i, s in enumerate(adj) if s > mean_adj + std_adj]

    # 3. 场景多样性：图像均值的标准差（颜色变化）
    means = np.array([f.mean(axis=(0, 1)) for f in feats])  # (n, 3)
    color_std = means.std(axis=0)
    # 全局色彩方差（所有像素）
    all_pixels = np.concatenate([f.reshape(-1, 3) for f in feats], axis=0)
    pixel_std = all_pixels.std(axis=0)

    # 4. 最相似的非相邻对（误匹配风险点）
    worst = []
    for i in range(n):
        for j in range(i + 3, n):
            s = sim(feats[i], feats[j])
            worst.append((round(s, 4), i, j))
    worst.sort(reverse=True)
    top5 = worst[:5]

    # 5. 最近邻检索的可分性：每个节点最像的是不是它的邻居
    nn_correct = 0
    for i in range(n):
        best_j, best_s = -1, -1
        for j in range(n):
            if j == i:
                continue
            s = sim(feats[i], feats[j])
            if s > best_s:
                best_s, best_j = s, j
        if abs(best_j - i) <= 2:
            nn_correct += 1

    return {
        "map_dir": os.path.basename(map_dir.rstrip("/\\")),
        "n_nodes": n,
        "similarity_decay_by_lag": decay,
        "adjacent": {
            "mean": round(mean_adj, 4),
            "std": round(std_adj, 4),
            "n_high_peaks": len(high_pairs),
            "high_peaks": high_pairs[:10],
        },
        "scene_diversity": {
            "color_mean_std": [round(float(x), 4) for x in color_std],
            "pixel_std": [round(float(x), 4) for x in pixel_std],
        },
        "top_similar_nonadjacent": [
            {"sim": s, "i": i, "j": j, "gap": j - i} for s, i, j in top5
        ],
        "nn_neighbor_accuracy": round(nn_correct / n, 4),
        "nn_note": "每个节点最近邻是否落在±2范围内；越高说明外观检索越可靠",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--map-dir", required=True)
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    res = analyze(args.map_dir)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
        json.dump(res, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
