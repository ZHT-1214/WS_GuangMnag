# -*- coding: utf-8 -*-
"""C 组 baseline 对比：纯视觉检索 vs NoMaD 距离预测。

核心问题：如果不使用 NoMaD 的距离预测头，仅靠图像外观相似度（最近邻检索）
定位当前节点，准确率是多少？与 NoMaD 的 95.4% 相比差多少？

方法：
  1. 对每条路线的全部节点两两计算外观相似度（缩略图 1-MSE）
  2. 模拟"纯检索"定位：给定当前帧，取最相似的节点作为预测位置
  3. 统计定位准确率（预测节点 == 真实节点，允许 ±k 容差）
  4. 与 NoMaD 的节点跟踪准确率对比

输出：表 + 图
"""
import glob
import json
import os
import statistics

import numpy as np
from PIL import Image

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROUTES_DIR = os.path.join(BASE, "_素材", "routes")
NAV_RESULT = os.path.join(BASE, "实验", "results", "navigation_all.json")
OUT_JSON = os.path.join(BASE, "实验", "results", "baseline_retrieval.json")
OUT_FIG = os.path.join(BASE, "_素材", "figs")

# 与 navigation_all.json 中的路线名对应
ROUTE_MAP = {
    "1": "1",
    "2-2": "2-2",
    "1-2": "1-2",
    "2-6": "2-6",
    "1-3": "1-3",
    "2-7": "2-7",
}

FEAT_SIZE = (32, 24)   # 缩略图尺寸（与 §5.1.2 一致）


def load_feat(path):
    im = Image.open(path).convert("RGB").resize(FEAT_SIZE)
    return np.asarray(im, dtype=np.float32) / 255.0


def similarity(a, b):
    """1 - 归一化 MSE，范围 [0,1]。"""
    return max(0.0, 1.0 - float(np.mean((a - b) ** 2)))


def evaluate_route(route_name, route_dir):
    files = sorted([f for f in os.listdir(route_dir)
                    if f.lower().endswith((".jpg", ".jpeg", ".png"))
                    and f.split(".")[0].isdigit()],
                   key=lambda x: int(x.split(".")[0]))
    if len(files) < 5:
        return None
    feats = [load_feat(os.path.join(route_dir, f)) for f in files]
    n = len(feats)

    # 预计算相似度矩阵
    sim = np.zeros((n, n), dtype=np.float32)
    for i in range(n):
        for j in range(i, n):
            s = similarity(feats[i], feats[j])
            sim[i, j] = s
            sim[j, i] = s

    # 模拟纯检索定位：第 i 帧作为查询，排除自身后取最相似
    preds = []
    for i in range(n):
        row = sim[i].copy()
        row[i] = -1.0        # 排除自身（真实系统有 temporal 上下文，但纯检索无）
        preds.append(int(np.argmax(row)))

    # 准确率：严格（±0）与容差（±1, ±2）
    acc = {}
    for tol in (0, 1, 2, 3):
        ok = sum(1 for i, p in enumerate(preds) if abs(p - i) <= tol)
        acc[f"tol_{tol}"] = round(ok / n, 4)

    # 检索混淆：预测偏离真实位置的距离分布
    offsets = [p - i for i, p in enumerate(preds)]
    abs_offsets = [abs(o) for o in offsets]

    # 检索到的节点是否单调（能否用于跟踪）
    regressions = sum(1 for i in range(1, n) if preds[i] < preds[i - 1])

    return {
        "route": route_name,
        "n_nodes": n,
        "retrieval_accuracy": acc,
        "offset_abs_mean": round(statistics.mean(abs_offsets), 2),
        "offset_abs_median": round(statistics.median(abs_offsets), 2),
        "offset_abs_p90": round(sorted(abs_offsets)[int(len(abs_offsets) * 0.9)], 2),
        "regressions": regressions,
        "regression_rate": round(regressions / n, 4),
        "preds": preds,
    }


def main():
    nav = json.load(open(NAV_RESULT, encoding="utf-8"))
    # NoMaD 的逐路线准确率
    nomad_acc = {}
    for r in nav.get("routes", []):
        if "error" in r:
            continue
        name = r.get("name", r["map_id"][:8])
        nomad_acc[name] = {
            "accuracy": r["metrics"]["node_tracking_accuracy"],
            "regression_rate": r["metrics"]["regression_rate"],
            "n_nodes": r["n_nodes"],
        }

    results = []
    for name, dirname in ROUTE_MAP.items():
        d = os.path.join(ROUTES_DIR, dirname)
        if not os.path.isdir(d):
            print(f"跳过 {name}（目录不存在）")
            continue
        r = evaluate_route(name, d)
        if r:
            results.append(r)
            print(f"{name:6s} n={r['n_nodes']:3d}  "
                  f"检索准确率(±0)={r['retrieval_accuracy']['tol_0']*100:5.1f}%  "
                  f"(±2)={r['retrieval_accuracy']['tol_2']*100:5.1f}%  "
                  f"中位偏移={r['offset_abs_median']:.0f}")

    if not results:
        raise SystemExit("无可用路线")

    # 汇总
    def mean_of(key):
        vals = [r["retrieval_accuracy"][key] for r in results]
        return round(statistics.mean(vals), 4)

    summary = {
        "n_routes": len(results),
        "retrieval_accuracy_mean": {
            "tol_0": mean_of("tol_0"),
            "tol_1": mean_of("tol_1"),
            "tol_2": mean_of("tol_2"),
            "tol_3": mean_of("tol_3"),
        },
        "nomad_accuracy_mean": round(
            statistics.mean([v["accuracy"] for v in nomad_acc.values()]), 4)
        if nomad_acc else None,
        "nomad_regression_rate_mean": round(
            statistics.mean([v["regression_rate"] for v in nomad_acc.values()]), 4)
        if nomad_acc else None,
    }

    # 逐路线对比
    comparison = []
    for r in results:
        name = r["route"]
        nm = nomad_acc.get(name, {})
        comparison.append({
            "route": name,
            "n_nodes": r["n_nodes"],
            "retrieval_acc": r["retrieval_accuracy"]["tol_0"],
            "retrieval_acc_tol2": r["retrieval_accuracy"]["tol_2"],
            "nomad_acc": nm.get("accuracy"),
            "retrieval_offset_median": r["offset_abs_median"],
            "retrieval_regressions": r["regressions"],
            "nomad_regressions": nm.get("regression_rate"),
        })

    out = {
        "meta": {
            "method": "pure appearance retrieval (nearest neighbor) vs NoMaD distance prediction",
            "feature": f"RGB thumbnail {FEAT_SIZE[0]}x{FEAT_SIZE[1]}, similarity = 1 - normalized MSE",
            "note": "纯检索排除自身帧；真实系统可用时序上下文，此处为最保守估计",
        },
        "summary": summary,
        "per_route": comparison,
        "details": results,
    }
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    json.dump(out, open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    print("\n" + "=" * 68)
    print("C 组 baseline 对比结果")
    print("=" * 68)
    print(f"路线数: {summary['n_routes']}")
    print(f"\n纯外观检索准确率:")
    for k, v in summary["retrieval_accuracy_mean"].items():
        print(f"  {k}: {v*100:.1f}%")
    print(f"\nNoMaD 节点跟踪准确率: {summary['nomad_accuracy_mean']*100:.1f}%")

    print("\n逐路线对比:")
    print(f"{'路线':<8}{'节点':>5}{'纯检索':>9}{'检索±2':>9}{'NoMaD':>9}{'提升':>9}")
    print("-" * 68)
    for c in comparison:
        gain = (c["nomad_acc"] - c["retrieval_acc"]) * 100 if c["nomad_acc"] is not None else None
        print(f"{c['route']:<8}{c['n_nodes']:>5}"
              f"{c['retrieval_acc']*100:>8.1f}%{c['retrieval_acc_tol2']*100:>8.1f}%"
              f"{c['nomad_acc']*100:>8.1f}%" if c["nomad_acc"] is not None else "", end="")
        print(f"{gain:>+8.1f}%" if gain is not None else "")

    print(f"\n保存 -> {OUT_JSON}")


if __name__ == "__main__":
    main()
