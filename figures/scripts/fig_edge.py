# -*- coding: utf-8 -*-
"""生成图 7（修订版）：边缘 vs 云端时延对比，含优化前后。"""
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
C_LORANGE = (228, 170, 130)
C_GREEN = (38, 122, 78)


def font(size, bold=False):
    return ImageFont.truetype(FONT_B if bold else FONT, size)


def put(d, xy, s, f, fill=C_INK):
    d.text(xy, s, font=f, fill=fill)


def put_center(d, cx, cy, s, f, fill=C_INK):
    b = d.textbbox((0, 0), s, font=f)
    d.text((cx - (b[2] - b[0]) / 2, cy - (b[3] - b[1]) / 2 - b[1]), s, font=f, fill=fill)


def main():
    opt = json.load(open(os.path.join(RES, "latency_optimization.json"), encoding="utf-8"))
    cache = json.load(open(os.path.join(RES, "cache_bench.json"), encoding="utf-8"))

    W, H = 1400, 900
    img = Image.new("RGB", (W, H), C_BG)
    d = ImageDraw.Draw(img)
    put_center(d, W // 2, 44, "图 7  边缘与云端单帧时延对比（同口径，含节点图解码）", font(31, True))

    # ---- 左：柱状对比 ----
    lx, ly = 100, 165
    put(d, (lx, ly - 44), "端到端 P50 时延", font(22, True), C_INK)

    bars = [
        ("边缘\n优化前", cache["original"]["p50"], C_LORANGE),
        ("边缘\n优化后", cache["cached"]["p50"], C_ORANGE),
        ("云端\nRTX 4090", opt["cloud_ms"], C_GREEN),
    ]
    bar_w, gap = 130, 60
    maxh = 330
    maxv = max(b[1] for b in bars)
    base_y = ly + 400

    for i, (label, v, color) in enumerate(bars):
        x = lx + 40 + i * (bar_w + gap)
        h = int(maxh * v / maxv)
        d.rectangle((x, base_y - h, x + bar_w, base_y), fill=color, outline=C_EDGE, width=2)
        put_center(d, x + bar_w // 2, base_y - h - 24, f"{v:.0f} ms", font(20, True))
        for k, part in enumerate(label.split("\n")):
            put_center(d, x + bar_w // 2, base_y + 26 + k * 25, part, font(17))
    d.line([(lx, base_y), (lx + 60 + len(bars) * (bar_w + gap), base_y)],
           fill=C_EDGE, width=2)

    # 优化箭头标注
    x1 = lx + 40 + bar_w
    x2 = lx + 40 + (bar_w + gap)
    y_arrow = base_y - int(maxh * cache["original"]["p50"] / maxv) + 40
    put_center(d, (x1 + x2) // 2, y_arrow, f"−{cache['saving_ms']:.0f} ms", font(16, True), C_ORANGE)
    put_center(d, (x1 + x2) // 2, y_arrow + 22, f"−{cache['saving_pct']:.1f}%", font(16, True), C_ORANGE)

    # ---- 右：指标表 ----
    rx = 800
    put(d, (rx, ly - 44), "关键指标", font(22, True), C_INK)

    rows = [
        ("边缘/云端 比值", f"{opt['ratio_after']:.2f}×", C_ORANGE),
        ("边缘（优化后）", f"{cache['cached']['p50']:.0f} ms", C_ORANGE),
        ("节点解码开销", f"{cache['saving_ms']:.0f} ms", C_GREY),
        ("云端", f"{opt['cloud_ms']:.0f} ms", C_GREEN),
        ("导航帧间隔", "700 ms", C_INK),
        ("边缘占帧间隔", f"{cache['cached']['p50']/700*100:.0f}%", C_ORANGE),
        ("云端占帧间隔", f"{opt['cloud_ms']/700*100:.0f}%", C_GREEN),
    ]
    for i, (k, v, color) in enumerate(rows):
        y = ly + 6 + i * 52
        put(d, (rx, y + 10), k, font(19), C_INK)
        put(d, (rx + 300, y + 8), v, font(20, True), color)

    # ---- 精度验证框 ----
    bx, by = rx, ly + 6 + len(rows) * 52 + 20
    d.rectangle((bx, by, bx + 480, by + 92), outline=C_GREEN, width=2)
    put(d, (bx + 14, by + 10), "精度验证（缓存优化）", font(18, True), C_GREEN)
    put(d, (bx + 14, by + 38), f"torch.equal() = {cache['closest_identical']}", font(16), C_INK)
    put(d, (bx + 14, by + 60), "最大逐元素差异 = 0.0 · closest 判定完全一致", font(16), C_INK)

    # ---- 底部 ----
    yb = H - 128
    d.line([(60, yb - 22), (W - 60, yb - 22)], fill=C_EDGE, width=2)
    put(d, (60, yb),
        "同口径（含节点图解码）：边缘 394 ms，云端 104 ms，比值 3.80×。节点张量缓存使边缘降低 92 ms（19.0%），精度逐元素等价。",
        font(18, True), C_INK)
    put(d, (60, yb + 32),
        "边缘推理已占导航帧间隔（700 ms）的 56%，叠加采集与 TTS 后接近 2/3；云端仅占 15%，余量充足。",
        font(16), C_GREY)
    put(d, (60, yb + 58),
        "注：Jetson Orin Nano 15 W 模式，GPU 上限 624.75 MHz；云端为服务器本地回环，不含公网 RTT。",
        font(16), C_GREY)

    p = os.path.join(OUT, "fig7_edge_vs_cloud.png")
    img.save(p, dpi=(200, 200))

    arr = np.array(img)
    print("saved", p)
    for name, (x, y, w, h) in {
        "标题": (300, 20, 800, 50),
        "左标题": (lx, ly - 50, 300, 40),
        "右标题": (rx, ly - 50, 200, 40),
        "精度框": (bx, by, 470, 90),
        "底部": (60, yb, 1200, 40),
    }.items():
        region = arr[y:y + h, x:x + w]
        print(f"    {'OK  ' if (region < 240).any() else 'FAIL'} {name}")


if __name__ == "__main__":
    main()
