# -*- coding: utf-8 -*-
"""标注一致性分析（审稿问题 4）。

三份独立盲标结果（A/B/C）与作者原标注的对比：
  1. 三位标注者两两 Cohen's κ
  2. 三人的 Fleiss' κ
  3. 与作者原标注（labels_filled.json）的一致性
  4. 分歧样本定位与原因分析

判读标准（Landis & Koch, 1977）：
  >0.80 几乎完全一致  0.61-0.80 强一致  0.41-0.60 中等  0.21-0.40 一般  <0.21 弱
"""
import json
import os
import itertools
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
ANNOT = {
    "A": os.path.join(BASE, "A.json"),
    "B": os.path.join(BASE, "B.json"),
    "C": os.path.join(BASE, "C.json"),
}
ORIG = os.path.join(BASE, "labels_filled.json")
OUT = os.path.join(RESULTS_DIR, "inter_annotator.json")

# 方向别名归一（原标注里 forward/ahead 混用）
ALIAS = {
    "ahead": "forward",
    "forward": "forward",
    "left": "left",
    "right": "right",
    "unknown": "unknown",
    "none": "unknown",
    "back": "back",
}

DIR_LABELS = ["forward", "left", "right", "unknown"]


def norm_dir(v):
    if v is None:
        return "unknown"
    v = str(v).strip().lower()
    return ALIAS.get(v, v)


def cohen_kappa(a, b, labels=None):
    """Cohen's κ（两标注者）。"""
    assert len(a) == len(b)
    n = len(a)
    if n == 0:
        return None
    # 观察一致率
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    # 期望一致率
    ca, cb = Counter(a), Counter(b)
    pe = sum((ca[k] / n) * (cb[k] / n) for k in set(a) | set(b))
    if pe >= 1.0:
        return 1.0 if po >= 1.0 else None
    return (po - pe) / (1 - pe), po, pe


def fleiss_kappa(ratings, categories):
    """Fleiss' κ（多标注者）。
    ratings: list of list，每项是一组标注（长度一致）
    """
    n_items = len(ratings)
    n_raters = len(ratings[0]) if n_items else 0
    if n_items == 0 or n_raters < 2:
        return None

    # 每个类别的总体比例
    total = n_items * n_raters
    counts = Counter()
    for row in ratings:
        for v in row:
            counts[v] += 1
    p = {c: counts[c] / total for c in categories}

    # 每个 item 的 P_i
    P_items = []
    for row in ratings:
        rc = Counter(row)
        s = sum(rc[c] * (rc[c] - 1) for c in categories)
        P_items.append(s / (n_raters * (n_raters - 1)))

    P_bar = sum(P_items) / n_items
    Pe = sum(p[c] ** 2 for c in categories)
    if Pe >= 1.0:
        return 1.0 if P_bar >= 1.0 else None
    return (P_bar - Pe) / (1 - Pe), P_bar, Pe


def interpret(k):
    if k is None:
        return "无法计算"
    if k > 0.80:
        return "几乎完全一致"
    if k > 0.60:
        return "强一致"
    if k > 0.40:
        return "中等一致"
    if k > 0.20:
        return "一般一致"
    return "弱一致"


def load_annotators():
    data = {}
    for name, path in ANNOT.items():
        if not os.path.exists(path):
            print(f"  缺少 {path}")
            continue
        d = json.load(open(path, encoding="utf-8"))
        m = {r["file"]: r for r in d["labels"]}
        data[name] = m
        print(f"  {name}: {len(m)} 条")
    return data


def main():
    print("=" * 80)
    print("标注一致性分析")
    print("=" * 80)

    print("\n加载标注文件:")
    data = load_annotators()
    if len(data) < 2:
        raise SystemExit("至少需要 2 份标注")

    # 作者原标注
    orig = {}
    if os.path.exists(ORIG):
        od = json.load(open(ORIG, encoding="utf-8"))
        orig = {r["file"]: r for r in od["labels"]}
        print(f"  原作者: {len(orig)} 条")

    # 共同文件
    common = set.intersection(*[set(m.keys()) for m in data.values()])
    if orig:
        common &= set(orig.keys())
    common = sorted(common)
    print(f"\n共同样本: {len(common)} 张")

    names = list(data.keys())

    # ========== 1. 两两 Cohen's κ ==========
    print("\n" + "=" * 80)
    print("1. 两两 Cohen's κ")
    print("=" * 80)

    pairs = {}
    for x, y in itertools.combinations(names, 2):
        a_dir = [norm_dir(data[x][f]["passable"]) for f in common]
        b_dir = [norm_dir(data[y][f]["passable"]) for f in common]
        r_dir = cohen_kappa(a_dir, b_dir)
        a_st = [bool(data[x][f].get("stairs")) for f in common]
        b_st = [bool(data[y][f].get("stairs")) for f in common]
        r_st = cohen_kappa(a_st, b_st)

        pairs[f"{x}-{y}"] = {
            "direction": {"kappa": round(r_dir[0], 4), "po": round(r_dir[1], 4),
                          "pe": round(r_dir[2], 4)} if r_dir and r_dir[0] is not None else None,
            "stairs": {"kappa": round(r_st[0], 4), "po": round(r_st[1], 4),
                       "pe": round(r_st[2], 4)} if r_st and r_st[0] is not None else None,
        }
        print(f"\n  {x} vs {y}:")
        if r_dir and r_dir[0] is not None:
            print(f"    方向: κ={r_dir[0]:.4f} (观察一致 {r_dir[1]*100:.1f}%, "
                  f"期望 {r_dir[2]*100:.1f}%) → {interpret(r_dir[0])}")
        if r_st and r_st[0] is not None:
            print(f"    楼梯: κ={r_st[0]:.4f} (观察一致 {r_st[1]*100:.1f}%, "
                  f"期望 {r_st[2]*100:.1f}%) → {interpret(r_st[0])}")

    # ========== 2. Fleiss' κ（三人） ==========
    print("\n" + "=" * 80)
    print("2. Fleiss' κ（全部标注者）")
    print("=" * 80)
    ratings_dir = []
    ratings_st = []
    for f in common:
        ratings_dir.append([norm_dir(data[n][f]["passable"]) for n in names])
        ratings_st.append([bool(data[n][f].get("stairs")) for n in names])

    fr_dir = fleiss_kappa(ratings_dir, DIR_LABELS)
    fr_st = fleiss_kappa(ratings_st, [True, False])
    fleiss = {}
    if fr_dir and fr_dir[0] is not None:
        print(f"  方向 Fleiss' κ = {fr_dir[0]:.4f} "
              f"(P̄={fr_dir[1]*100:.1f}%, Pe={fr_dir[2]*100:.1f}%) → {interpret(fr_dir[0])}")
        fleiss["direction"] = {"kappa": round(fr_dir[0], 4),
                               "p_bar": round(fr_dir[1], 4),
                               "pe": round(fr_dir[2], 4)}
    if fr_st and fr_st[0] is not None:
        print(f"  楼梯 Fleiss' κ = {fr_st[0]:.4f} "
              f"(P̄={fr_st[1]*100:.1f}%, Pe={fr_st[2]*100:.1f}%) → {interpret(fr_st[0])}")
        fleiss["stairs"] = {"kappa": round(fr_st[0], 4),
                            "p_bar": round(fr_st[1], 4),
                            "pe": round(fr_st[2], 4)}

    # ========== 3. 与作者原标注的对比 ==========
    author_cmp = {}
    if orig:
        print("\n" + "=" * 80)
        print("3. 各标注者 vs 作者原标注")
        print("=" * 80)
        for n in names:
            a_dir = [norm_dir(orig[f]["passable"]) for f in common]
            b_dir = [norm_dir(data[n][f]["passable"]) for f in common]
            r = cohen_kappa(a_dir, b_dir)
            a_st = [bool(orig[f].get("stairs")) for f in common]
            b_st = [bool(data[n][f].get("stairs")) for f in common]
            rs = cohen_kappa(a_st, b_st)
            author_cmp[n] = {
                "direction": {"kappa": round(r[0], 4), "po": round(r[1], 4)} if r and r[0] is not None else None,
                "stairs": {"kappa": round(rs[0], 4), "po": round(rs[1], 4)} if rs and rs[0] is not None else None,
            }
            print(f"\n  {n} vs 作者:")
            if r and r[0] is not None:
                print(f"    方向: κ={r[0]:.4f} (一致 {r[1]*100:.1f}%) → {interpret(r[0])}")
            if rs and rs[0] is not None:
                print(f"    楼梯: κ={rs[0]:.4f} (一致 {rs[1]*100:.1f}%) → {interpret(rs[0])}")

    # ========== 4. 分歧分析 ==========
    print("\n" + "=" * 80)
    print("4. 分歧样本分析（方向）")
    print("=" * 80)
    disputed = []
    for f in common:
        vals = [norm_dir(data[n][f]["passable"]) for n in names]
        if len(set(vals)) > 1:
            disputed.append({
                "file": f,
                "annotations": dict(zip(names, vals)),
                "orig": norm_dir(orig[f]["passable"]) if orig else None,
            })
    print(f"  存在分歧的样本: {len(disputed)}/{len(common)} ({len(disputed)/len(common)*100:.1f}%)")
    for d in disputed[:20]:
        print(f"    {d['file']}: {d['annotations']}" +
              (f" | 作者={d['orig']}" if d["orig"] else ""))
    if len(disputed) > 20:
        print(f"    ... 共 {len(disputed)} 个")

    # 楼梯分歧
    disputed_st = []
    for f in common:
        vals = [bool(data[n][f].get("stairs")) for n in names]
        if len(set(vals)) > 1:
            disputed_st.append({"file": f,
                                "annotations": dict(zip(names, vals))})
    print(f"\n  楼梯存在分歧: {len(disputed_st)}/{len(common)}")

    # ========== 5. 类别分布 ==========
    print("\n" + "=" * 80)
    print("5. 各标注者的类别分布")
    print("=" * 80)
    dist = {}
    for n in names:
        c = Counter(norm_dir(data[n][f]["passable"]) for f in common)
        dist[n] = dict(c)
        print(f"  {n}: {dict(c)}")
    if orig:
        c = Counter(norm_dir(orig[f]["passable"]) for f in common)
        dist["作者"] = dict(c)
        print(f"  作者: {dict(c)}")

    # 保存
    out = {
        "meta": {
            "n_items": len(common),
            "annotators": names,
            "has_author_reference": bool(orig),
            "task": "traversability_direction + stairs",
            "blind_protocol": "annotators saw only the image, no model predictions or prior labels",
        },
        "pairwise_cohen": pairs,
        "fleiss": fleiss,
        "vs_author": author_cmp,
        "disputed_direction": disputed,
        "disputed_stairs": disputed_st,
        "class_distribution": dist,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\n保存 -> {OUT}")

    # 结论
    print("\n" + "=" * 80)
    print("结论")
    print("=" * 80)
    ks = [p["direction"]["kappa"] for p in pairs.values()
          if p["direction"] and p["direction"]["kappa"] is not None]
    if ks:
        import statistics
        print(f"  两两方向 κ: {[f'{k:.3f}' for k in ks]}")
        print(f"  均值 κ = {statistics.mean(ks):.4f} → {interpret(statistics.mean(ks))}")
    if fleiss.get("direction"):
        print(f"  三人 Fleiss' κ = {fleiss['direction']['kappa']:.4f} → "
              f"{interpret(fleiss['direction']['kappa'])}")


if __name__ == "__main__":
    main()
