# -*- coding: utf-8 -*-
"""验证假设：YOSO 输出 unknown 的样本，画面是否确实更模糊？

作者观察：YOSO 判"不确定"的图，目测都是画面模糊的。

量化指标（模糊度）：
  1. 拉普拉斯方差 (Laplacian variance) — 最经典的对焦/模糊度量，越低越模糊
  2. Tenengrad（Sobel 梯度能量）— 边缘强度，越低越模糊
  3. 高频能量占比（FFT）— 模糊图像高频分量少
  4. 对比度（灰度标准差）

统计检验：
  - unknown 组 vs 非 unknown 组的指标差异
  - Mann-Whitney U 检验（非参数，适合小样本）
"""
import json
import os

import numpy as np
from PIL import Image

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
IMG_DIR = os.path.join(BASE, "images_e3")
OUT = os.path.join(RESULTS_DIR, "blur_vs_unknown.json")


def laplacian_variance(gray):
    """拉普拉斯方差：经典的模糊检测指标。"""
    k = np.array([[0, 1, 0], [1, -4, 1], [0, 1, 0]], dtype=np.float32)
    # 手动卷积（不依赖 scipy）
    h, w = gray.shape
    lap = np.zeros((h - 2, w - 2), dtype=np.float32)
    for i in range(h - 2):
        for j in range(w - 2):
            lap[i, j] = (gray[i, j + 1] + gray[i + 1, j] + gray[i, j] +
                         gray[i + 2, j + 1] + gray[i + 1, j + 2] - 4 * gray[i + 1, j + 1])
    return float(lap.var())


def tenengrad(gray):
    """Tenengrad：Sobel 梯度能量。"""
    kx = np.array([[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]], dtype=np.float32)
    ky = np.array([[-1, -2, -1], [0, 0, 0], [1, 2, 1]], dtype=np.float32)
    h, w = gray.shape
    gx = np.zeros((h - 2, w - 2), dtype=np.float32)
    gy = np.zeros((h - 2, w - 2), dtype=np.float32)
    for i in range(h - 2):
        for j in range(w - 2):
            patch = gray[i:i + 3, j:j + 3]
            gx[i, j] = float(np.sum(patch * kx))
            gy[i, j] = float(np.sum(patch * ky))
    return float(np.mean(gx ** 2 + gy ** 2))


def high_freq_ratio(gray):
    """高频能量占比（FFT）。"""
    f = np.fft.fft2(gray)
    fshift = np.fft.fftshift(f)
    mag = np.abs(fshift)
    h, w = mag.shape
    cy, cx = h // 2, w // 2
    # 以半径 0.15*min(h,w) 为界
    r = int(0.15 * min(h, w))
    yy, xx = np.ogrid[:h, :w]
    mask_high = ((yy - cy) ** 2 + (xx - cx) ** 2) > r ** 2
    total = mag.sum()
    return float(mag[mask_high].sum() / total) if total > 0 else 0.0


def mann_whitney_u(a, b):
    """Mann-Whitney U 检验（手写，避免依赖 scipy）。返回 (U, p近似)。"""
    n1, n2 = len(a), len(b)
    combined = [(v, 0) for v in a] + [(v, 1) for v in b]
    combined.sort()
    # 秩
    ranks = [0.0] * len(combined)
    i = 0
    while i < len(combined):
        j = i
        while j < len(combined) and combined[j][0] == combined[i][0]:
            j += 1
        avg_rank = (i + 1 + j) / 2.0
        for k in range(i, j):
            ranks[k] = avg_rank
        i = j
    r1 = sum(ranks[k] for k in range(len(combined)) if combined[k][1] == 0)
    u1 = r1 - n1 * (n1 + 1) / 2
    u2 = n1 * n2 - u1
    u = min(u1, u2)
    # 正态近似
    mu = n1 * n2 / 2
    sigma = np.sqrt(n1 * n2 * (n1 + n2 + 1) / 12)
    z = (u - mu) / sigma if sigma > 0 else 0
    # 双尾 p（正态近似）
    from math import erfc, sqrt
    p = erfc(abs(z) / sqrt(2))
    return float(u), float(p)


def main():
    labels = json.load(open(os.path.join(BASE, "labels_filled.json"), encoding="utf-8"))

    e3 = json.load(open(os.path.join(RESULTS_DIR, "e3_obstacle_eval.json"), encoding="utf-8"))
    pred = {r["file"]: r["pred_direction"] for r in e3["all_records"]}

    print("=" * 84)
    print("验证假设：YOSO 判 unknown 的样本是否更模糊")
    print("=" * 84)

    records = []
    for r in labels["labels"]:
        f = r["file"]
        p = os.path.join(IMG_DIR, f)
        if not os.path.exists(p):
            continue
        im = Image.open(p).convert("L")
        # 统一缩放，避免尺寸影响
        im = im.resize((320, 240), Image.LANCZOS)
        g = np.asarray(im, dtype=np.float32)

        records.append({
            "file": f,
            "pred": pred.get(f),
            "gt": r["passable"],
            "lap_var": round(laplacian_variance(g), 2),
            "tenengrad": round(tenengrad(g), 2),
            "hf_ratio": round(high_freq_ratio(g), 4),
            "contrast": round(float(g.std()), 2),
            "brightness": round(float(g.mean()), 2),
        })

    print(f"样本数: {len(records)}")

    unknown = [r for r in records if r["pred"] == "unknown"]
    known = [r for r in records if r["pred"] != "unknown"]

    print(f"\nYOSO 判 unknown: {len(unknown)} 张")
    print(f"YOSO 判有方向: {len(known)} 张")

    print("\n" + "=" * 84)
    print("unknown 样本明细")
    print("=" * 84)
    print(f"{'文件':<14}{'拉普拉斯方差':>12}{'Tenengrad':>12}{'高频占比':>10}{'对比度':>9}{'亮度':>8}")
    print("-" * 84)
    for r in unknown:
        print(f"{r['file']:<14}{r['lap_var']:>12.2f}{r['tenengrad']:>12.2f}"
              f"{r['hf_ratio']:>10.4f}{r['contrast']:>9.2f}{r['brightness']:>8.1f}")

    # ===== 统计对比 =====
    print("\n" + "=" * 84)
    print("指标对比（unknown vs 有方向）")
    print("=" * 84)
    print(f"{'指标':<16}{'unknown 均值':>14}{'有方向 均值':>14}{'倍数':>10}{'U 检验 p':>12}{'显著?'}")
    print("-" * 84)

    metrics = [
        ("lap_var", "拉普拉斯方差"),
        ("tenengrad", "Tenengrad"),
        ("hf_ratio", "高频能量占比"),
        ("contrast", "对比度"),
        ("brightness", "亮度"),
    ]
    results = {}
    for key, name in metrics:
        a = [r[key] for r in unknown]
        b = [r[key] for r in known]
        if not a or not b:
            continue
        mean_a = float(np.mean(a))
        mean_b = float(np.mean(b))
        ratio = mean_a / mean_b if mean_b != 0 else None
        u, p = mann_whitney_u(a, b)
        sig = "✓ 显著" if p < 0.05 else "✗ 不显著"
        results[key] = {
            "name": name,
            "unknown_mean": round(mean_a, 4),
            "known_mean": round(mean_b, 4),
            "ratio": round(ratio, 3) if ratio else None,
            "u": round(u, 1),
            "p": round(p, 4),
            "significant": p < 0.05,
        }
        print(f"{name:<16}{mean_a:>14.2f}{mean_b:>14.2f}"
              f"{(f'{ratio:.2f}x' if ratio else 'N/A'):>10}{p:>12.4f}{sig:>10}")

    # ===== 结论 =====
    print("\n" + "=" * 84)
    print("结论")
    print("=" * 84)
    lap = results.get("lap_var")
    hf = results.get("hf_ratio")
    if lap:
        print(f"  拉普拉斯方差: unknown={lap['unknown_mean']:.2f}, "
              f"有方向={lap['known_mean']:.2f}, "
              f"{'显著更低' if lap['significant'] else '无显著差异'} (p={lap['p']:.4f})")
    if hf:
        print(f"  高频能量占比: unknown={hf['unknown_mean']:.4f}, "
              f"有方向={hf['known_mean']:.4f}, "
              f"{'显著更低' if hf['significant'] else '无显著差异'} (p={hf['p']:.4f})")

    n_sig = sum(1 for r in results.values() if r["significant"])
    print(f"\n  {n_sig}/{len(results)} 个指标达到统计显著（p<0.05）")
    if lap and lap["significant"] and lap["unknown_mean"] < lap["known_mean"]:
        print("  ✓ 假设成立：YOSO 判 unknown 的样本确实更模糊")
    else:
        print("  ⚠ 假设未获统计支持，需进一步分析")

    out = {"n_total": len(records), "n_unknown": len(unknown),
           "n_known": len(known), "metrics": results, "records": records}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\n保存 -> {OUT}")


if __name__ == "__main__":
    main()
