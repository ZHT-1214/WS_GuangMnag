# -*- coding: utf-8 -*-
"""确认锚定效应：作者是否系统性地"不修正"YOSO 的错误。

核心检验：
  1. L2 的 11 例是否都标记为 changed=false（未修改）
  2. 在"YOSO 与标注者多数不一致"的样本中，作者修正了 YOSO 吗？
  3. 计算作者修正率，与独立标注者的判断对比
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
OUT = os.path.join(RESULTS_DIR, "anchor_verification.json")

ALIAS = {"ahead": "forward", "forward": "forward", "left": "left",
         "right": "right", "unknown": "unknown", "none": "unknown"}


def norm(v):
    if v is None:
        return "unknown"
    return ALIAS.get(str(v).strip().lower(), str(v).strip().lower())


def main():
    labels = json.load(open(os.path.join(BASE, "labels_filled.json"), encoding="utf-8"))
    orig = {r["file"]: r for r in labels["labels"]}

    v2 = {}
    for n, fn in [("A+", "A+.json"), ("B+", "B+.json"),
                  ("C+", "C+.json"), ("D+", "D+.json")]:
        p = os.path.join(BASE, fn)
        if os.path.exists(p):
            d = json.load(open(p, encoding="utf-8"))
            v2[n] = {r["file"]: norm(r["passable"]) for r in d["labels"]}

    e3 = json.load(open(os.path.join(RESULTS_DIR, "e3_obstacle_eval.json"), encoding="utf-8"))
    recs = {r["file"]: r for r in e3["all_records"]}

    files = sorted(f for f in orig if all(f in v2[n] for n in v2))

    print("=" * 86)
    print("锚定效应核实")
    print("=" * 86)

    # ===== 1. YOSO 判错时，作者修正了吗？ =====
    print("\n" + "=" * 86)
    print("1. YOSO 与标注者多数不一致的样本 → 作者是否修正？")
    print("=" * 86)

    yoso_wrong = []       # YOSO != 标注者多数
    for f in files:
        y = norm(orig[f]["yoso_passable"])
        vals = [v2[n][f] for n in v2]
        mv = Counter(vals).most_common(1)[0][0]
        a = norm(orig[f]["passable"])
        ch = orig[f].get("changed", False)
        if y != mv:
            yoso_wrong.append({"file": f, "yoso": y, "author": a,
                               "majority": mv, "changed_flag": ch,
                               "author_fixed": a != y,
                               "author_matches_yoso": a == y})

    print(f"  YOSO 与标注者多数不一致的样本: {len(yoso_wrong)} 个")
    fixed = sum(1 for r in yoso_wrong if r["author_fixed"])
    not_fixed = sum(1 for r in yoso_wrong if not r["author_fixed"])
    print(f"  作者修正了 YOSO: {fixed} 个 ({fixed/len(yoso_wrong)*100:.1f}%)")
    print(f"  作者保留了 YOSO: {not_fixed} 个 ({not_fixed/len(yoso_wrong)*100:.1f}%)")

    print(f"\n{'文件':<14}{'YOSO':<10}{'标注者多数':<12}{'作者':<10}{'changed':<9}{'作者是否修正'}")
    print("-" * 86)
    for r in yoso_wrong:
        print(f"{r['file']:<14}{r['yoso']:<10}{r['majority']:<12}{r['author']:<10}"
              f"{str(r['changed_flag']):<9}"
              f"{'✓修正' if r['author_fixed'] else '✗保留YOSO'}")

    # ===== 2. L2 样本的 changed 标记 =====
    print("\n" + "=" * 86)
    print("2. L2 样本（4 标注者一致但作者不同）的 changed 标记")
    print("=" * 86)
    l2 = []
    for f in files:
        vals = [v2[n][f] for n in v2]
        if len(set(vals)) == 1:      # 4 人一致
            mv = vals[0]
            if orig[f]["passable"] != mv and norm(orig[f]["passable"]) != mv:
                l2.append({"file": f, "author": norm(orig[f]["passable"]),
                           "majority": mv, "yoso": norm(orig[f]["yoso_passable"]),
                           "changed": orig[f].get("changed", False)})
    print(f"  样本数: {len(l2)}")
    print(f"{'文件':<14}{'YOSO':<10}{'标注者一致':<12}{'作者':<10}{'changed':<9}{'作者=YOSO?'}")
    print("-" * 86)
    n_match = 0
    for r in l2:
        same = r["author"] == r["yoso"]
        if same:
            n_match += 1
        print(f"{r['file']:<14}{r['yoso']:<10}{r['majority']:<12}{r['author']:<10}"
              f"{str(r['changed']):<9}{'✓' if same else '✗'}")
    print(f"\n  其中作者标注 == YOSO 的: {n_match}/{len(l2)}")

    # ===== 3. 关键统计：作者修正率 vs 应修正率 =====
    print("\n" + "=" * 86)
    print("3. 核心统计")
    print("=" * 86)
    print(f"  YOSO 与标注者多数不一致: {len(yoso_wrong)} 例（这些地方 YOSO 可能是错的）")
    print(f"  作者实际修正: {fixed} 例")
    print(f"  作者修正率: {fixed/len(yoso_wrong)*100:.1f}%")
    print()
    print(f"  作者与 YOSO 一致率: {sum(1 for f in files if norm(orig[f]['passable'])==norm(orig[f]['yoso_passable']))}/{len(files)}")
    print(f"  标注者多数与 YOSO 一致率: "
          f"{sum(1 for f in files if Counter([v2[n][f] for n in v2]).most_common(1)[0][0]==norm(orig[f]['yoso_passable']))}/{len(files)}")

    # 二项检验：如果作者独立标注，11 次全巧合的概率
    print("\n" + "=" * 86)
    print("4. 统计显著性")
    print("=" * 86)
    # 在 L2 的 11 例中，作者全部与 YOSO 一致
    # 若作者独立标注，按标注者的类别分布，随机碰上的概率
    if l2:
        k = len(l2)
        # 标注者在这些样本上的一致答案与 YOSO 不同的比例
        # 用标注者整体与 YOSO 的一致率作为零假设下的匹配概率
        p_yoso_match = sum(1 for f in files
                           if Counter([v2[n][f] for n in v2]).most_common(1)[0][0]
                           == norm(orig[f]["yoso_passable"])) / len(files)
        p_all = p_yoso_match ** k
        print(f"  标注者与 YOSO 的整体一致率: {p_yoso_match*100:.1f}%")
        print(f"  若作者独立标注，{k} 例全部恰好等于 YOSO 的概率: {p_all:.2e}")
        print(f"  → {'极不可能（<0.001），强烈提示锚定' if p_all < 0.001 else '在随机范围内'}")

    out = {"n_yoso_wrong": len(yoso_wrong),
           "author_fixed": fixed,
           "author_kept_yoso": not_fixed,
           "fix_rate": round(fixed/len(yoso_wrong), 4) if yoso_wrong else None,
           "l2_samples": l2,
           "l2_author_matches_yoso": n_match,
           "details": yoso_wrong}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\n保存 -> {OUT}")


if __name__ == "__main__":
    main()
