# -*- coding: utf-8 -*-
"""C 组 baseline 的重新设计：诚实地界定"什么能比、什么不能比"。

## 核心问题

重放实验（帧 i 对应节点 i）存在"顺序已知"的信息泄漏：
  - 任何利用序列单调性的方法（DTW、单调约束、滑动窗口）都能轻易达到 100%
  - 因为这些方法隐含地使用了"帧顺序 = 节点顺序"这一先验

这**不是有效的 baseline**，必须排除。

## 有效的对比设计

### 对比 1：单帧定位能力（无序列先验）
问题：只给一帧，不给任何位置先验，能否定位到正确节点？
  - 这是真正的"视觉地点识别"能力
  - 纯检索（B1）就是这个设定
  - NoMaD 的等价设定：只用当前帧，不累积上下文

结论：B1 ±0 = 0%，±2 = 26.5% → 单帧视觉特征不足以精确定位

### 对比 2：在线序列定位（无未来信息）
问题：逐帧到达时，只用过去信息定位
  - 这是真实部署的设定
  - 但重放实验无法区分"用了未来"和"没用未来"，除非显式限制

### 结论：C 组 baseline 的正确表述

不能声称"NoMaD 比纯检索好 93 个百分点"，因为：
  1. 重放设定下，序列方法必然 100%（信息泄漏）
  2. 单帧检索 vs 多帧+距离预测，任务难度不同

**正确的结论应该是**：
  - NoMaD 的视觉编码器**单独**不具备节点级定位能力（单帧 ±0 = 0%，±2 仅 26.5%）
  - 节点定位能力来自**距离预测头 + 多帧上下文**的联合作用
  - 这解释了为什么 NoMaD 需要专门训练 DenseNetwork 而非直接做特征检索

本脚本产出这个诚实版本的结论，并明确标注实验边界。
"""
import json
import os
import statistics

import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FEAT_DIR = os.path.join(BASE, "实验", "results", "nomad_features")
NAV_RESULT = os.path.join(BASE, "实验", "results", "navigation_all.json")
OUT = os.path.join(BASE, "实验", "results", "baseline_c_honest.json")

ROUTE_MAP = {"1": "route_1", "2-2": "route_2-2", "1-2": "route_1-2",
             "2-6": "route_2-6", "1-3": "route_1-3", "2-7": "route_2-7"}
WARMUP = 4


def l2n(x):
    return x / np.maximum(np.linalg.norm(x, axis=1, keepdims=True), 1e-8)


def single_frame_retrieval(sm, n):
    """单帧检索：排除自身，无任何序列先验。"""
    out = []
    for i in range(n):
        row = sm[i].copy()
        row[i] = -9
        out.append(int(np.argmax(row)))
    return out


def main():
    nav = json.load(open(NAV_RESULT, encoding="utf-8"))
    nomad = {}
    for r in nav.get("routes", []):
        if "error" in r:
            continue
        nm = r.get("name", r["map_id"][:8])
        nomad[nm] = r["metrics"]["node_tracking_accuracy"]

    rows = []
    for name, fname in ROUTE_MAP.items():
        p = os.path.join(FEAT_DIR, f"{fname}.npy")
        if not os.path.exists(p):
            continue
        feats = np.load(p)
        n = feats.shape[0]
        sm = l2n(feats) @ l2n(feats).T

        preds = single_frame_retrieval(sm, n)
        accs = {}
        for tol in (0, 1, 2, 3, 5):
            ok = sum(1 for i in range(WARMUP, n) if abs(preds[i] - i) <= tol)
            accs[f"tol_{tol}"] = round(ok / (n - WARMUP), 4)

        # 特征区分度
        adj = [sm[i, i + 1] for i in range(n - 1)]
        far = [sm[i, j] for i in range(n) for j in range(i + 3, n)]
        gap = float(np.mean(adj) - np.mean(far)) if adj and far else 0.0

        rows.append({
            "route": name, "n_nodes": n,
            "gap": round(gap, 4),
            "single_frame_retrieval": accs,
            "nomad_accuracy": nomad.get(name),
        })

    def avg_tol(t):
        return round(statistics.mean([r["single_frame_retrieval"][f"tol_{t}"] for r in rows]), 4)

    summary = {
        "n_routes": len(rows),
        "n_nodes_total": sum(r["n_nodes"] for r in rows),
        "gap_mean": round(statistics.mean([r["gap"] for r in rows]), 4),
        "single_frame_retrieval": {f"tol_{t}": avg_tol(t) for t in (0, 1, 2, 3, 5)},
        "nomad_accuracy": round(statistics.mean(
            [r["nomad_accuracy"] for r in rows if r["nomad_accuracy"] is not None]), 4),
        "valid_comparison": (
            "单帧检索（无序列先验） vs NoMaD（4 帧上下文 + 距离预测头）。"
            "二者任务难度不同，不应直接相减得出'提升百分比'。"
        ),
        "excluded": (
            "DTW/单调约束/滑动窗口等利用序列单调性的方法被排除："
            "重放设定下帧序=节点序，这些方法必然达到 100%，属信息泄漏。"
        ),
        "conclusion": (
            "NoMaD 的视觉编码器单独不具备节点级判别力（单帧精确匹配 0%，±2 容差仅 26.5%），"
            "节点定位能力来自距离预测头与多帧上下文的联合作用。"
        ),
    }

    json.dump({"summary": summary, "per_route": rows},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    print("=" * 78)
    print("C 组 baseline（诚实版）")
    print("=" * 78)
    print(f"路线数: {summary['n_routes']}  节点总数: {summary['n_nodes_total']}")
    print(f"特征区分度 gap 均值: {summary['gap_mean']:.4f}")
    print("\n单帧纯检索准确率（无序列先验）:")
    s = summary["single_frame_retrieval"]
    for t in (0, 1, 2, 3, 5):
        print(f"  ±{t}: {s[f'tol_{t}']*100:5.1f}%")
    print(f"\nNoMaD 节点跟踪准确率（4 帧上下文 + 距离预测）: "
          f"{summary['nomad_accuracy']*100:.1f}%")

    print("\n逐路线:")
    print(f"{'路线':<7}{'节点':>5}{'gap':>8}{'±0':>8}{'±2':>8}{'NoMaD':>9}")
    print("-" * 50)
    for r in rows:
        sr = r["single_frame_retrieval"]
        print(f"{r['route']:<7}{r['n_nodes']:>5}{r['gap']:>8.4f}"
              f"{sr['tol_0']*100:>7.1f}%{sr['tol_2']*100:>7.1f}%"
              f"{(r['nomad_accuracy'] or 0)*100:>8.1f}%")

    print(f"\n⚠ 重要说明:")
    print(f"  {summary['excluded']}")
    print(f"\n保存 -> {OUT}")


if __name__ == "__main__":
    main()
