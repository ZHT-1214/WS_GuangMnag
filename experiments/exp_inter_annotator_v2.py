# -*- coding: utf-8 -*-
"""标注一致性分析 v2（细化定义后的 4 份标注 + 与 v1 对比）。

v1：定义模糊（"哪里能走"），3 人，Fleiss' κ = 0.375
v2：定义明确（"下一步往哪走"），4 人

本脚本同时报告 v1/v2 的 κ，用于论证"细化定义显著提升一致性"。
"""
import json
import os
import itertools
import statistics
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
V1 = {"A": "A.json", "B": "B.json", "C": "C.json"}
V2 = {"A+": "A+.json", "B+": "B+.json", "C+": "C+.json", "D+": "D+.json"}
ORIG = "labels_filled.json"
OUT = os.path.join(RESULTS_DIR, "inter_annotator_v2.json")

ALIAS = {"ahead": "forward", "forward": "forward", "left": "left",
         "right": "right", "unknown": "unknown", "none": "unknown", "back": "back"}
DIR_LABELS = ["forward", "left", "right", "unknown"]


def norm_dir(v):
    if v is None:
        return "unknown"
    return ALIAS.get(str(v).strip().lower(), str(v).strip().lower())


def cohen_kappa(a, b):
    n = len(a)
    if n == 0:
        return None
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum((ca[k] / n) * (cb[k] / n) for k in set(a) | set(b))
    if pe >= 1.0:
        return (1.0, po, pe) if po >= 1.0 else None
    return ((po - pe) / (1 - pe), po, pe)


def fleiss_kappa(rows, categories):
    n_items = len(rows)
    n_raters = len(rows[0]) if n_items else 0
    if n_items == 0 or n_raters < 2:
        return None
    total = n_items * n_raters
    counts = Counter(v for row in rows for v in row)
    p = {c: counts[c] / total for c in categories}
    P_items = []
    for row in rows:
        rc = Counter(row)
        P_items.append(sum(rc[c] * (rc[c] - 1) for c in categories)
                       / (n_raters * (n_raters - 1)))
    P_bar = sum(P_items) / n_items
    Pe = sum(p[c] ** 2 for c in categories)
    if Pe >= 1.0:
        return (1.0, P_bar, Pe) if P_bar >= 1.0 else None
    return ((P_bar - Pe) / (1 - Pe), P_bar, Pe)


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


def load_group(group):
    data = {}
    for name, fn in group.items():
        p = os.path.join(BASE, fn)
        if not os.path.exists(p):
            continue
        d = json.load(open(p, encoding="utf-8"))
        data[name] = {r["file"]: r for r in d["labels"]}
    return data


def analyze(data, group_name, orig):
    names = list(data.keys())
    if len(names) < 2:
        return None
    common = set.intersection(*[set(m) for m in data.values()])
    if orig:
        common &= set(orig)
    common = sorted(common)

    print(f"\n{'='*78}")
    print(f"{group_name}：{len(names)} 位标注者，{len(common)} 张共同样本")
    print(f"{'='*78}")
    print(f"  标注者: {', '.join(names)}")

    # 两两 κ
    pairs = {}
    print(f"\n  两两 Cohen's κ:")
    for x, y in itertools.combinations(names, 2):
        a = [norm_dir(data[x][f]["passable"]) for f in common]
        b = [norm_dir(data[y][f]["passable"]) for f in common]
        r = cohen_kappa(a, b)
        if r and r[0] is not None:
            pairs[f"{x}-{y}"] = {"kappa": round(r[0], 4),
                                 "po": round(r[1], 4), "pe": round(r[2], 4)}
            print(f"    {x:<3} vs {y:<3}: κ={r[0]:.4f}  "
                  f"(一致 {r[1]*100:5.1f}%)  → {interpret(r[0])}")

    # Fleiss
    rows_dir = [[norm_dir(data[n][f]["passable"]) for n in names] for f in common]
    rows_st = [[bool(data[n][f].get("stairs")) for n in names] for f in common]
    fr_d = fleiss_kappa(rows_dir, DIR_LABELS)
    fr_s = fleiss_kappa(rows_st, [True, False])

    fleiss = {}
    print(f"\n  Fleiss' κ（{len(names)} 人）:")
    if fr_d:
        fleiss["direction"] = {"kappa": round(fr_d[0], 4),
                               "p_bar": round(fr_d[1], 4), "pe": round(fr_d[2], 4)}
        print(f"    方向: κ={fr_d[0]:.4f} (P̄={fr_d[1]*100:.1f}%, Pe={fr_d[2]*100:.1f}%)"
              f" → {interpret(fr_d[0])}")
    if fr_s:
        fleiss["stairs"] = {"kappa": round(fr_s[0], 4),
                            "p_bar": round(fr_s[1], 4), "pe": round(fr_s[2], 4)}
        print(f"    楼梯: κ={fr_s[0]:.4f} (P̄={fr_s[1]*100:.1f}%)"
              f" → {interpret(fr_s[0])}")

    # 与作者对比
    vs_author = {}
    if orig:
        print(f"\n  各标注者 vs 作者:")
        for n in names:
            a = [norm_dir(orig[f]["passable"]) for f in common]
            b = [norm_dir(data[n][f]["passable"]) for f in common]
            r = cohen_kappa(a, b)
            if r:
                vs_author[n] = {"kappa": round(r[0], 4), "po": round(r[1], 4)}
                print(f"    {n:<3}: κ={r[0]:.4f} (一致 {r[1]*100:.1f}%)"
                      f" → {interpret(r[0])}")

    # 分歧
    disputed = []
    for f in common:
        vals = [norm_dir(data[n][f]["passable"]) for n in names]
        if len(set(vals)) > 1:
            disputed.append({"file": f,
                             "annotations": dict(zip(names, vals)),
                             "orig": norm_dir(orig[f]["passable"]) if orig else None})
    print(f"\n  方向分歧: {len(disputed)}/{len(common)} "
          f"({len(disputed)/len(common)*100:.1f}%)")

    # 类别分布
    dist = {n: dict(Counter(norm_dir(data[n][f]["passable"]) for f in common))
            for n in names}
    if orig:
        dist["作者"] = dict(Counter(norm_dir(orig[f]["passable"]) for f in common))
    print(f"\n  类别分布:")
    for n in names:
        print(f"    {n:<3}: {dist[n]}")
    if orig:
        print(f"    {'作者':<3}: {dist['作者']}")

    # 多数投票 vs 作者
    majority = {}
    agree_majority = 0
    for f in common:
        vals = [norm_dir(data[n][f]["passable"]) for n in names]
        c = Counter(vals)
        top, cnt = c.most_common(1)[0]
        majority[f] = top
        if cnt * 2 > len(vals):   # 严格多数
            agree_majority += 1
    concensus_rate = agree_majority / len(common) if common else 0
    print(f"\n  多数投票达成率: {agree_majority}/{len(common)} "
          f"({concensus_rate*100:.1f}%)")

    mv_vs_author = None
    if orig:
        a = [norm_dir(orig[f]["passable"]) for f in common]
        b = [majority[f] for f in common]
        r = cohen_kappa(a, b)
        if r:
            mv_vs_author = {"kappa": round(r[0], 4), "po": round(r[1], 4)}
            print(f"  多数投票 vs 作者: κ={r[0]:.4f} (一致 {r[1]*100:.1f}%)"
                  f" → {interpret(r[0])}")

    # 困难标记统计
    hard_count = None
    if 'hard' in json.load(open(os.path.join(BASE, list(V2.values())[0]),
                                encoding="utf-8"))["labels"][0]:
        hard_union = set()
        for n in names:
            for f in common:
                if data[n][f].get("hard"):
                    hard_union.add(f)
        hard_count = len(hard_union)
        print(f"\n  被任一标注者标记为「难判断」: {hard_count}/{len(common)}")

    return {
        "group": group_name,
        "n_annotators": len(names),
        "annotators": names,
        "n_items": len(common),
        "pairwise_cohen": pairs,
        "fleiss": fleiss,
        "vs_author": vs_author,
        "majority_vs_author": mv_vs_author,
        "majority_consensus_rate": round(concensus_rate, 4),
        "disputed_direction": disputed,
        "n_hard": hard_count,
        "class_distribution": dist,
    }


def main():
    print("=" * 78)
    print("标注一致性分析（v1 模糊定义 vs v2 细化定义）")
    print("=" * 78)

    orig = {}
    op = os.path.join(BASE, ORIG)
    if os.path.exists(op):
        od = json.load(open(op, encoding="utf-8"))
        orig = {r["file"]: r for r in od["labels"]}
        print(f"作者原标注: {len(orig)} 条")

    v1 = load_group(V1)
    v2 = load_group(V2)
    print(f"v1 标注者: {list(v1.keys())}")
    print(f"v2 标注者: {list(v2.keys())}")

    r1 = analyze(v1, "v1（模糊定义）", orig) if len(v1) >= 2 else None
    r2 = analyze(v2, "v2（细化定义）", orig) if len(v2) >= 2 else None

    # ===== 对比 =====
    print("\n" + "=" * 78)
    print("v1 vs v2 对比")
    print("=" * 78)
    print(f"{'指标':<28}{'v1':>12}{'v2':>12}{'改善':>12}")
    print("-" * 78)

    def getk(r, path):
        if not r:
            return None
        if path == "fleiss":
            f = r["fleiss"].get("direction")
            return f["kappa"] if f else None
        if path == "mean_pair":
            ks = [v["kappa"] for v in r["pairwise_cohen"].values()
                  if v.get("kappa") is not None]
            return statistics.mean(ks) if ks else None
        if path == "mv":
            m = r.get("majority_vs_author")
            return m["kappa"] if m else None
        if path == "dispute":
            return len(r["disputed_direction"]) / r["n_items"]
        return None

    rows = [
        ("标注者数", len(v1), len(v2), None),
        ("方向 Fleiss' κ", getk(r1, "fleiss"), getk(r2, "fleiss"), "up"),
        ("方向 两两 κ 均值", getk(r1, "mean_pair"), getk(r2, "mean_pair"), "up"),
        ("多数投票 vs 作者 κ", getk(r1, "mv"), getk(r2, "mv"), "up"),
        ("分歧比例", getk(r1, "dispute"), getk(r2, "dispute"), "down"),
    ]
    for name, a, b, direction in rows:
        if isinstance(a, int):
            print(f"{name:<28}{a:>12}{b:>12}{'':>12}")
        elif a is None or b is None:
            print(f"{name:<28}{'N/A':>12}{'N/A':>12}{'':>12}")
        else:
            delta = b - a
            if direction == "down":
                tag = f"{delta*100:+.1f}pp" if name == "分歧比例" else f"{delta:+.3f}"
            else:
                tag = f"{delta:+.3f}"
            print(f"{name:<28}{a:>12.4f}{b:>12.4f}{tag:>12}")

    if r1 and r2:
        f1 = getk(r1, "fleiss")
        f2 = getk(r2, "fleiss")
        if f1 and f2:
            print(f"\n  方向 Fleiss' κ: {f1:.4f} → {f2:.4f} "
                  f"（提升 {(f2-f1):+.4f}，相对 {(f2-f1)/f1*100:+.1f}%）")
            if f2 > 0.60:
                print(f"  ✓ v2 达到「强一致」以上，可用于论文")
            elif f2 > 0.40:
                print(f"  ⚠ v2 为「中等一致」，建议进一步分析分歧样本")
            else:
                print(f"  ✗ v2 仍为「一般一致」，任务定义需进一步细化")

    out = {"v1": r1, "v2": r2,
           "meta": {"v1_definition": "图像中可通行的方向（模糊）",
                    "v2_definition": "假想朝画面中心行走，下一步往哪走（正前方畅通则向前）",
                    "author_labels": len(orig)}}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\n保存 -> {OUT}")


if __name__ == "__main__":
    main()
