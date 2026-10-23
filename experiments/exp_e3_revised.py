# -*- coding: utf-8 -*-
"""复核结果记录与重新计算。

作者（你）看过 11 张 L2 样本后，逐张给出的判断：
  e3_024: unknown   （原标 forward，YOSO forward）
  e3_026: right     （原标 forward，YOSO forward）
  e3_035: right     （原标 forward，YOSO forward）
  e3_056: forward   （原标 left，YOSO left）
  e3_072: left      （原标 unknown，YOSO unknown）
  e3_073: forward   （原标 unknown，YOSO unknown）
  e3_074: left      （原标 unknown，YOSO unknown）
  e3_075: forward   （原标 unknown，YOSO unknown）
  e3_076: left      （原标 unknown，YOSO unknown）
  未明确: e3_061, e3_062

结论：作者复核后的 9 个判断与 4 位盲标者完全一致。
这证明原标注确实是"未仔细复核 YOSO 预测"造成的漏改，而非作者与盲标者的
判断标准差异。因此可以用"复核后的标注"作为真值重算 E3。
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
OUT = os.path.join(RESULTS_DIR, "e3_revised.json")

ALIAS = {"ahead": "forward", "forward": "forward", "left": "left",
         "right": "right", "unknown": "unknown", "none": "unknown"}


def norm(v):
    if v is None:
        return "unknown"
    return ALIAS.get(str(v).strip().lower(), str(v).strip().lower())


# 作者复核后的修正（只列与原标注不同的）
AUTHOR_REVISION = {
    "e3_024.jpg": "unknown",
    "e3_026.jpg": "right",
    "e3_035.jpg": "right",
    "e3_056.jpg": "forward",
    "e3_072.jpg": "left",
    "e3_073.jpg": "forward",
    "e3_074.jpg": "left",
    "e3_075.jpg": "forward",
    "e3_076.jpg": "left",
    # e3_061 / e3_062 作者未明确，暂按盲标者判断（forward）处理，但标记为待定
}


def main():
    labels = json.load(open(os.path.join(BASE, "labels_filled.json"), encoding="utf-8"))
    orig = {r["file"]: norm(r["passable"]) for r in labels["labels"]}
    yoso = {r["file"]: norm(r["yoso_passable"]) for r in labels["labels"]}

    v2 = {}
    for n, fn in [("A+", "A+.json"), ("B+", "B+.json"),
                  ("C+", "C+.json"), ("D+", "D+.json")]:
        p = os.path.join(BASE, fn)
        if os.path.exists(p):
            v2[n] = {r["file"]: norm(r["passable"]) for r in json.load(open(p, encoding="utf-8"))["labels"]}

    e3 = json.load(open(os.path.join(RESULTS_DIR, "e3_obstacle_eval.json"), encoding="utf-8"))
    recs = {r["file"]: r for r in e3["all_records"]}
    pred = {f: norm(r["pred_direction"]) for f, r in recs.items()}

    files = sorted(f for f in pred if f in orig)
    print("=" * 88)
    print("作者复核结果分析")
    print("=" * 88)

    # ===== 1. 复核判断 vs 盲标者 =====
    print("\n" + "=" * 88)
    print("1. 作者的复核判断 vs 4 位盲标者")
    print("=" * 88)
    print(f"{'文件':<14}{'原标注':<10}{'复核判断':<10}{'盲标一致':<10}{'是否一致'}")
    print("-" * 88)
    n_match = 0
    for f, new in AUTHOR_REVISION.items():
        mv = Counter([v2[n][f] for n in v2]).most_common(1)[0][0]
        match = new == mv
        if match:
            n_match += 1
        print(f"{f:<14}{orig[f]:<10}{new:<10}{mv:<10}"
              f"{'✓ 一致' if match else '✗ 不同'}")
    print(f"\n  复核判断与盲标者一致的: {n_match}/{len(AUTHOR_REVISION)} "
          f"({n_match/len(AUTHOR_REVISION)*100:.1f}%)")

    # ===== 2. 构造修正后的真值 =====
    print("\n" + "=" * 88)
    print("2. 构造修正后的真值（三种口径）")
    print("=" * 88)

    # 口径 A：原标注（论文原口径）
    gt_orig = dict(orig)

    # 口径 B：作者复核修正后（9 处修正；e3_061/062 保持原标注 left/right？还是按盲标）
    # 谨慎起见，e3_061/062 保持原标注（作者未明确表态）
    gt_revised = dict(orig)
    for f, v in AUTHOR_REVISION.items():
        gt_revised[f] = v

    # 口径 C：4 位盲标者多数投票
    gt_majority = {}
    for f in files:
        vals = [v2[n][f] for n in v2 if f in v2[n]]
        gt_majority[f] = Counter(vals).most_common(1)[0][0]

    # ===== 3. 各种口径下的准确率 =====
    print("\n" + "=" * 88)
    print("3. 各口径 E3 准确率")
    print("=" * 88)

    results = {}
    for name, gt in [("原标注（论文原口径）", gt_orig),
                     ("作者复核修正后", gt_revised),
                     ("4位盲标多数投票", gt_majority)]:
        n = len(files)
        correct = sum(1 for f in files if pred[f] == gt[f])
        errs = [(f, gt[f], pred[f]) for f in files if pred[f] != gt[f]]
        acc = correct / n
        results[name] = {"n": n, "correct": correct, "accuracy": round(acc, 4),
                         "errors": errs}
        print(f"\n  【{name}】")
        print(f"    准确率: {acc*100:.1f}%  ({correct}/{n})")
        if errs:
            print(f"    错误 {len(errs)} 例:")
            for f, t, p in errs:
                print(f"      {f}: 真值={t:<8} 预测={p}")

    # ===== 4. 对比 =====
    print("\n" + "=" * 88)
    print("4. 对比汇总")
    print("=" * 88)
    print(f"{'口径':<28}{'准确率':>10}{'错误数':>10}{'相对原口径':>14}")
    print("-" * 88)
    base = results["原标注（论文原口径）"]["accuracy"]
    for name, r in results.items():
        d = r["accuracy"] - base
        print(f"{name:<28}{r['accuracy']*100:>9.1f}%"
              f"{len(r['errors']):>10}{d*100:>+13.1f}pp")

    # ===== 5. 分层口径（最严谨） =====
    print("\n" + "=" * 88)
    print("5. 分层口径（推荐用于论文）")
    print("=" * 88)

    # 用修正后的真值做分层：盲标者共识度
    strata = {"unanimous": [], "majority": [], "divided": []}
    for f in files:
        vals = [v2[n][f] for n in v2]
        c = Counter(vals)
        top, cnt = c.most_common(1)[0]
        if cnt == 4:
            strata["unanimous"].append(f)
        elif cnt == 3:
            strata["majority"].append(f)
        else:
            strata["divided"].append(f)

    for k, label in [("unanimous", "盲标者 4:0 一致"),
                     ("majority", "盲标者 3:1 多数"),
                     ("divided", "盲标者 2:2 分歧")]:
        fs = strata[k]
        if not fs:
            continue
        n = len(fs)
        # 用修正后真值
        c_rev = sum(1 for f in fs if pred[f] == gt_revised[f])
        # 用盲标多数
        c_mv = sum(1 for f in fs if pred[f] == gt_majority[f])
        print(f"  {label:<20} n={n:>2}  "
              f"vs复核真值 {c_rev/n*100:>5.1f}%   vs盲标多数 {c_mv/n*100:>5.1f}%")

    # 共识子集
    consensus = strata["unanimous"] + strata["majority"]
    if consensus:
        n = len(consensus)
        c_rev = sum(1 for f in consensus if pred[f] == gt_revised[f])
        print(f"\n  有共识子集（4:0 + 3:1）: n={n}, "
              f"准确率（vs复核真值）{c_rev/n*100:.1f}%")
        results["consensus"] = {"label": "有共识子集", "n": n,
                                "correct": c_rev,
                                "accuracy": round(c_rev/n, 4)}

    # 输出
    out = {
        "author_revision": AUTHOR_REVISION,
        "revision_vs_blind_agreement": f"{n_match}/{len(AUTHOR_REVISION)}",
        "results": {k: {kk: vv for kk, vv in v.items() if kk != "errors"}
                    for k, v in results.items()},
        "strata": {k: len(v) for k, v in strata.items()},
        "note": "e3_061/e3_062 作者未明确复核，保持原标注",
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\n保存 -> {OUT}")


if __name__ == "__main__":
    main()
