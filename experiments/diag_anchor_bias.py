# -*- coding: utf-8 -*-
"""诊断：作者标注是否存在 YOSO 锚定效应。

关键问题：如果作者的标注是在 YOSO 预标注基础上做的，且只在"明显错误"处修改，
那么作者的标注会系统性贴近 YOSO，导致 E3 准确率虚高。

检验方法：
  1. 作者修改的样本（changed=true）中，YOSO 原本判错的比例
  2. 作者未修改的样本（changed=false）中，YOSO 判对的比例
  3. 对比 4 位独立标注者在这些样本上的判断
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
    return {r["file"]: r for r in d["labels"]}


def main():
    labels = json.load(open(os.path.join(BASE, "labels_filled.json"), encoding="utf-8"))
    meta = labels["meta"]
    orig = {r["file"]: r for r in labels["labels"]}

    print("=" * 84)
    print("诊断：作者标注的 YOSO 锚定效应")
    print("=" * 84)
    print(f"\n标注元信息: {meta}")

    # 分类：changed vs unchanged
    changed = [r for r in labels["labels"] if r.get("changed")]
    unchanged = [r for r in labels["labels"] if not r.get("changed")]
    print(f"\n作者修改样本: {len(changed)}/{len(labels['labels'])}")
    print(f"作者未修改: {len(unchanged)}")

    # 在 changed 样本中，YOSO 原预测 vs 作者最终标注
    print("\n" + "=" * 84)
    print("1. 作者修改样本的详情")
    print("=" * 84)
    print(f"{'文件':<14}{'YOSO原判':<11}{'作者改为':<11}{'修改方向'}")
    print("-" * 84)
    for r in changed:
        y = norm(r["yoso_passable"])
        a = norm(r["passable"])
        arrow = "→"
        print(f"{r['file']:<14}{y:<11}{a:<11}{y} {arrow} {a}")

    # ===== 关键检验：独立标注者对"作者修改样本"的判断 =====
    print("\n" + "=" * 84)
    print("2. 独立标注者对「作者修改样本」的判断")
    print("=" * 84)

    v2 = {}
    for n, fn in [("A+", "A+.json"), ("B+", "B+.json"), ("C+", "C+.json"), ("D+", "D+.json")]:
        d = load(fn)
        if d:
            v2[n] = d

    if not v2:
        print("无 v2 标注")
        return

    print(f"\n{'文件':<14}{'YOSO':<10}{'作者':<10}", end="")
    for n in v2:
        print(f"{n:<8}", end="")
    print(f"{'多数':<10}{'作者是否被支持'}")
    print("-" * 84)

    stats = {"author_matches_yoso": 0, "author_differs_yoso": 0,
             "author_differs_yoso_but_majority_agrees_author": 0,
             "author_differs_yoso_and_majority_agrees_yoso": 0,
             "author_differs_yoso_and_majority_neither": 0}

    for r in changed:
        f = r["file"]
        y = norm(r["yoso_passable"])
        a = norm(r["passable"])
        vals = [norm(v2[n][f]["passable"]) for n in v2 if f in v2[n]]
        mv = Counter(vals).most_common(1)[0][0] if vals else None

        print(f"{f:<14}{y:<10}{a:<10}", end="")
        for n in v2:
            v = norm(v2[n][f]["passable"]) if f in v2[n] else "?"
            mark = "*" if v == a else ""
            print(f"{v+mark:<8}", end="")
        print(f"{mv:<10}", end="")

        support = "?"
        if a == y:
            stats["author_matches_yoso"] += 1
            support = "作者=YOSO"
        else:
            stats["author_differs_yoso"] += 1
            if mv == a:
                stats["author_differs_yoso_but_majority_agrees_author"] += 1
                support = "多数支持作者"
            elif mv == y:
                stats["author_differs_yoso_and_majority_agrees_yoso"] += 1
                support = "多数支持YOSO"
            else:
                stats["author_differs_yoso_and_majority_neither"] += 1
                support = "多数两者皆非"
        print(support)

    print("\n统计（作者修改的样本中）:")
    for k, v in stats.items():
        print(f"  {k}: {v}")

    # ===== 3. 作者未修改样本：独立标注者是否也认同 =====
    print("\n" + "=" * 84)
    print("3. 作者未修改样本的一致性")
    print("=" * 84)
    n_agree_all = 0
    n_total = 0
    disagree_examples = []
    for r in unchanged:
        f = r["file"]
        a = norm(r["passable"])
        vals = [norm(v2[n][f]["passable"]) for n in v2 if f in v2[n]]
        if not vals:
            continue
        n_total += 1
        if all(v == a for v in vals):
            n_agree_all += 1
        else:
            mv = Counter(vals).most_common(1)[0][0]
            disagree_examples.append((f, a, dict(zip([n for n in v2 if f in v2[n]], vals)), mv))

    print(f"  作者未修改 {n_total} 个样本中，4 位标注者全部认同作者的: {n_agree_all} "
          f"({n_agree_all/n_total*100:.1f}%)")
    print(f"\n  存在分歧的前 10 例:")
    print(f"  {'文件':<14}{'作者':<10}{'多数':<10}{'标注者'}")
    print("  " + "-" * 76)
    for f, a, d, mv in disagree_examples[:10]:
        print(f"  {f:<14}{a:<10}{mv:<10}{d}")

    # ===== 结论 =====
    print("\n" + "=" * 84)
    print("结论")
    print("=" * 84)
    if stats["author_differs_yoso"] > 0:
        supported = stats["author_differs_yoso_but_majority_agrees_author"]
        total = stats["author_differs_yoso"]
        print(f"  作者在 {total} 处修改了 YOSO 的预测")
        print(f"  其中 {supported} 处得到多数标注者支持 ({supported/total*100:.1f}%)")
        print(f"  其中 {stats['author_differs_yoso_and_majority_agrees_yoso']} 处多数支持 YOSO（即作者改错了）")
        print(f"  其中 {stats['author_differs_yoso_and_majority_neither']} 处两者皆非")
        if supported / total < 0.5:
            print("\n  ✗ 作者的修改多数不被独立标注者支持 → 标注可能受 YOSO 锚定影响")
        else:
            print("\n  ✓ 作者的修改多数得到独立标注者支持 → 标注相对可靠")


if __name__ == "__main__":
    main()
