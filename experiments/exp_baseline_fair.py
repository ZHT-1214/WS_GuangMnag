# -*- coding: utf-8 -*-
"""C 组 baseline 对比（公平版）：三种定位方法的同口径比较。

问题：上一版直接对比"纯检索 ±0"与"NoMaD 精确匹配"不公平，因为：
  - 纯检索排除自身后，最近邻必然是相邻帧，±0 准确率恒为 0
  - NoMaD 有时序上下文（4 帧）与距离预测头，能精确定位

本版构建三个同口径的 baseline：
  B1. 纯外观检索（无约束）：查询帧取最相似节点，排除自身
  B2. 纯外观检索 + 时序单调约束（真实 VPR 系统的常见做法）
  B3. 纯外观检索 + 滑动窗口（限制在上一位置 ±W 内搜索）
  Proposed. NoMaD 距离预测（实测数据）

评测口径统一为：预测节点 == 真实节点（精确匹配）
"""
import json
import os
import statistics

import numpy as np
from PIL import Image

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROUTES_DIR = os.path.join(BASE, "_素材", "routes")
NAV_RESULT = os.path.join(BASE, "实验", "results", "navigation_all.json")
OUT_JSON = os.path.join(BASE, "实验", "results", "baseline_fair.json")

ROUTE_MAP = {"1": "1", "2-2": "2-2", "1-2": "1-2", "2-6": "2-6", "1-3": "1-3", "2-7": "2-7"}
FEAT_SIZE = (32, 24)
WINDOW = 5   # 滑动窗口半径


def load_feat(path):
    im = Image.open(path).convert("RGB").resize(FEAT_SIZE)
    return np.asarray(im, dtype=np.float32) / 255.0


def sim(a, b):
    return max(0.0, 1.0 - float(np.mean((a - b) ** 2)))


def build_sim_matrix(feats):
    n = len(feats)
    m = np.zeros((n, n), dtype=np.float32)
    for i in range(n):
        for j in range(i, n):
            s = sim(feats[i], feats[j])
            m[i, j] = s
            m[j, i] = s
    return m


def baseline_pure_retrieval(sim, n):
    """B1: 纯检索，排除自身。"""
    preds = []
    for i in range(n):
        row = sim[i].copy()
        row[i] = -1
        preds.append(int(np.argmax(row)))
    return preds


def baseline_monotonic(sim, n):
    """B2: 纯检索 + 单调约束（预测位置不得回退）。"""
    preds = []
    last = -1
    for i in range(n):
        row = sim[i].copy()
        row[i] = -1
        # 只在 last 及之后搜索（禁止回退）
        row[:last + 1] = -1
        if row.max() <= 0:
            preds.append(min(last + 1, n - 1))
        else:
            preds.append(int(np.argmax(row)))
        last = preds[-1]
    return preds


def baseline_window(sim, n, w=WINDOW):
    """B3: 纯检索 + 滑动窗口（在上一次位置 ±w 内搜索）。"""
    preds = []
    last = 0
    for i in range(n):
        lo = max(0, last - w)
        hi = min(n, last + w + 1)
        row = sim[i].copy()
        # 窗口外与自身置为 -1
        mask = np.full(n, -1.0, dtype=np.float32)
        mask[lo:hi] = row[lo:hi]
        mask[i] = -1 if lo <= i < hi else mask[i]
        if mask.max() <= 0:
            preds.append(last)
        else:
            preds.append(int(np.argmax(mask)))
        last = preds[-1]
    return preds


def exact_accuracy(preds, n, skip_first=4):
    """精确匹配准确率（跳过前 4 帧，与 NoMaD 的 warmup 对齐）。"""
    ok = sum(1 for i in range(skip_first, n) if preds[i] == i)
    total = n - skip_first
    return round(ok / total, 4) if total > 0 else 0.0


def evaluate_route(name, d):
    files = sorted([f for f in os.listdir(d)
                    if f.lower().endswith((".jpg", ".jpeg", ".png"))
                    and f.split(".")[0].isdigit()],
                   key=lambda x: int(x.split(".")[0]))
    n = len(files)
    if n < 10:
        return None
    feats = [load_feat(os.path.join(d, f)) for f in files]
    sm = build_sim_matrix(feats)

    b1 = baseline_pure_retrieval(sm, n)
    b2 = baseline_monotonic(sm, n)
    b3 = baseline_window(sm, n)

    def offset_stats(preds):
        offs = [abs(p - i) for i, p in enumerate(preds[4:], start=4)]
        return {
            "median": round(statistics.median(offs), 1),
            "mean": round(statistics.mean(offs), 2),
            "p90": round(sorted(offs)[int(len(offs) * 0.9)], 1),
        }

    return {
        "route": name,
        "n_nodes": n,
        "B1_pure_retrieval": {
            "accuracy": exact_accuracy(b1, n),
            "offset": offset_stats(b1),
        },
        "B2_monotonic": {
            "accuracy": exact_accuracy(b2, n),
            "offset": offset_stats(b2),
        },
        "B3_window": {
            "accuracy": exact_accuracy(b3, n),
            "offset": offset_stats(b3),
        },
    }


def main():
    nav = json.load(open(NAV_RESULT, encoding="utf-8"))
    nomad = {}
    for r in nav.get("routes", []):
        if "error" in r:
            continue
        nm = r.get("name", r["map_id"][:8])
        nomad[nm] = r["metrics"]["node_tracking_accuracy"]

    results = []
    for name, dn in ROUTE_MAP.items():
        d = os.path.join(ROUTES_DIR, dn)
        if not os.path.isdir(d):
            continue
        r = evaluate_route(name, d)
        if r:
            r["nomad_accuracy"] = nomad.get(name)
            results.append(r)

    if not results:
        raise SystemExit("无可用路线")

    def avg(key):
        vals = [r[key]["accuracy"] for r in results]
        return round(statistics.mean(vals), 4)

    summary = {
        "n_routes": len(results),
        "n_nodes_total": sum(r["n_nodes"] for r in results),
        "B1_pure_retrieval_acc": avg("B1_pure_retrieval"),
        "B2_monotonic_acc": avg("B2_monotonic"),
        "B3_window_acc": avg("B3_window"),
        "NoMaD_acc": round(statistics.mean([r["nomad_accuracy"] for r in results
                                            if r["nomad_accuracy"] is not None]), 4),
        "evaluation": "exact node match, skipping first 4 warmup frames",
    }

    out = {"summary": summary, "per_route": results}
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    json.dump(out, open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    print("=" * 78)
    print("C 组 baseline 对比（同口径：精确节点匹配，跳过前 4 帧 warmup）")
    print("=" * 78)
    print(f"\n{'方法':<28}{'准确率':>10}{'说明':>30}")
    print("-" * 78)
    rows = [
        ("B1 纯外观检索（无约束）", summary["B1_pure_retrieval_acc"], "最近邻，排除自身"),
        ("B2 纯检索+单调约束", summary["B2_monotonic_acc"], "禁止位置回退"),
        ("B3 纯检索+滑动窗口(±5)", summary["B3_window_acc"], "限制搜索范围"),
        ("NoMaD 距离预测（本文）", summary["NoMaD_acc"], "实测，含 4 帧上下文"),
    ]
    for name, v, note in rows:
        print(f"{name:<28}{v*100:>9.1f}%{note:>30}")

    print(f"\n逐路线:")
    print(f"{'路线':<7}{'节点':>5}{'B1':>8}{'B2':>8}{'B3':>8}{'NoMaD':>9}")
    print("-" * 50)
    for r in results:
        print(f"{r['route']:<7}{r['n_nodes']:>5}"
              f"{r['B1_pure_retrieval']['accuracy']*100:>7.1f}%"
              f"{r['B2_monotonic']['accuracy']*100:>7.1f}%"
              f"{r['B3_window']['accuracy']*100:>7.1f}%"
              f"{(r['nomad_accuracy'] or 0)*100:>8.1f}%")

    print(f"\n提升幅度（NoMaD vs 最强 baseline）:")
    best_baseline = max(summary["B1_pure_retrieval_acc"],
                        summary["B2_monotonic_acc"],
                        summary["B3_window_acc"])
    print(f"  最强 baseline = {best_baseline*100:.1f}%")
    print(f"  NoMaD = {summary['NoMaD_acc']*100:.1f}%")
    print(f"  绝对提升 = {(summary['NoMaD_acc']-best_baseline)*100:+.1f} 个百分点")
    print(f"\n保存 -> {OUT_JSON}")


if __name__ == "__main__":
    main()
