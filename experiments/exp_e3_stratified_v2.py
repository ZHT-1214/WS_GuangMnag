# -*- coding: utf-8 -*-
"""E3 分层评测 v2（修正分层逻辑）。

v1 的缺陷：用"5 人（作者+4标注者）的一致率"分层，导致"作者是少数派"的样本
被归入"多数共识"，产生"vs作者100% 但 vs多数投票65.6%"的矛盾。

v2 正确做法：以**独立标注者**（4 人，不含作者）的共识度分层，
再分别看作者与多数投票的位置。这样才能分离：
  - 任务本身的歧义（标注者之间不一致）
  - 作者的个人偏差（标注者一致但作者不同）

分层定义：
  L1 全体一致   : 4 位独立标注者 + 作者，5 人完全相同
  L2 标注者共识 : 4 位独立标注者全部相同，但作者不同（作者偏差）
  L3 标注者多数 : 4 位标注者中 3:1，取多数
  L4 高度分歧   : 4 位标注者 2:2
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
OUT = os.path.join(RESULTS_DIR, "e3_stratified_v2.json")

ALIAS = {"ahead": "forward", "forward": "forward", "left": "left",
         "right": "right", "unknown": "unknown", "none": "unknown"}


def norm(v):
    if v is None:
        return "unknown"
    return ALIAS.get(str(v).strip().lower(), str(v).strip().lower())


def main():
    labels = json.load(open(os.path.join(BASE, "labels_filled.json"), encoding="utf-8"))
    orig = {r["file"]: norm(r["passable"]) for r in labels["labels"]}

    v2 = {}
    for n, fn in [("A+", "A+.json"), ("B+", "B+.json"),
                  ("C+", "C+.json"), ("D+", "D+.json")]:
        p = os.path.join(BASE, fn)
        if os.path.exists(p):
            d = json.load(open(p, encoding="utf-8"))
            v2[n] = {r["file"]: norm(r["passable"]) for r in d["labels"]}

    e3 = json.load(open(os.path.join(RESULTS_DIR, "e3_obstacle_eval.json"), encoding="utf-8"))
    pred = {r["file"]: norm(r["pred_direction"]) for r in e3["all_records"]}

    files = sorted(f for f in pred if f in orig and all(f in v2[n] for n in v2))
    print("=" * 86)
    print("E3 分层评测 v2（以独立标注者共识度分层）")
    print("=" * 86)
    print(f"总样本: {len(files)}")
    print(f"独立标注者: {list(v2.keys())}")
    print(f"作者作为参照（不参与分层）")

    strata = {"L1_unanimous": [], "L2_author_odd": [], "L3_majority": [], "L4_divided": []}
    detail = []

    for f in files:
        indep = [v2[n][f] for n in v2]
        c = Counter(indep)
        top, cnt = c.most_common(1)[0]
        n_ind = len(indep)

        if cnt == n_ind:
            # 4 位标注者全一致
            if orig[f] == top:
                key = "L1_unanimous"
            else:
                key = "L2_author_odd"
        elif cnt == n_ind - 1:      # 3:1
            key = "L3_majority"
        else:                        # 2:2
            key = "L4_divided"

        strata[key].append(f)
        detail.append({
            "file": f,
            "author": orig[f],
            "indep_votes": dict(zip(list(v2.keys()), indep)),
            "indep_majority": top,
            "indep_consensus": f"{cnt}/{n_ind}",
            "author_matches_majority": orig[f] == top,
            "pred": pred[f],
            "correct_vs_author": pred[f] == orig[f],
            "correct_vs_majority": pred[f] == top,
            "stratum": key,
        })

    labels_map = {
        "L1_unanimous": "L1 全体一致（含作者）",
        "L2_author_odd": "L2 标注者一致但作者不同",
        "L3_majority": "L3 标注者 3:1 多数",
        "L4_divided": "L4 标注者 2:2 高度分歧",
    }
    print("\n" + "=" * 86)
    print("分层结果")
    print("=" * 86)
    for k in ("L1_unanimous", "L2_author_odd", "L3_majority", "L4_divided"):
        n = len(strata[k])
        print(f"  {labels_map[k]:<28} {n:>3} 张 ({n/len(files)*100:>5.1f}%)")

    # ===== 各层准确率 =====
    print("\n" + "=" * 86)
    print("各层 YOSO 准确率")
    print("=" * 86)
    print(f"{'层次':<32}{'样本':>5}{'vs作者':>10}{'vs标注者多数':>14}")
    print("-" * 86)

    results = {}
    for k in ("L1_unanimous", "L2_author_odd", "L3_majority", "L4_divided", "all"):
        fs = files if k == "all" else strata[k]
        if not fs:
            continue
        n = len(fs)
        sub = [d for d in detail if d["file"] in fs]
        a = sum(1 for d in sub if d["correct_vs_author"]) / n
        m = sum(1 for d in sub if d["correct_vs_majority"]) / n
        key = "全部" if k == "all" else labels_map[k]
        results[k] = {"label": key, "n": n,
                      "acc_vs_author": round(a, 4),
                      "acc_vs_indep_majority": round(m, 4)}
        print(f"{key:<32}{n:>5}{a*100:>9.1f}%{m*100:>13.1f}%")

    # ===== L2：作者偏差的具体案例 =====
    print("\n" + "=" * 86)
    print("L2 案例：4 位标注者一致，但作者标注不同")
    print("=" * 86)
    if strata["L2_author_odd"]:
        print(f"{'文件':<14}{'作者':<10}{'标注者一致':<12}{'YOSO':<10}{'谁对'}")
        print("-" * 86)
        for d in detail:
            if d["stratum"] != "L2_author_odd":
                continue
            who = "标注者" if d["pred"] == d["indep_majority"] else ("作者" if d["pred"] == d["author"] else "都不是")
            print(f"{d['file']:<14}{d['author']:<10}{d['indep_majority']:<12}"
                  f"{d['pred']:<10}{who}")
        print(f"\n  在 {len(strata['L2_author_odd'])} 例中，YOSO 与标注者一致 "
              f"{sum(1 for d in detail if d['stratum']=='L2_author_odd' and d['correct_vs_majority'])} 例，"
              f"与作者一致 {sum(1 for d in detail if d['stratum']=='L2_author_odd' and d['correct_vs_author'])} 例")
    else:
        print("  无此类样本")

    # ===== L4：高度分歧 =====
    print("\n" + "=" * 86)
    print("L4 案例：标注者 2:2 分歧（任务本身的歧义）")
    print("=" * 86)
    if strata["L4_divided"]:
        for d in detail:
            if d["stratum"] != "L4_divided":
                continue
            print(f"  {d['file']}: 作者={d['author']:<9} 预测={d['pred']:<9} {d['indep_votes']}")
    else:
        print("  无此类样本")

    # ===== 推荐口径 =====
    print("\n" + "=" * 86)
    print("推荐报告口径")
    print("=" * 86)
    # 客观可信子集 = L1 + L3（标注者有多数共识的）
    reliable = strata["L1_unanimous"] + strata["L3_majority"]
    if reliable:
        n = len(reliable)
        sub = [d for d in detail if d["file"] in reliable]
        a = sum(1 for d in sub if d["correct_vs_author"]) / n
        m = sum(1 for d in sub if d["correct_vs_majority"]) / n
        print(f"  「标注者有共识」子集（L1+L3）: n={n}")
        print(f"    vs 作者标注   : {a*100:.1f}%")
        print(f"    vs 标注者多数 : {m*100:.1f}%")
        results["reliable"] = {"label": "L1+L3 有共识子集", "n": n,
                               "acc_vs_author": round(a, 4),
                               "acc_vs_indep_majority": round(m, 4)}

    # 全部标注者一致子集（最严格）
    if strata["L1_unanimous"]:
        n = len(strata["L1_unanimous"])
        sub = [d for d in detail if d["stratum"] == "L1_unanimous"]
        a = sum(1 for d in sub if d["correct_vs_author"]) / n
        print(f"  「5 人全体一致」子集: n={n}, 准确率 {a*100:.1f}%")

    out = {"strata": {k: len(v) for k, v in strata.items()},
           "results": results, "detail": detail,
           "meta": {"n_items": len(files), "annotators": list(v2.keys())}}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\n保存 -> {OUT}")


if __name__ == "__main__":
    main()
