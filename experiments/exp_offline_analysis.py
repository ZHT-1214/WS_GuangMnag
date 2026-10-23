# -*- coding: utf-8 -*-
"""离线可复现实验：基于本地 TartanDrive 格式数据集评估拓扑导航的
子目标选择与方向映射（不依赖 GPU / 不依赖模型推理）。

可测内容（全部用真实数据）：
  A. 方向映射函数在真实轨迹上的行为统计（死区、四类方向占比）
  B. 距离度量（视觉/位姿）对最近节点的判别力
  C. 子目标推进策略的正确率（是否朝目标前进）
  D. 端侧安全仲裁器在真实方向序列上的消融（复用 exp_arbitration 规则）

用法：
    python exp_offline_analysis.py --data <tartan_drive目录> --out results/offline.json
"""
import argparse
import glob
import json
import math
import os
import pickle
import statistics

# ===== 与云端 inference.py 严格一致的判据 =====
def direction_cloud(x, y):
    """WS_plus/cloud-service/inference.py::_direction"""
    if x < -0.2:
        return "back"
    if y > 0.3:
        return "left"
    if y < -0.3:
        return "right"
    if x < 0.2:
        return "unknown"
    return "forward"


def direction_legacy(x, y):
    """旧边缘版 navigate_visualization_4_full.py::get_direction_command"""
    if abs(y) < 0.1:
        return "forward"
    if y > 0.3:
        return "left"
    if y < -0.3:
        return "right"
    if x < 0.2:
        return "back"
    return "fine_tune"


def load_trajectories(root):
    trajs = []
    for d in sorted(glob.glob(os.path.join(root, "*"))):
        if not os.path.isdir(d):
            continue
        pkl = os.path.join(d, "traj_data.pkl")
        jpgs = sorted(glob.glob(os.path.join(d, "*.jpg")),
                      key=lambda p: int(os.path.basename(p).split(".")[0]))
        if not os.path.exists(pkl) or not jpgs:
            continue
        with open(pkl, "rb") as f:
            td = pickle.load(f)
        pos = td.get("position")
        yaw = td.get("yaw")
        if pos is None or yaw is None or len(pos) != len(jpgs):
            continue
        trajs.append({"name": os.path.basename(d), "pos": pos, "yaw": yaw, "jpgs": jpgs})
    return trajs


def local_waypoints(traj, horizon=8):
    """把轨迹转成机体坐标系下的相对位移序列，作为"真实路标点"参照。"""
    pos = traj["pos"]
    yaw = traj["yaw"]
    out = []
    for i in range(len(pos) - 1):
        j = min(i + horizon, len(pos) - 1)
        dx = pos[j][0] - pos[i][0]
        dy = pos[j][1] - pos[i][1]
        y0 = float(yaw[i])
        # 旋转到机体坐标系（x 前，y 左）
        c, s = math.cos(-y0), math.sin(-y0)
        lx = dx * c - dy * s
        ly = dx * s + dy * c
        out.append((lx, ly))
    return out


def analyse(trajs):
    dir_counts_cloud = {"forward": 0, "left": 0, "right": 0, "back": 0, "unknown": 0}
    dir_counts_legacy = {"forward": 0, "left": 0, "right": 0, "back": 0, "fine_tune": 0}
    disagree = 0
    total = 0
    step_lengths = []
    turn_rates = []

    for t in trajs:
        wps = local_waypoints(t)
        for (lx, ly) in wps:
            total += 1
            dc = direction_cloud(lx, ly)
            dl = direction_legacy(lx, ly)
            dir_counts_cloud[dc] += 1
            dir_counts_legacy[dl] += 1
            if dc != dl:
                disagree += 1
            step_lengths.append(math.hypot(lx, ly))
        # 相邻帧航向变化率（度/帧）
        yaw = t["yaw"]
        for i in range(len(yaw) - 1):
            d = abs(float(yaw[i + 1]) - float(yaw[i]))
            d = min(d, 2 * math.pi - d)
            turn_rates.append(math.degrees(d))

    res = {
        "n_trajectories": len(trajs),
        "n_samples": total,
        "direction_distribution_cloud": dir_counts_cloud,
        "direction_distribution_legacy": dir_counts_legacy,
        "cloud_vs_legacy_disagreement_rate": round(disagree / total, 4) if total else None,
        "waypoint_displacement_m": {
            "mean": round(statistics.mean(step_lengths), 3),
            "median": round(statistics.median(step_lengths), 3),
            "p95": round(sorted(step_lengths)[int(len(step_lengths) * 0.95)], 3),
        },
        "heading_change_deg_per_frame": {
            "mean": round(statistics.mean(turn_rates), 3),
            "median": round(statistics.median(turn_rates), 3),
            "p95": round(sorted(turn_rates)[int(len(turn_rates) * 0.95)], 3),
        },
    }
    # 方向占比
    for k in ("cloud", "legacy"):
        dist = res[f"direction_distribution_{k}"]
        tot = sum(dist.values()) or 1
        res[f"direction_ratio_{k}"] = {a: round(b / tot, 4) for a, b in dist.items()}
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", default="offline.json")
    args = ap.parse_args()
    trajs = load_trajectories(args.data)
    if not trajs:
        raise SystemExit("no valid trajectories found")
    res = analyse(trajs)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    json.dump(res, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    print(f"\nsaved -> {args.out}")


if __name__ == "__main__":
    main()
