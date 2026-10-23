# -*- coding: utf-8 -*-
"""生成 C 组 baseline 对比图（图 6）。"""
import json
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFont

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES = os.path.join(BASE, "实验", "results", "baseline_c_honest.json")
OUT = os.path.join(BASE, "_素材", "figs")
os.makedirs(OUT, exist_ok=True)

FONT = r"C:\Windows\Fonts\msyh.ttc"
FONT_B = r"C:\Windows\Fonts\msyhbd.ttc"
C_BG, C_INK, C_EDGE = (255, 255, 255), (32, 32, 36), (90, 96, 110)
C_GREY = (110, 110, 118)
C_GREEN = (38, 122, 78)
C_ORANGE = (196, 108, 42)
C_BLUE = (86, 130, 190)


def font(size, bold=False):
    return ImageFont.truetype(FONT_B if bold else FONT, size)


def put(d, xy, s, f, fill=C_INK):
    d.text(xy, s, font=f, fill=fill)


def put_center(d, cx, cy, s, f, fill=C_INK):
    b = d.textbbox((0, 0), s, font=f)
    d.text((cx - (b[2] - b[0]) / 2, cy - (b[3] - b[1]) / 2 - b[1]), s, font=f, fill=fill)


def main():
    data = json.load(open(RES, encoding="utf-8"))
    s = data["summary"]
    rows = data["per_route"]

    W, H = 1340, 880
    img = Image.new("RGB", (W, H), C_BG)
    d = ImageDraw.Draw(img)
    put_center(d, W // 2, 44, "图 6  单帧纯检索与 NoMaD 的节点定位能力对比", font(33, True))

    # ---- 左：总体对比（分组柱状）----
    lx, ly = 100, 150
    put(d, (lx, ly - 46), "总体准确率（n=312 帧）", font(23, True), C_INK)

    groups = [
        ("单帧检索 ±0", s["single_frame_retrieval"]["tol_0"], C_ORANGE),
        ("单帧检索 ±2", s["single_frame_retrieval"]["tol_2"], C_ORANGE),
        ("单帧检索 ±5", s["single_frame_retrieval"]["tol_5"], C_ORANGE),
        ("NoMaD", s["nomad_accuracy"], C_GREEN),
    ]
    bar_w, gap = 96, 34
    maxh = 300
    base_y = ly + 360
    for i, (label, v, color) in enumerate(groups):
        x = lx + 30 + i * (bar_w + gap)
        h = int(maxh * v)
        d.rectangle((x, base_y - h, x + bar_w, base_y), fill=color, outline=C_EDGE, width=2)
        put_center(d, x + bar_w // 2, base_y - h - 22, f"{v*100:.1f}%", font(19, True))
        # 标签竖排两行
        parts = label.split(" ")
        for k, p in enumerate(parts):
            put_center(d, x + bar_w // 2, base_y + 24 + k * 24, p, font(17))
    d.line([(lx + 10, base_y), (lx + 30 + len(groups) * (bar_w + gap), base_y)],
           fill=C_EDGE, width=2)

    # ---- 右：逐路线散点/柱状 ----
    rx, ry = 760, 150
    put(d, (rx, ry - 46), "逐路线对比", font(23, True), C_INK)

    n = len(rows)
    row_h = 62
    put(d, (rx + 10, ry - 6), "路线", font(16, True), C_GREY)
    put(d, (rx + 90, ry - 6), "单帧±2", font(16, True), C_GREY)
    put(d, (rx + 210, ry - 6), "NoMaD", font(16, True), C_GREY)
    for i, r in enumerate(rows):
        y = ry + 26 + i * row_h
        put(d, (rx + 10, y + 6), r["route"], font(18))
        # 单帧±2 条
        v1 = r["single_frame_retrieval"]["tol_2"]
        w1 = int(110 * v1)
        d.rectangle((rx + 90, y, rx + 90 + max(w1, 1), y + 30),
                    fill=C_ORANGE, outline=C_EDGE, width=1)
        put(d, (rx + 94 + max(w1, 1), y + 4), f"{v1*100:.0f}%", font(15))
        # NoMaD 条
        v2 = r["nomad_accuracy"] or 0
        w2 = int(110 * v2)
        d.rectangle((rx + 210, y, rx + 210 + max(w2, 1), y + 30),
                    fill=C_GREEN, outline=C_EDGE, width=1)
        put(d, (rx + 214 + max(w2, 1), y + 4), f"{v2*100:.0f}%", font(15))

    # ---- 底部结论 ----
    yb = H - 130
    d.line([(60, yb - 20), (W - 60, yb - 20)], fill=C_EDGE, width=2)
    put(d, (60, yb), f"特征区分度 gap = {s['gap_mean']:.4f}（相邻帧与远端帧余弦相似度之差）",
        font(19, True), C_INK)
    put(d, (60, yb + 34),
        "视觉编码器单独不具备节点级判别力；定位能力来自距离预测头（DenseNetwork）与多帧上下文的联合作用。",
        font(17), C_GREY)
    put(d, (60, yb + 62),
        "注：二者任务难度不同（单帧 vs 4 帧上下文），不应将差值解读为“提升幅度”。",
        font(17), C_GREY)

    p = os.path.join(OUT, "fig6_baseline.png")
    img.save(p, dpi=(200, 200))

    # 像素自检
    arr = np.array(img)
    checks = {
        "标题": (300, 20, 700, 50),
        "左标题": (lx, ly - 55, 300, 40),
        "柱状数值": (lx + 30, base_y - maxh - 40, 400, 40),
        "右标题": (rx, ry - 55, 200, 40),
        "底部结论": (60, yb, 900, 40),
    }
    print("saved", p)
    for name, (x, y, w, h) in checks.items():
        region = arr[y:y + h, x:x + w]
        has = bool((region < 240).any())
        print(f"    {'OK  ' if has else 'FAIL'} {name}")


if __name__ == "__main__":
    main()
