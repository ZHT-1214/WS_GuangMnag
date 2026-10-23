# -*- coding: utf-8 -*-
"""生成图 9：规则 2/3/4 真机验证结果。"""
import json
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFont

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES = os.path.join(BASE, "实验", "results", "arbitration_rules234.json")
LOGDIR = os.path.join(BASE, "实验", "results", "arb_logs")
OUT = os.path.join(BASE, "_素材", "figs")

FONT = r"C:\Windows\Fonts\msyh.ttc"
FONT_B = r"C:\Windows\Fonts\msyhbd.ttc"
C_BG, C_INK, C_EDGE = (255, 255, 255), (32, 32, 36), (90, 96, 110)
C_GREY = (110, 110, 118)
C_ORANGE = (196, 108, 42)
C_GREEN = (38, 122, 78)
C_BLUE = (86, 130, 190)
C_RED = (180, 60, 60)


def font(size, bold=False):
    return ImageFont.truetype(FONT_B if bold else FONT, size)


def put(d, xy, s, f, fill=C_INK):
    d.text(xy, s, font=f, fill=fill)


def put_center(d, cx, cy, s, f, fill=C_INK):
    b = d.textbbox((0, 0), s, font=f)
    d.text((cx - (b[2] - b[0]) / 2, cy - (b[3] - b[1]) / 2 - b[1]), s, font=f, fill=fill)


def main():
    d0 = json.load(open(RES, encoding="utf-8"))
    summ = d0["summary"]
    sessions = d0["sessions"]

    W, H = 1480, 900
    img = Image.new("RGB", (W, H), C_BG)
    d = ImageDraw.Draw(img)
    put_center(d, W // 2, 42, "图 9  仲裁规则 2/3/4 的真机验证结果", font(32, True))

    # ===== 左上：三场景柱状 =====
    lx, ly = 100, 160
    put(d, (lx, ly - 40), "各场景规则 2 触发次数", font(20, True), C_INK)

    bar_w, gap = 100, 55
    maxh = 180
    maxv = max(s["rule2_conflict_overrides"] for s in sessions)
    base = ly + 210
    for i, s in enumerate(sessions):
        x = lx + 30 + i * (bar_w + gap)
        v = s["rule2_conflict_overrides"]
        h = int(maxh * v / maxv) if maxv else 0
        d.rectangle((x, base - h, x + bar_w, base), fill=C_ORANGE, outline=C_EDGE, width=2)
        put_center(d, x + bar_w // 2, base - h - 20, f"{v} 次", font(18, True))
        put_center(d, x + bar_w // 2, base + 22, s["session"], font(15))
    d.line([(lx, base), (lx + 40 + 3 * (bar_w + gap), base)], fill=C_EDGE, width=2)

    # ===== 右上：关键指标 =====
    rx, ry = 760, 160
    put(d, (rx, ry - 40), "关键指标汇总", font(20, True), C_INK)

    rows = [
        ("总录制时长", f"{d0['meta']['total_duration_s']:.0f} s", C_INK),
        ("总导航帧", f"{d0['meta']['total_nav_frames']}", C_INK),
        ("规则 2 冲突让行", f"{summ['rule2_conflict_overrides']} 次", C_ORANGE),
        ("规则 3 合规率", f"{summ['rule3_compliance_rate']*100:.1f}%", C_GREEN),
        ("规则 4 降级触发", f"{summ['rule4_stop_events']} 次", C_BLUE),
    ]
    for k, (name, val, color) in enumerate(rows):
        y = ry + 10 + k * 48
        put(d, (rx, y), name, font(17), C_INK)
        put(d, (rx + 250, y), val, font(18, True), color)

    # ===== 左下：规则 3 保持窗口时序图 =====
    bx, by = 100, 470
    put(d, (bx, by - 36), "规则 3 保持窗口：让行后导航静默时长", font(20, True), C_INK)

    # 绘制 5s 阈值线与各次让行后的静默时长
    chart_w, chart_h = 600, 130
    cy0 = by + 40
    d.rectangle((bx, cy0, bx + chart_w, cy0 + chart_h), outline=C_EDGE, width=2)
    # 5 秒阈值
    thr_x = bx + int(chart_w * 5 / 20)
    d.line([(thr_x, cy0), (thr_x, cy0 + chart_h)], fill=C_RED, width=2)
    put(d, (thr_x + 4, cy0 - 18), "5s 设计窗口", font(13), C_RED)
    # 20 秒轴标注
    for t in (0, 5, 10, 15, 20):
        x = bx + int(chart_w * t / 20)
        d.line([(x, cy0 + chart_h), (x, cy0 + chart_h + 5)], fill=C_EDGE, width=1)
        put_center(d, x, cy0 + chart_h + 16, f"{t}s", font(12), C_GREY)

    # 各场景的静默时长（用中位数画点）
    sil = [s["rule3_nav_silence_median_s"] for s in sessions if s["rule3_nav_silence_median_s"]]
    for i, s in enumerate(sessions):
        v = s["rule3_nav_silence_median_s"]
        if not v:
            continue
        x = bx + int(chart_w * min(v, 19.8) / 20)
        cy = cy0 + 40 + i * 34
        d.ellipse((x - 7, cy - 7, x + 7, cy + 7),
                  fill=C_GREEN if v >= 5 else C_RED, outline=C_EDGE, width=1)
        put(d, (bx + chart_w + 10, cy - 9), f"{s['session']}: {v:.1f}s", font(14))

    # ===== 右下：让行方向分布 =====
    dx, dy = 100, 700
    put(d, (dx, dy - 30), "规则 2 让行方向分布", font(20, True), C_INK)
    dirs = summ["rule2_override_directions"]
    total = sum(dirs.values())
    order = [("forward", "向前通行"), ("right", "右侧通行"), ("left", "左侧通行")]
    xx = dx + 20
    for key, label in order:
        v = dirs.get(key, 0)
        if total == 0:
            continue
        w = int(400 * v / total)
        d.rectangle((xx, dy + 10, xx + w, dy + 42), fill=C_ORANGE, outline=C_EDGE, width=1)
        put(d, (xx + w + 10, dy + 14), f"{label} {v} 次", font(15))
        xx += w + 130

    # ===== 底部说明 =====
    yb = H - 90
    d.line([(60, yb - 20), (W - 60, yb - 20)], fill=C_EDGE, width=2)
    put(d, (60, yb),
        "3 段真实障碍录制（576 s，712 帧）：规则 2 触发 37 次，规则 3 合规率 97.3%"
        f"（让行后静默中位数 {sum(sil)/len(sil):.1f}s），规则 4 触发 3 次。",
        font(17, True), C_INK)
    put(d, (60, yb + 28),
        "注：唯一 1 次规则 3 违规（让行后 3.5s 出现导航播报）发生在障碍居中、YOSO 判定抖动的边界场景，已如实报告。",
        font(15), C_GREY)

    p = os.path.join(OUT, "fig9_arbitration234.png")
    img.save(p, dpi=(200, 200))

    arr = np.array(img)
    print("saved", p)
    for name, (x, y, w, h) in {
        "标题": (380, 18, 720, 50),
        "左上": (lx, ly - 48, 400, 40),
        "右上": (rx, ry - 48, 300, 40),
        "左中": (bx, by - 42, 500, 40),
        "底部": (60, yb, 1200, 40),
    }.items():
        region = arr[y:y + h, x:x + w]
        print(f"    {'OK  ' if (region < 240).any() else 'FAIL'} {name}")


if __name__ == "__main__":
    main()
