# -*- coding: utf-8 -*-
"""生成图 8：跨会话定位误差与失锁修复效果。"""
import json
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFont

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES = os.path.join(BASE, "实验", "results")
OUT = os.path.join(BASE, "_素材", "figs")

FONT = r"C:\Windows\Fonts\msyh.ttc"
FONT_B = r"C:\Windows\Fonts\msyhbd.ttc"
C_BG, C_INK, C_EDGE = (255, 255, 255), (32, 32, 36), (90, 96, 110)
C_GREY = (110, 110, 118)
C_ORANGE = (196, 108, 42)
C_GREEN = (38, 122, 78)
C_RED = (180, 60, 60)
C_BLUE = (86, 130, 190)


def font(size, bold=False):
    return ImageFont.truetype(FONT_B if bold else FONT, size)


def put(d, xy, s, f, fill=C_INK):
    d.text(xy, s, font=f, fill=fill)


def put_center(d, cx, cy, s, f, fill=C_INK):
    b = d.textbbox((0, 0), s, font=f)
    d.text((cx - (b[2] - b[0]) / 2, cy - (b[3] - b[1]) / 2 - b[1]), s, font=f, fill=fill)


def main():
    summ = json.load(open(os.path.join(RES, "cross_session_summary.json"), encoding="utf-8"))
    main_exp = summ["main_experiment"]
    abl = summ["strict_ablation"]

    # 逐帧数据（修复前/后）
    raw_off = json.load(open(os.path.join(RES, "strict_off_1.json"), encoding="utf-8"))
    raw_on = json.load(open(os.path.join(RES, "strict_on_1.json"), encoding="utf-8"))

    W, H = 1480, 940
    img = Image.new("RGB", (W, H), C_BG)
    d = ImageDraw.Draw(img)
    put_center(d, W // 2, 42, "图 8  跨会话定位误差与失锁恢复效果", font(32, True))

    # ===== 上：逐帧进度曲线 =====
    px0, py0 = 110, 140
    pw, ph = 620, 300
    put(d, (px0, py0 - 36), "逐帧路径进度：真值 vs 系统判定", font(20, True), C_INK)

    def get_series(rec):
        pts = [(r["i"], r["gt_progress"], r["pred_progress"])
               for r in rec["records"]
               if r["pred_progress"] is not None and r["gt_progress"] is not None]
        return pts

    off_pts = get_series(raw_off)
    on_pts = get_series(raw_on)
    n_max = max(max(p[0] for p in off_pts), max(p[0] for p in on_pts))

    def x_of(i):
        return px0 + int(pw * i / n_max)

    def y_of(v):
        return py0 + ph - int(ph * v)

    # 坐标轴
    d.line([(px0, py0), (px0, py0 + ph)], fill=C_EDGE, width=2)
    d.line([(px0, py0 + ph), (px0 + pw, py0 + ph)], fill=C_EDGE, width=2)
    for v in (0.0, 0.5, 1.0):
        y = y_of(v)
        d.line([(px0 - 6, y), (px0, y)], fill=C_EDGE, width=2)
        put(d, (px0 - 48, y - 9), f"{v:.1f}", font(14), C_GREY)
    for i in (0, 40, 80):
        x = x_of(i)
        put_center(d, x, py0 + ph + 16, str(i), font(14), C_GREY)
    put_center(d, px0 + pw // 2, py0 + ph + 42, "帧序号", font(15), C_GREY)

    # 真值曲线（灰）
    for k in range(1, len(off_pts)):
        d.line([(x_of(off_pts[k-1][0]), y_of(off_pts[k-1][1])),
                (x_of(off_pts[k][0]), y_of(off_pts[k][1]))], fill=(200, 200, 205), width=3)
    # 修复前（红）
    for k in range(1, len(off_pts)):
        d.line([(x_of(off_pts[k-1][0]), y_of(off_pts[k-1][2])),
                (x_of(off_pts[k][0]), y_of(off_pts[k][2]))], fill=C_RED, width=2)
    # 修复后（绿）
    for k in range(1, len(on_pts)):
        d.line([(x_of(on_pts[k-1][0]), y_of(on_pts[k-1][2])),
                (x_of(on_pts[k][0]), y_of(on_pts[k][2]))], fill=C_GREEN, width=2)

    # 图例
    lx = px0 + 20
    ly = py0 + 16
    for name, color in [("真值（DTW）", (200, 200, 205)),
                        ("修复前", C_RED), ("修复后", C_GREEN)]:
        d.line([(lx, ly), (lx + 26, ly)], fill=color, width=3)
        put(d, (lx + 32, ly - 9), name, font(14), C_INK)
        lx += 120

    # ===== 右上：误差指标对比 =====
    rx, ry = 830, 140
    put(d, (rx, ry - 36), "误差指标（3 次重复均值）", font(20, True), C_INK)

    metrics = [
        ("误差均值", abl["off"]["error_mean"], abl["on"]["error_mean"]),
        ("误差 P90", abl["off"]["error_p90"], abl["on"]["error_p90"]),
    ]
    bar_w = 68
    maxv = 0.32
    base = ry + 250
    for k, (name, vo, vn) in enumerate(metrics):
        gx = rx + 30 + k * 200
        for j, (v, color, lab) in enumerate([(vo, C_RED, "修复前"), (vn, C_GREEN, "修复后")]):
            x = gx + j * (bar_w + 16)
            h = int(230 * v / maxv)
            d.rectangle((x, base - h, x + bar_w, base), fill=color, outline=C_EDGE, width=2)
            put_center(d, x + bar_w // 2, base - h - 18, f"{v*100:.1f}%", font(16, True))
            put_center(d, x + bar_w // 2, base + 20, lab, font(14))
        put_center(d, gx + bar_w + 8, base + 44, name, font(17, True))
    d.line([(rx, base), (rx + 420, base)], fill=C_EDGE, width=2)

    # ===== 右下：关键数字 =====
    sx, sy = 830, 560
    put(d, (sx, sy - 30), "失锁恢复效果", font(20, True), C_INK)

    rows = [
        ("误差均值", f"{abl['off']['error_mean']*100:.2f}%", f"{abl['on']['error_mean']*100:.2f}%",
         f"{abl['improvement']['error_mean']:+.1f}%"),
        ("误差 P90", f"{abl['off']['error_p90']*100:.2f}%", f"{abl['on']['error_p90']*100:.2f}%",
         f"{abl['improvement']['error_p90']:+.1f}%"),
        ("到达判定帧", f"{abl['off']['arrived_frames']:.0f}", f"{abl['on']['arrived_frames']:.0f}",
         "恢复"),
        ("末帧状态", abl["off"]["final_status"][0], abl["on"]["final_status"][0], "✓"),
    ]
    put(d, (sx + 10, sy + 8), "指标", font(15, True), C_GREY)
    put(d, (sx + 150, sy + 8), "修复前", font(15, True), C_GREY)
    put(d, (sx + 265, sy + 8), "修复后", font(15, True), C_GREY)
    put(d, (sx + 390, sy + 8), "变化", font(15, True), C_GREY)
    for k, (name, a, b, c) in enumerate(rows):
        y = sy + 40 + k * 42
        put(d, (sx + 10, y), name, font(16), C_INK)
        put(d, (sx + 150, y), a, font(16, True), C_RED)
        put(d, (sx + 265, y), b, font(16, True), C_GREEN)
        put(d, (sx + 390, y), c, font(16, True), C_ORANGE)

    # ===== 底部说明 =====
    yb = H - 118
    d.line([(60, yb - 22), (W - 60, yb - 22)], fill=C_EDGE, width=2)
    put(d, (60, yb),
        f"跨会话（2-7 → 2-7-3，88 帧，100% 覆盖，真值 DTW 对齐相似度 {main_exp['gt_mean_sim']:.4f}）："
        f"前 67% 路径误差中位数 2.0%，后段因单帧误判导致永久失锁。",
        font(17, True), C_INK)
    put(d, (60, yb + 30),
        "失锁恢复机制：连续 2 帧最佳距离 >6.0 时，搜索窗口由 ±4 临时扩大至 ±12，重新捕获真实位置。",
        font(16), C_GREY)
    put(d, (60, yb + 56),
        "注：该机制仅在真正失锁时生效；对未失锁的短会话（2-7-2，78% 覆盖）无改善，误差略增 1.0 个百分点。",
        font(16), C_GREY)

    p = os.path.join(OUT, "fig8_cross_session.png")
    img.save(p, dpi=(200, 200))

    arr = np.array(img)
    print("saved", p)
    for name, (x, y, w, h) in {
        "标题": (400, 20, 700, 50),
        "左上标题": (px0, py0 - 42, 400, 40),
        "右上标题": (rx, ry - 42, 300, 40),
        "右下标题": (sx, sy - 36, 250, 40),
        "底部": (60, yb, 1200, 40),
    }.items():
        region = arr[y:y + h, x:x + w]
        print(f"    {'OK  ' if (region < 240).any() else 'FAIL'} {name}")


if __name__ == "__main__":
    main()
