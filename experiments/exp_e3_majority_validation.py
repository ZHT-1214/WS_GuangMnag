# -*- coding: utf-8 -*-
"""关键验证：用多数投票作为真值，重算 E3 准确率。

背景：论文 §5.3.2 的 97.7% 是基于作者单人标注算的。
现在有 4 位独立标注者，且他们与作者的一致率只有 κ=0.24~0.40。
必须验证：换成"多数投票真值"后，E3 的结论是否依然成立。

如果稳健 → 论文可以理直气壮地报告 97.7%，并说明真值经多数投票复核
如果显著下降 → 必须修正论文数字
"""
import json
import os
from collections import Counter

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
ANNOT_V2 = {"A+": "A+.json", "B+": "B+.json", "C+": "C+.json", "D+": "D+.json"}
ANNOT_V1 = {"A": "A.json", "B": "B.json"}
ORIG = "labels_filled.json"
PRED = "yoso_predictions.json"
OUT = os.path.join(RESULTS_DIR, "e3_majority_validation.json")

ALIAS = {"ahead": "forward", "forward": "forward", "left": "left",
         "right": "right", "unknown": "unknown", "none": "unknown"}


def norm(v):
    if v is None:
        return "unknown"
    return ALIAS.get(str(v).strip().lower(), str(v).strip().lower())


def load(fn):
    p = os.path.join(BASE, fn)
    if not os.path.exists(p):
        return None
    d = json.load(open(p, encoding="utf-8"))
    if isinstance(d, dict) and "labels" in d:
        return {r["file"]: r for r in d["labels"]}
    return d


def main():
    print("=" * 82)
    print("E3 主结论稳健性验证：作者标注 vs 多数投票真值")
    print("=" * 82)

    orig = load(ORIG)
    v2 = {n: load(fn) for n, fn in ANNOT_V2.items() if load(fn)}
    v1 = {n: load(fn) for n, fn in ANNOT_V1.items() if load(fn)}

    # YOSO 预测与对齐后的真值：直接取 e3_obstacle_eval.json 的 all_records
    e3 = json.load(open(os.path.join(RESULTS_DIR, "e3_obstacle_eval.json"), encoding="utf-8"))
    recs = {r["file"]: r for r in e3["all_records"]}
    pred = {f: norm(r["pred_direction"]) for f, r in recs.items()}
    aligned_gt = {f: norm(r["gt_direction"]) for f, r in recs.items()}

    if not orig or not pred:
        raise SystemExit("缺少作者标注或 YOSO 预测")

    print(f"作者标注: {len(orig)}")
    print(f"v2 标注者: {list(v2.keys())}")
    print(f"v1 标注者: {list(v1.keys())}")
    print(f"YOSO 预测（已对齐）: {len(pred)}")

    def get_pred(f):
        return pred.get(f)

    def get_orig(f):
        return norm(orig[f].get("passable"))

    def majority(f, group):
        vals = [norm(group[n][f]["passable"]) for n in group if f in group[n]]
        if not vals:
            return None, 0, len(vals)
        c = Counter(vals)
        top, cnt = c.most_common(1)[0]
        return top, cnt, len(vals)

    files = sorted(f for f in pred if f in orig)

    print(f"\n可比对样本: {len(files)}")

    # ===== 1. 作者标注 vs 多数投票 =====
    print("\n" + "=" * 82)
    print("1. 作者真值 vs 各标注方案的一致情况")
    print("=" * 82)

    comparisons = {}
    for gname, group in (("v2-4人", v2), ("v1-2人", v1)):
        if not group:
            continue
        pairs = []
        for f in files:
            mv, cnt, tot = majority(f, group)
            if mv is None:
                continue
            pairs.append((get_orig(f), mv))
        agree = sum(1 for a, b in pairs if a == b) / len(pairs) if pairs else 0
        comparisons[gname] = {"n": len(pairs), "agree_with_author": round(agree, 4)}
        print(f"  {gname}: 作者与多数投票一致率 {agree*100:.1f}%（{len(pairs)} 张）")

    # ===== 2. 用不同真值重算 E3 =====
    print("\n" + "=" * 82)
    print("2. 用不同真值重算 E3 方向准确率")
    print("=" * 82)

    def evaluate(truth_fn, label, subset=None):
        fs = subset if subset else files
        correct = 0
        total = 0
        errors = []
        for f in fs:
            t = truth_fn(f)
            if t is None:
                continue
            p = get_pred(f)
            total += 1
            if p == t:
                correct += 1
            else:
                errors.append((f, t, p))
        acc = correct / total if total else 0
        print(f"\n  【{label}】n={total}, 正确 {correct}, 准确率 {acc*100:.1f}%")
        if errors:
            print(f"    错误样本 {len(errors)} 例:")
            for f, t, p in errors[:8]:
                print(f"      {f}: 真值={t:<8} 预测={p}")
            if len(errors) > 8:
                print(f"      ... 共 {len(errors)} 例")
        return {"label": label, "n": total, "correct": correct,
                "accuracy": round(acc, 4), "errors": errors}

    res = {}
    res["author"] = evaluate(lambda f: get_orig(f), "作者标注（论文原口径）")

    for gname, group in (("v2", v2), ("v1", v1)):
        if not group:
            continue
        # 全部样本用多数投票
        res[f"majority_{gname}"] = evaluate(
            lambda f, g=group: majority(f, g)[0], f"多数投票（{gname}）")

        # 只用在标注者间达成严格多数的样本
        unanimous = [f for f in files
                     if majority(f, group)[1] * 2 > majority(f, group)[2]]
        res[f"majority_{gname}_strict"] = evaluate(
            lambda f, g=group: majority(f, g)[0],
            f"多数投票-严格多数样本（{gname}）", subset=unanimous)

    # ===== 3. 对比表 =====
    print("\n" + "=" * 82)
    print("3. 汇总对比")
    print("=" * 82)
    print(f"{'真值口径':<38}{'样本数':>8}{'准确率':>10}{'相对作者':>12}")
    print("-" * 82)
    base = res["author"]["accuracy"]
    for k, v in res.items():
        delta = v["accuracy"] - base
        print(f"{v['label']:<38}{v['n']:>8}{v['accuracy']*100:>9.1f}%{delta*100:>+11.1f}pp")

    # ===== 4. 结论 =====
    print("\n" + "=" * 82)
    print("4. 结论")
    print("=" * 82)
    mv = res.get("majority_v2")
    if mv:
        diff = abs(mv["accuracy"] - base)
        print(f"  作者真值准确率      : {base*100:.1f}%")
        print(f"  多数投票真值准确率  : {mv['accuracy']*100:.1f}%")
        print(f"  差异                : {diff*100:.1f} 个百分点")
        if diff < 0.05:
            print(f"  ✓ 结论稳健：换真值口径后准确率变化 < 5pp，97.7% 的结论成立")
        elif diff < 0.10:
            print(f"  ⚠ 轻度敏感：变化 {diff*100:.1f}pp，需在论文中说明")
        else:
            print(f"  ✗ 结论不稳健：变化 {diff*100:.1f}pp，必须修正论文数字")

    out = {"author_baseline": res["author"],
           "majority_v2": res.get("majority_v2"),
           "majority_v2_strict": res.get("majority_v2_strict"),
           "majority_v1": res.get("majority_v1"),
           "author_vs_majority_agreement": comparisons,
           "all_results": {k: {kk: vv for kk, vv in v.items() if kk != "errors"}
                           for k, v in res.items()}}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\n保存 -> {OUT}")


if __name__ == "__main__":
    main()
