# -*- coding: utf-8 -*-
"""探索不同的类别聚合方式对标注一致性的影响。

目标：找到一种既保留任务语义、又能显著提升 κ 的类别划分方式。

测试的划分方案：
  S1 原始 4 类：forward / left / right / unknown
  S2 合并左右：forward / turn(left+right) / unknown
  S3 二分类：straight(forward) / turn(left+right)，剔除 unknown
  S4 三分类（把 unknown 归入 turn）：forward / turn
  S5 仅看"能否直行"：forward vs 其他（unknown 归入其他）
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
OUT = os.path.join(RESULTS_DIR, "inter_annotator_schemes.json")

ALIAS = {"ahead": "forward", "forward": "forward", "left": "left",
         "right": "right", "unknown": "unknown", "none": "unknown"}


def norm(v):
    if v is None:
        return "unknown"
    return ALIAS.get(str(v).strip().lower(), str(v).strip().lower())


def to_scheme(v, scheme):
    d = norm(v)
    if scheme == "S1":
        return d
    if scheme == "S2":
        return "turn" if d in ("left", "right") else d
    if scheme == "S3":
        if d == "unknown":
            return None      # 剔除
        return "straight" if d == "forward" else "turn"
    if scheme == "S4":
        return "straight" if d == "forward" else "turn"
    if scheme == "S5":
        return "straight" if d == "forward" else "other"
    return d


SCHEME_CATS = {
    "S1": ["forward", "left", "right", "unknown"],
    "S2": ["forward", "turn", "unknown"],
    "S3": ["straight", "turn"],
    "S4": ["straight", "turn"],
    "S5": ["straight", "other"],
}

SCHEME_DESC = {
    "S1": "原始 4 类（forward/left/right/unknown）",
    "S2": "合并左右（forward/turn/unknown）",
    "S3": "二分类剔除 unknown（straight/turn）",
    "S4": "二分类含 unknown（straight/turn）",
    "S5": "能否直行（straight/other）",
}


def cohen(a, b):
    n = len(a)
    if n == 0:
        return None
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum((ca[k] / n) * (cb[k] / n) for k in set(a) | set(b))
    if pe >= 1.0:
        return (1.0, po, pe) if po >= 1.0 else None
    return ((po - pe) / (1 - pe), po, pe)


def fleiss(rows, cats):
    n_items = len(rows)
    n_raters = len(rows[0])
    total = n_items * n_raters
    counts = Counter(v for r in rows for v in r)
    p = {c: counts[c] / total for c in cats}
    P_items = []
    for r in rows:
        rc = Counter(r)
        P_items.append(sum(rc[c] * (rc[c] - 1) for c in cats)
                       / (n_raters * (n_raters - 1)))
    P_bar = sum(P_items) / n_items
    Pe = sum(p[c] ** 2 for c in cats)
    if Pe >= 1.0:
        return (1.0, P_bar, Pe) if P_bar >= 1.0 else None
    return ((P_bar - Pe) / (1 - Pe), P_bar, Pe)


def interpret(k):
    if k is None:
        return "N/A"
    if k > 0.80:
        return "几乎完全"
    if k > 0.60:
        return "强"
    if k > 0.40:
        return "中等"
    if k > 0.20:
        return "一般"
    return "弱"


def load(group):
    out = {}
    for name, fn in group.items():
        p = os.path.join(BASE, fn)
        if os.path.exists(p):
            d = json.load(open(p, encoding="utf-8"))
            out[name] = {r["file"]: r for r in d["labels"]}
    return out


def main():
    print("=" * 82)
    print("类别划分方案对标注一致性的影响")
    print("=" * 82)

    v2 = load(V2)
    v1 = load(V1)
    orig = {}
    op = os.path.join(BASE, ORIG)
    if os.path.exists(op):
        orig = {r["file"]: r for r in json.load(open(op, encoding="utf-8"))["labels"]}

    results = {}
    for gname, data in (("v1(3人)", v1), ("v2(4人)", v2)):
        if len(data) < 2:
            continue
        names = list(data.keys())
        common = sorted(set.intersection(*[set(m) for m in data.values()]))
        print(f"\n{'='*82}")
        print(f"{gname}：{len(names)} 人 × {len(common)} 张")
        print(f"{'='*82}")
        print(f"{'方案':<34}{'Fleiss κ':>10}{'两两均值':>10}{'一致率':>9}{'等级':>8}")
        print("-" * 82)

        gres = {}
        for scheme in ("S1", "S2", "S3", "S4", "S5"):
            # 构造每人的序列（S3 需要逐样本剔除 unknown）
            rows = []
            used_files = []
            for f in common:
                vals = [to_scheme(data[n][f]["passable"], scheme) for n in names]
                if any(v is None for v in vals):
                    continue
                rows.append(vals)
                used_files.append(f)
            if not rows:
                continue

            fr = fleiss(rows, SCHEME_CATS[scheme])
            # 两两 κ 均值
            ks = []
            for i, j in itertools.combinations(range(len(names)), 2):
                a = [r[i] for r in rows]
                b = [r[j] for r in rows]
                r2 = cohen(a, b)
                if r2 and r2[0] is not None:
                    ks.append(r2[0])
            mean_k = statistics.mean(ks) if ks else None
            agree = fr[1] if fr else None

            gres[scheme] = {
                "desc": SCHEME_DESC[scheme],
                "n_items_used": len(rows),
                "fleiss_kappa": round(fr[0], 4) if fr else None,
                "pairwise_mean": round(mean_k, 4) if mean_k else None,
                "p_bar": round(fr[1], 4) if fr else None,
                "interpret": interpret(fr[0]) if fr else "N/A",
            }
            print(f"{SCHEME_DESC[scheme]:<34}"
                  f"{fr[0]:>10.4f}" if fr else f"{SCHEME_DESC[scheme]:<34}{'N/A':>10}",
                  end="")
            print(f"{mean_k:>10.4f}" if mean_k else f"{'N/A':>10}", end="")
            print(f"{fr[1]*100:>8.1f}%" if fr else f"{'N/A':>9}", end="")
            print(f"{interpret(fr[0]) if fr else 'N/A':>8}")

        results[gname] = gres

    # 与作者对比（用最优方案）
    print("\n" + "=" * 82)
    print("各方案下「多数投票 vs 作者」的 κ")
    print("=" * 82)
    print(f"{'方案':<34}{'v1':>10}{'v2':>10}")
    print("-" * 82)
    mv_results = {}
    for scheme in ("S1", "S2", "S3", "S4", "S5"):
        row = {}
        for gname, data in (("v1", v1), ("v2", v2)):
            names = list(data.keys())
            common = sorted(set.intersection(*[set(m) for m in data.values()]))
            if orig:
                common = [f for f in common if f in orig]
            pairs_a, pairs_b = [], []
            for f in common:
                vals = [to_scheme(data[n][f]["passable"], scheme) for n in names]
                if any(v is None for v in vals):
                    continue
                c = Counter(vals)
                top, cnt = c.most_common(1)[0]
                pairs_a.append(to_scheme(orig[f]["passable"], scheme))
                pairs_b.append(top)
            if pairs_a:
                r = cohen(pairs_a, pairs_b)
                row[gname] = round(r[0], 4) if r else None
        mv_results[scheme] = row
        a = row.get("v1")
        b = row.get("v2")
        print(f"{SCHEME_DESC[scheme]:<34}"
              f"{a:>10.4f}" if a else f"{SCHEME_DESC[scheme]:<34}{'N/A':>10}", end="")
        print(f"{b:>10.4f}" if b else f"{'N/A':>10}")

    # 结论
    print("\n" + "=" * 82)
    print("结论")
    print("=" * 82)
    best = None
    for scheme, gres in results.get("v2(4人)", {}).items():
        k = gres.get("fleiss_kappa")
        if k is not None and (best is None or k > best[1]):
            best = (scheme, k, gres)
    if best:
        print(f"  v2 最优方案: {best[0]} - {best[2]['desc']}")
        print(f"    Fleiss' κ = {best[1]:.4f} → {best[2]['interpret']}")
        if best[1] > 0.60:
            print("  ✓ 达到「强一致」，可用于论文")
        elif best[1] > 0.40:
            print("  ⚠ 仅「中等一致」，需在论文中说明任务本身的主观性")
        else:
            print("  ✗ 仍偏低，建议改为客观特征标注")

    out = {"schemes": SCHEME_DESC, "results": results,
           "majority_vs_author": mv_results,
           "meta": {"n_items": 87, "author_labels": len(orig)}}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\n保存 -> {OUT}")


if __name__ == "__main__":
    main()
