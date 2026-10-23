# -*- coding: utf-8 -*-
"""生成论文插图（Pillow 绘制，中文字体使用 Windows 系统字体）。"""
import os

from PIL import Image, ImageDraw, ImageFont

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "figs")
os.makedirs(OUT, exist_ok=True)

FONT = r"C:\Windows\Fonts\msyh.ttc"
FONT_B = r"C:\Windows\Fonts\msyhbd.ttc"

# 配色
C_BG = (255, 255, 255)
C_INK = (32, 32, 36)
C_EDGE = (90, 96, 110)
C_PHONE = (232, 241, 254)   # 手机端
C_CLOUD = (232, 248, 238)   # 云端
C_EDGE_C = (255, 245, 230)  # 边缘端
C_ACC = (196, 62, 62)
C_BLUE = (52, 96, 168)
C_GREEN = (38, 122, 78)


def font(size, bold=False):
    return ImageFont.truetype(FONT_B if bold else FONT, size)


def rounded(d, box, r, fill, outline, width=2):
    d.rounded_rectangle(box, radius=r, fill=fill, outline=outline, width=width)


def text_center(d, cx, cy, s, f, fill=C_INK):
    b = d.textbbox((0, 0), s, font=f)
    d.text((cx - (b[2] - b[0]) / 2, cy - (b[3] - b[1]) / 2 - b[1]), s, font=f, fill=fill)


def arrow(d, x1, y1, x2, y2, fill=C_EDGE, width=3, head=11):
    import math
    d.line([(x1, y1), (x2, y2)], fill=fill, width=width)
    ang = math.atan2(y2 - y1, x2 - x1)
    for s in (-0.42, 0.42):
        d.line([(x2, y2),
                (x2 - head * math.cos(ang - s), y2 - head * math.sin(ang - s))],
               fill=fill, width=width)


# ============================================================
# 图 1 系统总体架构
# ============================================================
def fig_architecture():
    W, H = 1720, 1240
    img = Image.new("RGB", (W, H), C_BG)
    d = ImageDraw.Draw(img)
    f_title = font(40, True)
    f_lane = font(28, True)
    f_box = font(24, True)
    f_small = font(20)
    f_tiny = font(17)

    text_center(d, W // 2, 46, "图 1  WS_plus 云端协同助盲导航系统总体架构", f_title, C_INK)

    # 三条泳道（互不重叠）
    lanes = [
        ("移动端（Android App，Kotlin/Jetpack Compose）", 100, 460, C_PHONE),
        ("云端推理服务（Python/FastAPI，GPU）", 580, 400, C_CLOUD),
        (None, 1000, 160, C_EDGE_C),  # 标题单独绘制，避免遮挡
    ]
    for name, y, h, color in lanes:
        rounded(d, (40, y, W - 40, y + h), 18, color, C_EDGE, 2)
        if name:
            d.text((62, y + 14), name, font=f_lane, fill=C_INK)

    # ---------- 移动端模块 ----------
    y0 = 165
    boxes_m = [
        ("语音交互层\n(VoiceControl / AiApiClient)", 70, 300),
        ("任务调度\nMainActivity 指令路由", 330, 300),
        ("相机采集\nCameraX 640×480→JPEG", 590, 300),
        ("本地拓扑图\n录制 / 导入 / 选择", 850, 300),
        ("导航显示与 TTS\nNavigationRouteVisualization", 1110, 540),
    ]
    for label, x, w in boxes_m:
        rounded(d, (x, y0, x + w, y0 + 120), 12, (255, 255, 255), C_EDGE, 2)
        lines = label.split("\n")
        for i, ln in enumerate(lines):
            text_center(d, x + w // 2, y0 + 44 + i * 30, ln, f_box if i == 0 else f_small)

    # 双通道
    rounded(d, (70, 320, 1030, 450), 12, (255, 255, 255), C_BLUE, 3)
    d.text((90, 332), "双通道并发请求（互不阻塞，独立节流）", font=f_box, fill=C_BLUE)
    d.text((90, 375), "通道 A：导航帧  700 ms/帧  →  POST /v1/navigation/sessions/{id}/frames",
           font=f_small, fill=C_INK)
    d.text((90, 407), "通道 B：避障帧 1000 ms/次  →  POST /v1/vision/obstacle", font=f_small, fill=C_INK)

    # 仲裁模块
    rounded(d, (1110, 320, 1650, 530), 12, (255, 240, 240), C_ACC, 3)
    d.text((1130, 332), "安全仲裁器（App 端状态机）", font=f_box, fill=C_ACC)
    for i, s in enumerate([
        "① 方向确认：连续 2 帧一致才播报",
        "② 冲突复核：连续 2 次冲突才改道",
        "③ 保持窗口：5 s 内抑制导航播报",
        "④ 超时降级：7 s 无响应→停车确认",
    ]):
        d.text((1130, 378 + i * 32), s, font=f_tiny, fill=C_INK)

    # ---------- 云端模块 ----------
    cy = 650
    boxes_c = [
        ("API 网关\n鉴权/限流/校验", 70, 300),
        ("NoMaD 推理后端\ninference.py", 400, 330),
        ("YOSO 边车\n127.0.0.1:8001", 760, 300),
        ("地图与语料\nZIP 上传/节点排序", 1090, 260),
        ("腾讯云 ASR\n语音转写", 1380, 290),
    ]
    for label, x, w in boxes_c:
        rounded(d, (x, cy, x + w, cy + 120), 12, (255, 255, 255), C_EDGE, 2)
        lines = label.split("\n")
        for i, ln in enumerate(lines):
            text_center(d, x + w // 2, cy + 44 + i * 30, ln, f_box if i == 0 else f_small)

    # 模型内部
    rounded(d, (400, cy + 135, 730, cy + 265), 12, (255, 255, 255), C_GREEN, 3)
    d.text((418, cy + 145), "NoMaD 推理流程（19.05 M 参数）", font=f_box, fill=C_GREEN)
    for i, s in enumerate([
        "① 视觉编码：EfficientNet-B0 ×2 + Transformer",
        "② 距离预测：DenseNetwork → 子目标节点",
        "③ 扩散去噪：10 步 DDPM，4 条候选轨迹",
        "④ 轨迹共识：中位数 + 最近样本选择",
    ]):
        d.text((418, cy + 185 + i * 24), s, font=f_tiny, fill=C_INK)

    # ---------- 边缘部署（旧） ----------
    ey = 1055
    # 泳道标题在框上方独立一行，避免遮挡
    d.text((62, 1000 + 14), "原有边缘部署（ROS，Jetson Orin Nano）", font=f_lane, fill=C_INK)
    for i, (label, x, w) in enumerate([
        ("ROS 话题订阅\n/sensor 图像", 70, 320),
        ("navigate_visualization_4_full.py", 420, 420),
        ("BLE 触觉带\nHLK-B40 震动指令", 870, 360),
        ("Jetson Orin Nano\n6 核 / 7.8 GB 内存", 1260, 400),
    ]):
        rounded(d, (x, ey, x + w, ey + 100), 12, (255, 255, 255), C_EDGE, 2)
        lines = label.split("\n")
        for j, ln in enumerate(lines):
            text_center(d, x + w // 2, ey + 34 + j * 30, ln, f_small if j == 0 else f_tiny)

    # 连线：手机 -> 云
    arrow(d, 700, 455, 700, 645, C_BLUE, 4)
    arrow(d, 900, 455, 900, 645, C_ACC, 4)
    d.text((712, 540), "HTTPS", font=f_tiny, fill=C_BLUE)
    d.text((912, 540), "HTTPS", font=f_tiny, fill=C_ACC)

    # 云 -> 手机 回传（走左外侧，避开仲裁器）
    arrow(d, 60, 645, 60, 460, C_GREEN, 3)
    d.text((70, 545), "JSON 结果回传", font=f_tiny, fill=C_GREEN)

    # 边缘 -> 云 迁移箭头
    arrow(d, 1450, 1025, 1450, 790, (150, 120, 60), 3)
    d.text((1462, 890), "能力迁移", font=f_tiny, fill=(150, 120, 60))
    d.text((1462, 914), "（算力/带宽解耦）", font=f_tiny, fill=(150, 120, 60))

    # 底部说明
    d.text((44, 1195), "注：实线为运行时数据流；边缘部署为既有方案，本文将其推理负载迁移至云端以解除端侧算力约束。",
           font=f_tiny, fill=(110, 110, 118))

    p = os.path.join(OUT, "fig1_architecture.png")
    img.save(p, dpi=(200, 200))
    print("saved", p)


# ============================================================
# 图 2 双通道融合与安全仲裁状态机
# ============================================================
def fig_state_machine():
    W, H = 1680, 1000
    img = Image.new("RGB", (W, H), C_BG)
    d = ImageDraw.Draw(img)
    f_title = font(40, True)
    f_box = font(25, True)
    f_small = font(20)
    f_tiny = font(17)

    text_center(d, W // 2, 46, "图 2  双通道融合与安全仲裁状态机", f_title)

    states = {
        "S0": ("S0 初始化\n建立视觉上下文", 150, 190, 300, 120),
        "S1": ("S1 正常引导\n导航方向可播报", 660, 190, 320, 120),
        "S2": ("S2 方向待确认\n连续计数中", 660, 420, 320, 110),
        "S3": ("S3 保持静默\n导航暂停 5 s", 1120, 420, 330, 110),
        "S4": ("S4 停车确认\n要求用户停下", 660, 660, 320, 120),
        "S5": ("S5 恢复判定\n连续安全帧", 1120, 660, 330, 120),
        "S6": ("S6 到达\n结束会话", 1120, 190, 330, 110),
    }
    colors = {
        "S0": (238, 242, 250), "S1": (228, 245, 233), "S2": (255, 249, 225),
        "S3": (255, 243, 228), "S4": (255, 228, 228), "S5": (233, 243, 255),
        "S6": (235, 235, 245),
    }
    for k, (label, x, y, w, h) in states.items():
        rounded(d, (x, y, x + w, y + h), 16, colors[k], C_EDGE, 3)
        lines = label.split("\n")
        for i, ln in enumerate(lines):
            text_center(d, x + w // 2, y + h / 2 - 14 + i * 30,
                        ln, f_box if i == 0 else f_small)

    def edge(a, b, label="", lx=0, ly=0, color=C_EDGE):
        _, x1, y1, w1, h1 = states[a]
        _, x2, y2, w2, h2 = states[b]
        ax, ay = x1 + w1 / 2, y1 + h1 / 2
        bx, by = x2 + w2 / 2, y2 + h2 / 2
        # 简化：从边界出发
        def boundary(cx, cy, tx, ty, w, h):
            import math
            dx, dy = tx - cx, ty - cy
            if dx == 0 and dy == 0:
                return cx, cy
            sx = (w / 2) / abs(dx) if dx else 1e9
            sy = (h / 2) / abs(dy) if dy else 1e9
            s = min(sx, sy)
            return cx + dx * s, cy + dy * s
        p1 = boundary(ax, ay, bx, by, w1, h1)
        p2 = boundary(bx, by, ax, ay, w2, h2)
        arrow(d, p1[0], p1[1], p2[0], p2[1], color, 3)
        if label:
            mx, my = (p1[0] + p2[0]) / 2 + lx, (p1[1] + p2[1]) / 2 + ly
            b = d.textbbox((0, 0), label, font=f_tiny)
            d.rectangle((mx - 6, my - 12, mx + (b[2] - b[0]) + 6, my + 14), fill=C_BG)
            d.text((mx, my - 10), label, font=f_tiny, fill=color)

    edge("S0", "S1", "上下文满 4 帧", 0, -22, C_GREEN)
    edge("S1", "S2", "方向与上次不同", 0, -22)
    edge("S2", "S1", "连续 2 帧一致\n→ 播报", 0, 26, C_GREEN)
    edge("S1", "S3", "避障通道报警", -10, -20, C_ACC)
    edge("S2", "S3", "避障通道报警", 0, -22, C_ACC)
    edge("S3", "S4", "楼梯/持续不确定\n/方向冲突", 0, -22, C_ACC)
    edge("S3", "S5", "5 s 保持窗口到期", 0, -22, C_GREEN)
    edge("S5", "S1", "连续 2 帧安全\n→ 恢复播报", 0, -22, C_GREEN)
    edge("S4", "S5", "用户确认后可继续", 0, -22)
    edge("S1", "S6", "closest ≥ goal", 0, -22, C_BLUE)

    # 图例
    lx, ly = 120, 830
    rounded(d, (lx - 20, ly - 20, lx + 1000, ly + 130), 12, (248, 249, 252), C_EDGE, 2)
    d.text((lx, ly), "关键设计：", font=f_box, fill=C_INK)
    notes = [
        "· 双通道独立节流（700 ms / 1000 ms），互不阻塞，避免单一长耗时请求拖垮整条链路；",
        "· 仲裁器只做“何时播报、何时闭嘴”，不修改任一模型的原始输出，保持可解释与可回退；",
        "· 一切不确定（超时、冲突、楼梯、unknown）一律降级为“停下确认”，安全优先于流畅。",
    ]
    for i, s in enumerate(notes):
        d.text((lx, ly + 38 + i * 28), s, font=f_small, fill=C_INK)

    p = os.path.join(OUT, "fig2_arbitration.png")
    img.save(p, dpi=(200, 200))
    print("saved", p)


# ============================================================
# 图 3 端到端时延实测（条形 + 分布）
# ============================================================
def fig_latency():
    W, H = 1560, 860
    img = Image.new("RGB", (W, H), C_BG)
    d = ImageDraw.Draw(img)
    f_title = font(36, True)
    f = font(22)
    f_b = font(22, True)
    f_small = font(19)
    text_center(d, W // 2, 40,
                "图 3  单帧推理时延实测（RTX 4090，云端本地回环，n=56/60）", f_title)

    # 上：条形对比（实测 P50）
    rows = [
        ("NoMaD 导航（稳态 P50）", 103.7, (60, 140, 100)),
        ("NoMaD 导航（P95）", 116.6, (120, 180, 140)),
        ("YOSO 避障（稳态 P50）", 49.7, (86, 130, 190)),
        ("YOSO 避障（P95）", 61.7, (150, 180, 215)),
        ("YOSO 寻物", 41.0, (150, 120, 60)),
        ("YOSO 环境描述", 44.0, (170, 140, 80)),
    ]
    x0, y0 = 420, 110
    maxw = 720
    mx = max(r[1] for r in rows)
    for i, (label, ms, color) in enumerate(rows):
        y = y0 + i * 66
        d.text((30, y + 8), label, font=f, fill=C_INK)
        w = int(maxw * ms / mx)
        d.rectangle((x0, y, x0 + w, y + 42), fill=color, outline=C_EDGE)
        d.text((x0 + w + 14, y + 8), f"{ms} ms", font=f_b, fill=C_INK)

    # 下：关键结论
    y = y0 + len(rows) * 66 + 20
    d.line([(30, y), (W - 30, y)], fill=C_EDGE, width=2)
    y += 24
    d.text((30, y), "关键结论", font=font(26, True), fill=C_ACC)
    notes = [
        "· NoMaD 导航 P50 = 103.7 ms（P95 = 116.6 ms，σ = 6.9 ms），两轮独立复测一致（103.8 ms）。",
        "· 原估算值 443 ms 高估 76.6%；主要偏差来自网络段与扩散去噪的保守估计。",
        "· 导航帧间隔 700 ms，推理仅占 14.8%，链路余量充足；避障 1 000 ms 周期下 YOSO 占 5.0%。",
        "· 首帧需累积 4 帧上下文（warming_up），耗时 17.7–21.6 ms，稳态后进入 90–118 ms 区间。",
        "· 注：本测为服务器本地回环，未含公网 RTT 与手机端采集/编码；公网场景需叠加 30–80 ms。",
    ]
    for i, s in enumerate(notes):
        d.text((30, y + 40 + i * 34), s, font=f_small, fill=C_INK)

    p = os.path.join(OUT, "fig3_latency.png")
    img.save(p, dpi=(200, 200))
    print("saved", p)


if __name__ == "__main__":
    fig_architecture()
    fig_state_machine()
    fig_latency()
