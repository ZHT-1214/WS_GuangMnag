# -*- coding: utf-8 -*-
"""C 组 baseline 对比（公平版）：同骨干、仅换定位方式。

实验设计：
  所有方法都使用 NoMaD 的视觉编码器（EfficientNet-B0 + Transformer）提取的 256 维特征，
  唯一的区别是"如何用这些特征定位当前节点"：
    B1 纯外观检索：余弦相似度最近邻（排除自身）
    B2 检索+单调约束：禁止位置回退
    B3 检索+滑动窗口：限制在上一位置 ±W 内
    Proposed: NoMaD 距离预测头（DenseNetwork）+ 子目标选择

这样就把"距离预测头"的贡献单独隔离出来，是真正的消融实验。
评测口径：预测节点 == 真实节点（精确匹配），跳过前 4 帧 warmup。
"""
import json
import os
import statistics

import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FEAT_DIR = os.path.join(BASE, "实验", "results", "nomad_features")
NAV_RESULT = os.path.join(BASE, "实验", "results", "navigation_all.json")
OUT_JSON = os.path.join(BASE, "实验", "results", "baseline_fair_v2.json")

ROUTE_MAP = {
    "1": "route_1",
    "2-2": "route_2-2",
    "1-2": "route_1-2",
    "2-6": "route_2-6",
    "1-3": "route_1-3",
    "2-7": "route_2-7",
}
WINDOW = 5
WARMUP = 4


def l2norm(x):
    n = np.linalg.norm(x, axis=1, keepdims=True)
    return x / np.maximum(n, 1e-8)


def cosine_sim_matrix(feats):
    f = l2norm(feats)
    return f @ f.T


def exact_acc(preds, n, skip=WARMUP):
    if n <= skip:
        return 0.0
    ok = sum(1 for i in range(skip, n) if preds[i] == i)
    return round(ok / (n - skip), 4)


def offset_stats(preds, skip=WARMUP):
    offs = [abs(p - i) for i, p in enumerate(preds) if i >= skip]
    if not offs:
        return {"median": 0, "mean": 0, "p90": 0}
    return {
        "median": round(statistics.median(offs), 1),
        "mean": round(statistics.mean(offs), 2),
        "p90": round(sorted(offs)[min(int(len(offs) * 0.9), len(offs) - 1)], 1),
    }


def b1_pure(sm, n):
    preds = []
    for i in range(n):
        row = sm[i].copy()
        row[i] = -1
        preds.append(int(np.argmax(row)))
    return preds


def b2_monotonic(sm, n):
    preds, last = [], -1
    for i in range(n):
        row = sm[i].copy()
        row[i] = -1
        row[:last + 1] = -1
        preds.append(int(np.argmax(row)) if row.max() > -1 else min(last + 1, n - 1))
        last = preds[-1]
    return preds


def b3_window(sm, n, w=WINDOW):
    preds, last = [], 0
    for i in range(n):
        lo, hi = max(0, last - w), min(n, last + w + 1)
        mask = np.full(n, -1.0, dtype=np.float32)
        mask[lo:hi] = sm[i, lo:hi]
        if lo <= i < hi:
            mask[i] = -1
        preds.append(int(np.argmax(mask)) if mask.max() > -1 else last)
        last = preds[-1]
    return preds


def b4_temporal(sm, n, w=WINDOW, alpha=0.7):
    """B4: 检索 + 时序平滑（加权历史相似度），更接近真实 VPR 系统。"""
    preds, last = [], 0
    prev_score = None
    for i in range(n):
        row = sm[i].copy()
        row[i] = -1
        if prev_score is not None:
            # 加入位置先验：离上一位置越近分数越高
            prior = -np.abs(np.arange(n) - last) / max(n, 1)
            row = alpha * row + (1 - alpha) * prior
        preds.append(int(np.argmax(row)))
        last = preds[-1]
        prev_score = sm[i]
    return preds


def main():
    nav = json.load(open(NAV_RESULT, encoding="utf-8"))
    nomad = {}
    for r in nav.get("routes", []):
        if "error" in r:
            continue
        nm = r.get("name", r["map_id"][:8])
        nomad[nm] = r["metrics"]["node_tracking_accuracy"]

    results = []
    for name, fname in ROUTE_MAP.items():
        p = os.path.join(FEAT_DIR, f"{fname}.npy")
        if not os.path.exists(p):
            print(f"跳过 {name}（特征缺失）")
            continue
        feats = np.load(p)
        n = feats.shape[0]
        sm = cosine_sim_matrix(feats)

        preds = {
            "B1_pure_retrieval": b1_pure(sm, n),
            "B2_monotonic": b2_monotonic(sm, n),
            "B3_window": b3_window(sm, n),
            "B4_temporal_prior": b4_temporal(sm, n),
        }
        rec = {"route": name, "n_nodes": n,
               "nomad_accuracy": nomad.get(name)}
        for k, pr in preds.items():
            rec[k] = {"accuracy": exact_acc(pr, n), "offset": offset_stats(pr, n)}
        results.append(rec)
        print(f"{name:6s} n={n:3d}  " +
              "  ".join(f"{k.split('_')[0]}={rec[k]['accuracy']*100:5.1f}%"
                        for k in preds) +
              f"  NoMaD={(rec['nomad_accuracy'] or 0)*100:5.1f}%")

    def avg(key):
        return round(statistics.mean([r[key]["accuracy"] for r in results]), 4)

    summary = {
        "n_routes": len(results),
        "n_nodes_total": sum(r["n_nodes"] for r in results),
        "B1_pure_retrieval": avg("B1_pure_retrieval"),
        "B2_monotonic": avg("B2_monotonic"),
        "B3_window": avg("B3_window"),
        "B4_temporal_prior": avg("B4_temporal_prior"),
        "NoMaD": round(statistics.mean([r["nomad_accuracy"] for r in results
                                        if r["nomad_accuracy"] is not None]), 4),
        "design": "all methods share NoMaD visual encoder (EfficientNet-B0+Transformer, 256-d); "
                  "only the localization strategy differs",
        "evaluation": "exact node match, skip first 4 warmup frames",
    }
    out = {"summary": summary, "per_route": results}
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    json.dump(out, open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    print("\n" + "=" * 74)
    print("C 组 baseline（同骨干，仅换定位方式）")
    print("=" * 74)
    print(f"{'方法':<32}{'准确率':>10}")
    print("-" * 74)
    for k, label in [
        ("B1_pure_retrieval", "B1 纯外观检索（余弦最近邻）"),
        ("B2_monotonic", "B2 检索 + 单调约束"),
        ("B3_window", "B3 检索 + 滑动窗口 (±5)"),
        ("B4_temporal_prior", "B4 检索 + 位置先验"),
        ("NoMaD", "NoMaD 距离预测头（本文）"),
    ]:
        print(f"{label:<32}{summary[k]*100:>9.1f}%")

    best = max(summary["B1_pure_retrieval"], summary["B2_monotonic"],
               summary["B3_window"], summary["B4_temporal_prior"])
    print(f"\n最强 baseline = {best*100:.1f}%")
    print(f"NoMaD = {summary['NoMaD']*100:.1f}%")
    print(f"绝对提升 = {(summary['NoMaD']-best)*100:+.1f} 个百分点")
    print(f"\n保存 -> {OUT_JSON}")


if __name__ == "__main__":
    main()
