# -*- coding: utf-8 -*-
"""E3 的分层评测：区分"客观无歧义样本"与"边界样本"。

思路：
  87 张样本中，一部分是所有标注者都认同的（客观可判定），
  另一部分是标注者分歧的（本身就存在歧义）。

  对无歧义样本报告准确率（这是可信的），
  对边界样本单独报告（说明任务的主观性），
  而不是把两类混在一起算一个 97.7%。

判据：
  无歧义 = 4 位 v2 标注者 + 作者，全部一致
  多数共识 = ≥4/5 一致
  分歧 = 存在明显对立
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
OUT = os.path.join(RESULTS_DIR, "e3_stratified.json")

ALIAS = {"ahead": "forward", "forward": "forward", "left": "left",
         "right": "right", "unknown": "unknown", "none": "unknown"}


def norm(v):
    if v is None:
        return "unknown"
    return ALIAS.get(str(v).strip().lower(), str(v).strip().lower())


def main():
    # 作者标注
    labels = json.load(open(os.path.join(BASE, "labels_filled.json"), encoding="utf-8"))
    orig = {r["file"]: norm(r["passable"]) for r in labels["labels"]}

    # 独立标注
    v2 = {}
    for n, fn in [("A+", "A+.json"), ("B+", "B+.json"),
                  ("C+", "C+.json"), ("D+", "D+.json")]:
        p = os.path.join(BASE, fn)
        if os.path.exists(p):
            d = json.load(open(p, encoding="utf-8"))
            v2[n] = {r["file"]: norm(r["passable"]) for r in d["labels"]}

    # YOSO 预测（已对齐）
    e3 = json.load(open(os.path.join(RESULTS_DIR, "e3_obstacle_eval.json"), encoding="utf-8"))
    recs = {r["file"]: r for r in e3["all_records"]}
    pred = {f: norm(r["pred_direction"]) for f, r in recs.items()}

    files = sorted(f for f in pred if f in orig)
    print("=" * 84)
    print("E3 分层评测：客观样本 vs 边界样本")
    print("=" * 84)
    print(f"总样本: {len(files)}")
    print(f"标注者: 作者 + {list(v2.keys())}")

    # ===== 分层 =====
    # 每张图的 5 个判断（作者 + 4 位标注者）
    strata = {"unanimous": [], "majority": [], "divided": []}
    detail = []

    for f in files:
        votes = [orig[f]] + [v2[n][f] for n in v2 if f in v2[n]]
        c = Counter(votes)
        top, cnt = c.most_common(1)[0]
        n_votes = len(votes)
        ratio = cnt / n_votes

        if ratio == 1.0:
            key = "unanimous"
        elif ratio >= 0.8:      # 5 人中至少 4 人一致
            key = "majority"
        else:
            key = "divided"

        strata[key].append(f)
        detail.append({
            "file": f,
            "votes": dict(zip(["作者"] + [n for n in v2 if f in v2[n]], votes)),
            "majority": top,
            "consensus_ratio": round(ratio, 2),
            "stratum": key,
            "pred": pred[f],
            "author_label": orig[f],
            "correct_vs_author": pred[f] == orig[f],
            "correct_vs_majority": pred[f] == top,
        })

    for k, label in [("unanimous", "全体一致"), ("majority", "多数共识(≥80%)"),
                     ("divided", "存在分歧")]:
        print(f"  {label}: {len(strata[k])} 张 ({len(strata[k])/len(files)*100:.1f}%)")

    # ===== 各层准确率 =====
    print("\n" + "=" * 84)
    print("各层准确率")
    print("=" * 84)
    print(f"{'层次':<20}{'样本数':>8}{'vs作者':>12}{'vs多数投票':>14}")
    print("-" * 84)

    results = {}
    for k, label in [("unanimous", "全体一致"), ("majority", "多数共识(≥80%)"),
                     ("divided", "存在分歧"), ("all", "全部")]:
        fs = files if k == "all" else strata[k]
        if not fs:
            continue
        n = len(fs)
        # vs 作者
        acc_author = sum(1 for f in fs if pred[f] == orig[f]) / n
        # vs 多数投票
        sub = [d for d in detail if d["file"] in fs]
        acc_mv = sum(1 for d in sub if d["correct_vs_majority"]) / n
        results[k] = {"label": label, "n": n,
                      "acc_vs_author": round(acc_author, 4),
                      "acc_vs_majority": round(acc_mv, 4)}
        print(f"{label:<20}{n:>8}{acc_author*100:>11.1f}%{acc_mv*100:>13.1f}%")

    # ===== 边界样本详情 =====
    print("\n" + "=" * 84)
    print("存在分歧的样本详情")
    print("=" * 84)
    print(f"{'文件':<14}{'预测':<10}{'作者':<10}{'多数':<10}{'一致率':>8}  {'投票分布'}")
    print("-" * 84)
    for d in sorted(detail, key=lambda x: x["consensus_ratio"]):
        if d["stratum"] != "divided":
            continue
        print(f"{d['file']:<14}{d['pred']:<10}{d['author_label']:<10}"
              f"{d['majority']:<10}{d['consensus_ratio']*100:>7.0f}%  {d['votes']}")

    # ===== 结论 =====
    print("\n" + "=" * 84)
    print("结论与论文写法建议")
    print("=" * 84)
    u = results.get("unanimous")
    m = results.get("majority")
    dv = results.get("divided")

    if u:
        print(f"  1. 全体一致的 {u['n']} 张样本上，YOSO 准确率 {u['acc_vs_author']*100:.1f}%")
        print(f"     （这部分是客观可判定的，结论可信）")
    if m:
        print(f"  2. 多数共识的 {m['n']} 张上，准确率 {m['acc_vs_author']*100:.1f}%")
    if dv:
        print(f"  3. 存在分歧的 {dv['n']} 张上，准确率 {dv['acc_vs_author']*100:.1f}%")
        print(f"     这些样本本身就存在标注歧义，不应计入客观准确率")
        print(f"     建议在论文中：报告无歧义子集的准确率，并单独讨论分歧子集")

    # 无歧义子集 = unanimous + majority
    clean = strata["unanimous"] + strata["majority"]
    if clean:
        n = len(clean)
        acc_a = sum(1 for f in clean if pred[f] == orig[f]) / n
        acc_mv_ = sum(1 for d in detail if d["file"] in clean and d["correct_vs_majority"]) / n
        print(f"\n  推荐口径：「无歧义子集」(全体一致+多数共识) n={n}")
        print(f"    vs 作者标注准确率: {acc_a*100:.1f}%")
        print(f"    vs 多数投票准确率: {acc_mv_*100:.1f}%")
        results["clean"] = {"label": "无歧义子集", "n": n,
                            "acc_vs_author": round(acc_a, 4),
                            "acc_vs_majority": round(acc_mv_, 4)}

    out = {"strata": {k: len(v) for k, v in strata.items()},
           "results": results,
           "detail": detail,
           "meta": {"n_items": len(files), "annotators": ["作者"] + list(v2.keys())}}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\n保存 -> {OUT}")


if __name__ == "__main__":
    main()
