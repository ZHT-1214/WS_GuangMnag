# -*- coding: utf-8 -*-
"""E3 避障准确率评测：分析人工校正后的标注结果。

重要：归一化 forward/ahead 别名（YOSO 输出 forward，标注工具按钮用 ahead）。
"""
import json
import os
from collections import Counter, defaultdict

# ===== 仓库路径定义（自动插入，适配 GitHub 仓库结构）=====
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)          # 仓库根目录
BASE_DIR = _REPO
RESULTS_DIR = os.path.join(_REPO, "data", "results")
LABELS_DIR = os.path.join(_REPO, "data", "labels")
ROUTES_DIR = os.path.join(_REPO, "data", "routes")
FIGS_DIR = os.path.join(_REPO, "figures")
# =========================================================


BASE = LABELS_DIR
LABELS = os.path.join(BASE, "labels_filled.json")
OUT = os.path.join(RESULTS_DIR, "e3_obstacle_eval.json")

# 方向别名归一化
ALIAS = {
    "forward": "ahead",
    "ahead": "ahead",
    "left": "left",
    "right": "right",
    "none": "none",
    "unknown": "unknown",
}


def norm(d):
    return ALIAS.get(str(d).strip().lower(), "unknown")


def main():
    data = json.load(open(LABELS, encoding="utf-8"))
    labels = data["labels"]
    print(f"总样本: {len(labels)}")
    print(f"工具报告: 已核对 {data['meta']['verified']}, 修改 {data['meta']['changed']}")

    # 逐条比对（归一化后）
    records = []
    for it in labels:
        gt = norm(it["passable"])
        pred = norm(it["yoso_passable"])
        gt_st = bool(it["stairs"])
        pred_st = bool(it["yoso_stairs"])
        records.append({
            "file": it["file"],
            "route": it["route"],
            "orig_index": it["orig_index"],
            "gt_direction": gt,
            "pred_direction": pred,
            "dir_correct": gt == pred,
            "gt_stairs": gt_st,
            "pred_stairs": pred_st,
            "stairs_correct": gt_st == pred_st,
            "raw_changed": it.get("changed", False),
            "real_dir_change": gt != pred,
            "real_stairs_change": gt_st != pred_st,
        })

    n = len(records)
    dir_correct = sum(1 for r in records if r["dir_correct"])
    st_correct = sum(1 for r in records if r["stairs_correct"])

    # 混淆矩阵
    cm = Counter((r["gt_direction"], r["pred_direction"]) for r in records)

    # 按类别
    by_gt = defaultdict(list)
    for r in records:
        by_gt[r["gt_direction"]].append(r["dir_correct"])
    per_class = {}
    for k, v in sorted(by_gt.items()):
        per_class[k] = {"n": len(v), "correct": sum(v),
                        "accuracy": round(sum(v) / len(v), 4)}

    # 按预测类别（精确率视角）
    by_pred = defaultdict(list)
    for r in records:
        by_pred[r["pred_direction"]].append(r["dir_correct"])
    per_pred = {}
    for k, v in sorted(by_pred.items()):
        per_pred[k] = {"n": len(v), "correct": sum(v),
                       "precision": round(sum(v) / len(v), 4)}

    # 楼梯指标
    tp = sum(1 for r in records if r["gt_stairs"] and r["pred_stairs"])
    fp = sum(1 for r in records if not r["gt_stairs"] and r["pred_stairs"])
    fn = sum(1 for r in records if r["gt_stairs"] and not r["pred_stairs"])
    tn = sum(1 for r in records if not r["gt_stairs"] and not r["pred_stairs"])

    # 真实错误样本
    errors = [r for r in records if not r["dir_correct"] or not r["stairs_correct"]]

    # 按路线
    by_route = defaultdict(lambda: {"n": 0, "dir_ok": 0, "st_ok": 0})
    for r in records:
        b = by_route[r["route"]]
        b["n"] += 1
        b["dir_ok"] += int(r["dir_correct"])
        b["st_ok"] += int(r["stairs_correct"])

    result = {
        "meta": {
            "n_samples": n,
            "source": "YOSO 预标注 + 人工逐张核对",
            "note": "已归一化 forward/ahead 别名（同一语义）",
            "tool_reported_changed": data["meta"]["changed"],
            "real_changes": sum(1 for r in records
                                if r["real_dir_change"] or r["real_stairs_change"]),
        },
        "direction": {
            "accuracy": round(dir_correct / n, 4),
            "correct": dir_correct,
            "total": n,
            "per_class": per_class,
            "per_predicted_class": per_pred,
            "confusion_matrix": {f"{g}->{p}": c for (g, p), c in sorted(cm.items())},
        },
        "stairs": {
            "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": round(tp / (tp + fp), 4) if (tp + fp) else None,
            "recall": round(tp / (tp + fn), 4) if (tp + fn) else None,
            "accuracy": round((tp + tn) / n, 4),
        },
        "per_route": {k: {**v,
                          "dir_accuracy": round(v["dir_ok"] / v["n"], 4),
                          "st_accuracy": round(v["st_ok"] / v["n"], 4)}
                      for k, v in sorted(by_route.items())},
        "errors": errors,
        "all_records": records,
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(result, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    print("\n" + "=" * 60)
    print("E3 避障通道准确率（归一化后）")
    print("=" * 60)
    print(f"方向准确率: {result['direction']['accuracy']*100:.1f}% "
          f"({dir_correct}/{n})")
    print(f"楼梯准确率: {result['stairs']['accuracy']*100:.1f}% ({st_correct}/{n})")
    print(f"真实修改数: {result['meta']['real_changes']}")

    print("\n--- 方向混淆矩阵（行=人工真值, 列=YOSO 预测）---")
    classes = ["ahead", "left", "right", "unknown", "none"]
    print(f"{'真值\\预测':<10}" + "".join(f"{c:>10}" for c in classes))
    for g in classes:
        row = [cm.get((g, p), 0) for p in classes]
        if sum(row) == 0:
            continue
        print(f"{g:<10}" + "".join(f"{v:>10}" for v in row))

    print("\n--- 按真值类别 ---")
    for k, v in per_class.items():
        print(f"  {k:10s}: {v['correct']:3d}/{v['n']:3d} = {v['accuracy']*100:5.1f}%")

    print("\n--- 按预测类别（精确率）---")
    for k, v in per_pred.items():
        print(f"  {k:10s}: {v['correct']:3d}/{v['n']:3d} = {v['precision']*100:5.1f}%")

    print("\n--- 楼梯检测 ---")
    print(f"  TP={tp} FP={fp} FN={fn} TN={tn}")
    print(f"  精确率={result['stairs']['precision']}  召回率={result['stairs']['recall']}")

    print("\n--- 按路线 ---")
    for k, v in result["per_route"].items():
        print(f"  {k:8s}: n={v['n']:2d}  方向={v['dir_accuracy']*100:5.1f}%  "
              f"楼梯={v['st_accuracy']*100:5.1f}%")

    print("\n--- 真实错误样本 ---")
    for e in errors:
        flags = []
        if not e["dir_correct"]:
            flags.append(f"方向 {e['gt_direction']}≠{e['pred_direction']}")
        if not e["stairs_correct"]:
            flags.append(f"楼梯 {e['gt_stairs']}≠{e['pred_stairs']}")
        print(f"  {e['file']} ({e['route']}#{e['orig_index']}): " + " | ".join(flags))

    print(f"\n保存 -> {OUT}")


if __name__ == "__main__":
    main()
