# -*- coding: utf-8 -*-
"""生成 E3 结果图：混淆矩阵热力图 + 分类准确率 + 楼梯检测。

注意：PIL 的 ImageDraw.text() 在不指定 fill 时不会绘制任何像素，
因此本脚本所有 text() 调用都显式传入 fill，并在保存后做像素自检。
"""
import json
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFont

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES = os.path.join(BASE, "实验", "results", "e3_obstacle_eval.json")
OUT = os.path.join(BASE, "_素材", "figs")
os.makedirs(OUT, exist_ok=True)

FONT = r"C:\Windows\Fonts\msyh.ttc"
FONT_B = r"C:\Windows\Fonts\msyhbd.ttc"

C_BG = (255, 255, 255)
C_INK = (32, 32, 36)
C_EDGE = (90, 96, 110)
C_HI = (38, 122, 78)
C_BLUE = (86, 130, 190)
C_GREY = (110, 110, 118)
C_WHITE = (255, 255, 255)


def font(size, bold=False):
    return ImageFont.truetype(FONT_B if bold else FONT, size)


def put(d, xy, s, f, fill=C_INK):
    """显式 fill 的文字绘制（PIL 不指定 fill 时不绘制）。"""
    d.text(xy, s, font=f, fill=fill)


def put_center(d, cx, cy, s, f, fill=C_INK):
    b = d.textbbox((0, 0), s, font=f)
    d.text((cx - (b[2] - b[0]) / 2, cy - (b[3] - b[1]) / 2 - b[1]),
           s, font=f, fill=fill)


def heat_color(v, vmax):
    if vmax <= 0:
        return (240, 240, 240)
    t = min(1.0, v / vmax)
    return tuple(int(255 - (255 - c) * t) for c in C_HI)


def check_text_pixels(img, boxes):
    """自检：确认每个文字区域确实有非背景像素。"""
    arr = np.array(img)
    ok = True
    for name, (x, y, w, h) in boxes.items():
        region = arr[y:y + h, x:x + w]
        has = bool((region < 240).any())
        print(f"    {'OK  ' if has else 'FAIL'} {name}")
        ok = ok and has
    return ok


def fig_confusion():
    data = json.load(open(RES, encoding="utf-8"))
    cm = data["direction"]["confusion_matrix"]
    classes = ["ahead", "left", "right", "unknown"]
    zh = {"ahead": "向前", "left": "向左", "right": "向右", "unknown": "不确定"}

    W, H = 1100, 920
    img = Image.new("RGB", (W, H), C_BG)
    d = ImageDraw.Draw(img)

    put_center(d, W // 2, 46, "图 4  避障方向混淆矩阵（n=87）", font(34, True))

    x0, y0 = 330, 180
    cell = 150
    n = len(classes)
    vmax = max(cm.get(f"{g}->{p}", 0) for g in classes for p in classes)

    # 列标题
    for j, p in enumerate(classes):
        put_center(d, x0 + j * cell + cell // 2, y0 - 48, zh[p], font(22, True))

    # 行标题 + 单元格
    for i, g in enumerate(classes):
        cy = y0 + i * cell + cell // 2
        put_center(d, x0 - 95, cy, zh[g], font(22, True))
        for j, p in enumerate(classes):
            v = cm.get(f"{g}->{p}", 0)
            x = x0 + j * cell
            y = y0 + i * cell
            d.rectangle((x, y, x + cell, y + cell),
                        fill=heat_color(v, vmax), outline=C_EDGE, width=2)
            color = C_WHITE if v > vmax * 0.55 else C_INK
            put_center(d, x + cell // 2, y + cell // 2, str(v), font(40, True), color)

    # 轴说明
    put(d, (x0, y0 - 105), "YOSO 预测", font(20, True), C_EDGE)
    for k, ch in enumerate("人工真值"):
        put(d, (72, y0 + n * cell // 2 - 60 + k * 30), ch, font(19, True), C_EDGE)

    # 统计
    y = y0 + n * cell + 55
    acc = data["direction"]["accuracy"]
    put(d, (130, y),
        f"方向准确率 = {acc*100:.1f}%  ({data['direction']['correct']}/{data['direction']['total']})",
        font(24, True), C_HI)
    put(d, (130, y + 46), "对角线为正确预测；非对角仅 2 例（见 §5.3.1 错误分析）",
        font(18), C_GREY)

    p = os.path.join(OUT, "fig4_confusion.png")
    img.save(p, dpi=(200, 200))
    print("saved", p)
    check_text_pixels(img, {
        "标题": (300, 20, 500, 50),
        "列标题": (x0, y0 - 70, 600, 40),
        "行标题": (x0 - 160, y0, 80, 200),
        "准确率": (130, y, 500, 40),
    })


def fig_per_class():
    data = json.load(open(RES, encoding="utf-8"))
    pc = data["direction"]["per_class"]
    stairs = data["stairs"]

    W, H = 1320, 860
    img = Image.new("RGB", (W, H), C_BG)
    d = ImageDraw.Draw(img)
    put_center(d, W // 2, 44, "图 5  分类别准确率与楼梯检测", font(34, True))

    f_lab = font(22)
    f_val = font(20, True)
    f_small = font(15)
    f_head = font(23, True)

    # 左：分类准确率
    zh = {"ahead": "向前", "left": "向左", "right": "向右", "unknown": "不确定"}
    order = ["ahead", "left", "right", "unknown"]
    lab_x, bar_x, y0 = 120, 230, 160
    bar_h, gap = 62, 34
    maxw = 400

    put(d, (bar_x, y0 - 48), "方向分类准确率", f_head, C_INK)
    for i, k in enumerate(order):
        v = pc[k]["accuracy"]
        n = pc[k]["n"]
        y = y0 + i * (bar_h + gap)
        put(d, (lab_x, y + 16), zh[k], f_lab, C_INK)
        w = int(maxw * v)
        d.rectangle((bar_x, y, bar_x + w, y + bar_h), fill=C_HI, outline=C_EDGE, width=2)
        put(d, (bar_x + w + 14, y + 14), f"{v*100:.1f}%  (n={n})", f_val, C_INK)

    # 右：楼梯指标
    rx, rx_bar, maxw2 = 800, 950, 250
    put(d, (rx, y0 - 48), "楼梯检测", f_head, C_INK)
    metrics = [
        ("召回率", stairs["recall"], f"TP={stairs['tp']} / (TP+FN)={stairs['tp']+stairs['fn']}"),
        ("精确率", stairs["precision"], f"TP={stairs['tp']} / (TP+FP)={stairs['tp']+stairs['fp']}"),
        ("准确率", stairs["accuracy"], f"n={data['direction']['total']}"),
    ]
    for i, (name, v, note) in enumerate(metrics):
        y = y0 + i * (bar_h + gap + 24)
        put(d, (rx, y + 14), name, f_lab, C_INK)
        w = int(maxw2 * (v or 0))
        d.rectangle((rx_bar, y, rx_bar + w, y + bar_h),
                    fill=C_BLUE, outline=C_EDGE, width=2)
        put(d, (rx_bar + w + 14, y + 14), f"{(v or 0)*100:.1f}%", f_val, C_INK)
        put(d, (rx, y + bar_h + 4), note, f_small, C_GREY)

    # 底部说明
    put(d, (60, H - 96), "注：楼梯检测无漏报（FN=0），1 例误报（FP=1，见 e3_077.jpg）。",
        font(18), C_GREY)
    put(d, (60, H - 62), "方向分类中 left 与 unknown 达 100%，right 最低（91.7%，1 例误判为向前）。",
        font(18), C_GREY)

    p = os.path.join(OUT, "fig5_per_class.png")
    img.save(p, dpi=(200, 200))
    print("saved", p)
    check_text_pixels(img, {
        "标题": (450, 18, 450, 50),
        "左标题": (bar_x, y0 - 55, 300, 40),
        "左标签": (lab_x, y0, 100, 120),
        "左数值": (bar_x + maxw, y0, 200, 60),
        "右标题": (rx, y0 - 55, 200, 40),
        "右数值": (rx_bar, y0, 300, 60),
        "底部注释": (60, H - 100, 800, 40),
    })


if __name__ == "__main__":
    fig_confusion()
    fig_per_class()
