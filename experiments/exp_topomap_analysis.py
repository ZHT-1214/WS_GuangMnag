# -*- coding: utf-8 -*-
"""离线实验 2：拓扑图建图质量与节点判别力分析。

针对本地真实数据（tartan_drive 轨迹 + my_home_map 拓扑图），回答三个问题：
  Q1 拓扑图节点在视觉上是否可区分（相邻节点相似度 vs 远端节点相似度）
  Q2 按"节点间位移"划分的子目标窗口半径是否合理（radius=4 覆盖多少米）
  Q3 轨迹的航向变化分布，判断"方向指令"在真实数据中的可用性

不依赖 GPU：图像相似度用缩略图直方图 + 灰度结构相关性计算。
"""
import argparse
import glob
import json
import math
import os
import pickle
import statistics

import numpy as np
from PIL import Image


def load_gray(path, size=(64, 48)):
    im = Image.open(path).convert("L").resize(size)
    return np.asarray(im, dtype=np.float32) / 255.0


def similarity(a, b):
    """结构相似性的简化度量：1 - 归一化均方误差，范围[0,1]。"""
    mse = float(np.mean((a - b) ** 2))
    return max(0.0, 1.0 - mse)


def analyse_topomap(topomap_dir):
    files = sorted(
        [f for f in glob.glob(os.path.join(topomap_dir, "*"))
         if os.path.basename(f).split(".")[0].isdigit()],
        key=lambda p: int(os.path.basename(p).split(".")[0]))
    imgs = [load_gray(f) for f in files]
    n = len(imgs)
    if n < 3:
        return {"n_nodes": n, "note": "节点过少"}

    adj, far = [], []
    for i in range(n):
        for j in range(i + 1, n):
            s = similarity(imgs[i], imgs[j])
            if j - i == 1:
                adj.append(s)
            elif j - i >= max(3, n // 2):
                far.append(s)
    return {
        "n_nodes": n,
        "adjacent_similarity_mean": round(statistics.mean(adj), 4),
        "far_similarity_mean": round(statistics.mean(far), 4),
        "discriminability_gap": round(statistics.mean(adj) - statistics.mean(far), 4),
        "adjacent_similarity_min": round(min(adj), 4),
        "far_similarity_max": round(max(far), 4),
        "note": "相邻节点应显著比远端节点相似；gap 越大说明拓扑图越可区分",
    }


def analyse_window(traj_root, radius=4):
    """按轨迹相邻帧位移，估算 radius 个节点覆盖的物理距离。"""
    dists = []
    for d in sorted(glob.glob(os.path.join(traj_root, "*"))):
        pkl = os.path.join(d, "traj_data.pkl")
        if not os.path.isdir(d) or not os.path.exists(pkl):
            continue
        with open(pkl, "rb") as f:
            td = pickle.load(f)
        pos = td.get("position")
        if pos is None or len(pos) < 2:
            continue
        for i in range(len(pos) - 1):
            dists.append(math.hypot(pos[i + 1][0] - pos[i][0],
                                    pos[i + 1][1] - pos[i][1]))
    if not dists:
        return {}
    med = statistics.median(dists)
    return {
        "n_intervals": len(dists),
        "median_node_spacing_m": round(med, 4),
        "radius_nodes": radius,
        "radius_covered_m": round(med * radius, 3),
        "mean_spacing_m": round(statistics.mean(dists), 4),
    }


def analyse_heading(traj_root):
    """航向变化分布：判断数据集是否包含足够转弯，用于方向指令评估。"""
    changes = []
    for d in sorted(glob.glob(os.path.join(traj_root, "*"))):
        pkl = os.path.join(d, "traj_data.pkl")
        if not os.path.isdir(d) or not os.path.exists(pkl):
            continue
        with open(pkl, "rb") as f:
            td = pickle.load(f)
        yaw = td.get("yaw")
        if yaw is None or len(yaw) < 2:
            continue
        for i in range(len(yaw) - 1):
            dd = abs(float(yaw[i + 1]) - float(yaw[i]))
            dd = min(dd, 2 * math.pi - dd)
            changes.append(math.degrees(dd))
    if not changes:
        return {}
    s = sorted(changes)
    return {
        "n_frames": len(changes),
        "heading_change_deg": {
            "mean": round(statistics.mean(changes), 3),
            "median": round(statistics.median(changes), 3),
            "p90": round(s[int(len(s) * 0.90)], 3),
            "p99": round(s[int(len(s) * 0.99)], 3),
            "max": round(s[-1], 3),
        },
        "ratio_over_10deg": round(sum(1 for c in changes if c > 10) / len(changes), 4),
        "ratio_over_30deg": round(sum(1 for c in changes if c > 30) / len(changes), 4),
        "note": "若 over_10deg 极低，说明采集时未按行进方向转动，方向指令评估需重新采集",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--topomap", required=True)
    ap.add_argument("--trajs", required=True)
    ap.add_argument("--out", default="topomap_analysis.json")
    args = ap.parse_args()

    res = {
        "topomap": analyse_topomap(args.topomap),
        "window": analyse_window(args.trajs),
        "heading": analyse_heading(args.trajs),
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    json.dump(res, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
