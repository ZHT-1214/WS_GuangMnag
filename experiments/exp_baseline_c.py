# -*- coding: utf-8 -*-
"""C 组 baseline（最终版）：同骨干、多容差口径的公平对比。

修正：
  1. 报告多容差（±0/±1/±2/±3/±5）准确率，避免"±0 恒为 0"造成的误导
  2. 增加"检索 + 全局序列对齐（DTW 式单调匹配）"作为最强 baseline
  3. 明确说明：所有方法共享 NoMaD 编码器，差异仅在定位策略

关键结论：NoMaD 的视觉编码器本身不具备地点判别力（相邻/远端相似度 gap 仅 0.02），
真正的节点定位能力来自距离预测头（DenseNetwork）。
"""
import json
import os
import statistics

import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FEAT_DIR = os.path.join(BASE, "实验", "results", "nomad_features")
NAV_RESULT = os.path.join(BASE, "实验", "results", "navigation_all.json")
OUT_JSON = os.path.join(BASE, "实验", "results", "baseline_c.json")

ROUTE_MAP = {"1": "route_1", "2-2": "route_2-2", "1-2": "route_1-2",
             "2-6": "route_2-6", "1-3": "route_1-3", "2-7": "route_2-7"}
WARMUP = 4


def l2n(x):
    return x / np.maximum(np.linalg.norm(x, axis=1, keepdims=True), 1e-8)


def b1_pure(sm, n):
    out = []
    for i in range(n):
        row = sm[i].copy()
        row[i] = -9
        out.append(int(np.argmax(row)))
    return out


def b2_monotonic(sm, n):
    """检索 + 单调约束（预测位置不得回退）。"""
    out, last = [], -1
    for i in range(n):
        row = sm[i].copy()
        row[i] = -9
        row[:last + 1] = -9
        out.append(int(np.argmax(row)) if row.max() > -9 else min(last + 1, n - 1))
        last = out[-1]
    return out


def b3_dtw(sm, n):
    """最强 baseline：全局序列对齐（DTW），把检索结果强制映射为单调递增序列。

    这是视觉示教-重复（VT&R）系统的常见做法：先算相似度矩阵，
    再用动态规划找一条单调最优路径。
    """
    NEG = -1e6
    # dp[i][j] = 前 i 帧匹配到前 j 个节点的最大累计相似度
    dp = np.full((n, n), NEG, dtype=np.float64)
    back = np.zeros((n, n), dtype=np.int32)
    for j in range(n):
        dp[0, j] = sm[0, j]
    for i in range(1, n):
        # 单调：第 i 帧匹配的节点索引 >= 第 i-1 帧
        best_prev = NEG
        best_j = 0
        for j in range(n):
            if dp[i - 1, j] > best_prev:
                best_prev = dp[i - 1, j]
                best_j = j
            if best_prev > NEG / 2:
                dp[i, j] = best_prev + sm[i, j]
                back[i, j] = best_j
    # 回溯
    j = int(np.argmax(dp[n - 1]))
    path = [0] * n
    for i in range(n - 1, -1, -1):
        path[i] = j
        if i > 0:
            j = back[i, j]
    return path


def acc_at_tol(preds, n, tol, skip=WARMUP):
    if n <= skip:
        return 0.0
    ok = sum(1 for i in range(skip, n) if abs(preds[i] - i) <= tol)
    return round(ok / (n - skip), 4)


def main():
    nav = json.load(open(NAV_RESULT, encoding="utf-8"))
    nomad = {}
    for r in nav.get("routes", []):
        if "error" in r:
            continue
        nm = r.get("name", r["map_id"][:8])
        nomad[nm] = r["metrics"]["node_tracking_accuracy"]

    per_route = []
    for name, fname in ROUTE_MAP.items():
        p = os.path.join(FEAT_DIR, f"{fname}.npy")
        if not os.path.exists(p):
            continue
        feats = np.load(p)
        n = feats.shape[0]
        sm = l2n(feats) @ l2n(feats).T

        methods = {
            "B1_pure_retrieval": b1_pure(sm, n),
            "B2_monotonic": b2_monotonic(sm, n),
            "B3_dtw_alignment": b3_dtw(sm, n),
        }
        rec = {"route": name, "n_nodes": n,
               "nomad_accuracy": nomad.get(name),
               "gap": None}
        # 计算 gap
        adj = [sm[i, i + 1] for i in range(n - 1)]
        far = [sm[i, j] for i in range(n) for j in range(i + 3, n)]
        if adj and far:
            rec["gap"] = round(float(np.mean(adj) - np.mean(far)), 4)

        for k, pr in methods.items():
            rec[k] = {f"tol_{t}": acc_at_tol(pr, n, t) for t in (0, 1, 2, 3, 5)}
            offs = [abs(pr[i] - i) for i in range(WARMUP, n)]
            rec[k]["offset_median"] = round(statistics.median(offs), 1) if offs else 0
        per_route.append(rec)
        print(f"{name:6s} n={n:3d} gap={rec['gap']:.4f}  "
              f"B1±2={rec['B1_pure_retrieval']['tol_2']*100:5.1f}%  "
              f"B3±2={rec['B3_dtw_alignment']['tol_2']*100:5.1f}%  "
              f"B3±0={rec['B3_dtw_alignment']['tol_0']*100:5.1f}%  "
              f"NoMaD={(rec['nomad_accuracy'] or 0)*100:5.1f}%")

    def avg(key, tol):
        return round(statistics.mean([r[key][f"tol_{tol}"] for r in per_route]), 4)

    summary = {
        "n_routes": len(per_route),
        "n_nodes_total": sum(r["n_nodes"] for r in per_route),
        "design": "all methods share NoMaD visual encoder (EfficientNet-B0+Transformer, 256-d)",
        "evaluation": f"exact/near node match, skip first {WARMUP} warmup frames",
        "B1_pure_retrieval": {f"tol_{t}": avg("B1_pure_retrieval", t) for t in (0, 1, 2, 3, 5)},
        "B2_monotonic": {f"tol_{t}": avg("B2_monotonic", t) for t in (0, 1, 2, 3, 5)},
        "B3_dtw_alignment": {f"tol_{t}": avg("B3_dtw_alignment", t) for t in (0, 1, 2, 3, 5)},
        "NoMaD": round(statistics.mean([r["nomad_accuracy"] for r in per_route
                                        if r["nomad_accuracy"] is not None]), 4),
        "gap_mean": round(statistics.mean([r["gap"] for r in per_route if r["gap"]]), 4),
    }
    def _conv(o):
        if isinstance(o, (np.integer,)):
            return int(o)
        if isinstance(o, (np.floating,)):
            return float(o)
        raise TypeError(type(o))

    json.dump({"summary": summary, "per_route": per_route},
              open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False,
              indent=2, default=_conv)

    print("\n" + "=" * 82)
    print("C 组 baseline（同骨干，多容差口径）")
    print("=" * 82)
    print(f"{'方法':<30}{'±0':>8}{'±1':>8}{'±2':>8}{'±3':>8}{'±5':>8}")
    print("-" * 82)
    for k, label in [("B1_pure_retrieval", "B1 纯外观检索"),
                     ("B2_monotonic", "B2 检索+单调约束"),
                     ("B3_dtw_alignment", "B3 检索+DTW 全局对齐")]:
        row = summary[k]
        print(f"{label:<30}" + "".join(f"{row[f'tol_{t}']*100:>7.1f}%" for t in (0, 1, 2, 3, 5)))
    print(f"{'NoMaD 距离预测（本文）':<30}{summary['NoMaD']*100:>7.1f}%"
          f"{'-':>8}{'-':>8}{'-':>8}{'-':>8}")

    print(f"\n特征区分度 gap 均值: {summary['gap_mean']:.4f}（相邻 vs 远端相似度差）")
    print(f"\n保存 -> {OUT_JSON}")


if __name__ == "__main__":
    main()
