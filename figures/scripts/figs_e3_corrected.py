# -*- coding: utf-8 -*-
"""用修正后的真值重新生成图 4（混淆矩阵）与图 5（分类别准确率）。

修正来源：作者复核 9 处标注（与 4 位盲标者 100% 一致）。
"""
import json
import os
from collections import Counter

import numpy as np
from PIL import Image, ImageDraw, ImageFont

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "_素材", "figs")

FONT = r"C:\Windows\Fonts\msyh.ttc"
FONT_B = r"C:\Windows\Fonts\msyhbd.ttc"
C_BG, C_INK, C_EDGE = (255, 255, 255), (32, 32, 36), (90, 96, 110)
C_HI, C_BLUE, C_GREY, C_WHITE = (38, 122, 78), (86, 130, 190), (110, 110, 118), (255, 255, 255)

ALIAS = {"ahead": "forward", "forward": "forward", "left": "left",
         "right": "right", "unknown": "unknown", "none": "unknown"}
ZH = {"forward": "向前", "left": "向左", "right": "向右", "unknown": "不确定"}
CLASSES = ["forward", "left", "right", "unknown"]

# 作者复核修正（9 处）
REVISION = {
    "e3_024.jpg": "unknown", "e3_026.jpg": "right", "e3_035.jpg": "right",
    "e3_056.jpg": "forward", "e3_072.jpg": "left", "e3_073.jpg": "forward",
    "e3_074.jpg": "left", "e3_075.jpg": "forward", "e3_076.jpg": "left",
}


def norm(v):
    if v is None:
        return "unknown"
    return ALIAS.get(str(v).strip().lower(), str(v).strip().lower())


def font(size, bold=False):
    return ImageFont.truetype(FONT_B if bold else FONT, size)


def put(d, xy, s, f, fill=C_INK):
    d.text(xy, s, font=f, fill=fill)


def put_center(d, cx, cy, s, f, fill=C_INK):
    b = d.textbbox((0, 0), s, font=f)
    d.text((cx - (b[2] - b[0]) / 2, cy - (b[3] - b[1]) / 2 - b[1]), s, font=f, fill=fill)


def load_data():
    labels = json.load(open(os.path.join(BASE, "_素材", "obstacle_eval",
                                        "labels_filled.json"), encoding="utf-8"))
    e3 = json.load(open(os.path.join(BASE, "实验", "results",
                                    "e3_obstacle_eval.json"), encoding="utf-8"))
    pred = {r["file"]: norm(r["pred_direction"]) for r in e3["all_records"]}

    gt = {}
    for r in labels["labels"]:
        f = r["file"]
        gt[f] = REVISION.get(f, norm(r["passable"]))

    files = sorted(f for f in pred if f in gt)
    return gt, pred, files


def heat_color(v, vmax):
    if vmax <= 0:
        return (240, 240, 240)
    t = min(1.0, v / vmax)
    return tuple(int(255 - (255 - c) * t) for c in C_HI)


def fig_confusion(gt, pred, files):
    cm = Counter()
    for f in files:
        cm[(gt[f], pred[f])] += 1
    vmax = max(cm.values()) if cm else 1

    W, H = 1100, 920
    img = Image.new("RGB", (W, H), C_BG)
    d = ImageDraw.Draw(img)
    put_center(d, W // 2, 46, f"图 4  避障方向混淆矩阵（修正后，n={len(files)}）", font(32, True))

    x0, y0, cell = 330, 180, 150
    n = len(CLASSES)
    for j, p in enumerate(CLASSES):
        put_center(d, x0 + j * cell + cell // 2, y0 - 48, ZH[p], font(22, True))
    for i, g in enumerate(CLASSES):
        cy = y0 + i * cell + cell // 2
        put_center(d, x0 - 95, cy, ZH[g], font(22, True))
        for j, p in enumerate(CLASSES):
            v = cm.get((g, p), 0)
            x, y = x0 + j * cell, y0 + i * cell
            d.rectangle((x, y, x + cell, y + cell),
                        fill=heat_color(v, vmax), outline=C_EDGE, width=2)
            color = C_WHITE if v > vmax * 0.55 else C_INK
            put_center(d, x + cell // 2, y + cell // 2, str(v), font(40, True), color)

    put(d, (x0, y0 - 105), "YOSO 预测", font(20, True), C_EDGE)
    for k, ch in enumerate("人工真值"):
        put(d, (72, y0 + n * cell // 2 - 60 + k * 30), ch, font(19, True), C_EDGE)

    correct = sum(cm.get((c, c), 0) for c in CLASSES)
    acc = correct / len(files) if files else 0
    y = y0 + n * cell + 55
    put(d, (130, y), f"方向准确率 = {acc*100:.1f}%  ({correct}/{len(files)})", font(24, True), C_HI)
    put(d, (130, y + 46),
        "注：真值经作者复核修正（9 处），与 4 位盲标者 100% 一致",
        font(17), C_GREY)

    p = os.path.join(OUT, "fig4_confusion.png")
    img.save(p, dpi=(200, 200))
    arr = np.array(img)
    print(f"saved {p}  (acc={acc*100:.1f}%)")
    for name, (x, y_, w, h) in {
        "标题": (280, 20, 540, 50),
        "列标题": (x0, y0 - 70, 600, 40),
        "行标题": (x0 - 160, y0, 80, 200),
        "准确率": (130, y, 500, 40),
    }.items():
        r = arr[y_:y_ + h, x:x + w]
        print(f"    {'OK  ' if (r < 240).any() else 'FAIL'} {name}")
    return cm, acc


def fig_per_class(gt, pred, files):
    per = {}
    for c in CLASSES:
        sub = [f for f in files if gt[f] == c]
        if not sub:
            per[c] = {"n": 0, "accuracy": 0.0}
            continue
        ok = sum(1 for f in sub if pred[f] == c)
        per[c] = {"n": len(sub), "accuracy": ok / len(sub)}

    # 楼梯
    labels = json.load(open(os.path.join(BASE, "_素材", "obstacle_eval",
                                        "labels_filled.json"), encoding="utf-8"))
    e3 = json.load(open(os.path.join(BASE, "实验", "results",
                                    "e3_obstacle_eval.json"), encoding="utf-8"))
    pst = {r["file"]: bool(r["pred_stairs"]) for r in e3["all_records"]}
    gst = {r["file"]: bool(r["stairs"]) for r in labels["labels"] if r["file"] in files}
    fs = [f for f in files if f in gst]
    tp = sum(1 for f in fs if gst[f] and pst.get(f))
    fn_ = sum(1 for f in fs if gst[f] and not pst.get(f))
    fp = sum(1 for f in fs if not gst[f] and pst.get(f))
    recall = tp / (tp + fn_) if tp + fn_ else 0
    precision = tp / (tp + fp) if tp + fp else 0
    stairs_acc = sum(1 for f in fs if gst[f] == pst.get(f)) / len(fs) if fs else 0

    W, H = 1340, 880
    img = Image.new("RGB", (W, H), C_BG)
    d = ImageDraw.Draw(img)
    put_center(d, W // 2, 44, "图 5  分类别准确率与楼梯检测（修正后）", font(34, True))

    f_lab, f_val, f_small, f_head = font(22), font(20, True), font(15), font(23, True)
    lab_x, bar_x, y0 = 120, 230, 160
    bar_h, gap, maxw = 62, 34, 400

    put(d, (bar_x, y0 - 48), "方向分类准确率", f_head)
    for i, k in enumerate(CLASSES):
        v, n = per[k]["accuracy"], per[k]["n"]
        y = y0 + i * (bar_h + gap)
        put(d, (lab_x, y + 16), ZH[k], f_lab)
        w = int(maxw * v)
        d.rectangle((bar_x, y, bar_x + w, y + bar_h), fill=C_HI, outline=C_EDGE, width=2)
        put(d, (bar_x + w + 14, y + 14), f"{v*100:.1f}%  (n={n})", f_val)

    rx, rx_bar, maxw2 = 800, 950, 250
    put(d, (rx, y0 - 48), "楼梯检测", f_head)
    for i, (name, v, note) in enumerate([
        ("召回率", recall, f"TP={tp} / (TP+FN)={tp+fn_}"),
        ("精确率", precision, f"TP={tp} / (TP+FP)={tp+fp}"),
        ("准确率", stairs_acc, f"n={len(fs)}"),
    ]):
        y = y0 + i * (bar_h + gap + 24)
        put(d, (rx, y + 14), name, f_lab)
        w = int(maxw2 * v)
        d.rectangle((rx_bar, y, rx_bar + w, y + bar_h), fill=C_BLUE, outline=C_EDGE, width=2)
        put(d, (rx_bar + w + 14, y + 14), f"{v*100:.1f}%", f_val)
        put(d, (rx, y + bar_h + 4), note, f_small, C_GREY)

    put(d, (60, H - 96),
        "注：方向准确率整体 87.4%（76/87）；修正前的 97.7% 因锚定偏差偏高 10.3 个百分点，已撤回。",
        font(17), C_GREY)
    put(d, (60, H - 62),
        "楼梯检测无漏报（FN=0），1 例误报（FP=1）；此类误报属安全侧失败。",
        font(17), C_GREY)

    p = os.path.join(OUT, "fig5_per_class.png")
    img.save(p, dpi=(200, 200))
    arr = np.array(img)
    print(f"saved {p}")
    for name, (x, y_, w, h) in {
        "标题": (450, 18, 450, 50),
        "左标题": (bar_x, y0 - 55, 300, 40),
        "右标题": (rx, y0 - 55, 200, 40),
        "底部": (60, H - 100, 800, 40),
    }.items():
        r = arr[y_:y_ + h, x:x + w]
        print(f"    {'OK  ' if (r < 240).any() else 'FAIL'} {name}")
    return per, recall, precision


def main():
    gt, pred, files = load_data()
    print(f"样本: {len(files)}")
    cm, acc = fig_confusion(gt, pred, files)
    per, rec, prec = fig_per_class(gt, pred, files)

    out = {"n": len(files), "accuracy": round(acc, 4),
           "per_class": {k: {"n": v["n"], "accuracy": round(v["accuracy"], 4)}
                         for k, v in per.items()},
           "stairs": {"recall": round(rec, 4), "precision": round(prec, 4)},
           "revision": REVISION}
    op = os.path.join(BASE, "实验", "results", "e3_corrected_metrics.json")
    json.dump(out, open(op, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\n保存 -> {op}")
    print(f"\n分类别:")
    for k, v in per.items():
        print(f"  {ZH[k]}: {v['accuracy']*100:.1f}% (n={v['n']})")
    print(f"楼梯: 召回 {rec*100:.1f}%, 精确 {prec*100:.1f}%")


if __name__ == "__main__":
    main()
