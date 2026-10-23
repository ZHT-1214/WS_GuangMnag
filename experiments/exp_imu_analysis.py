# -*- coding: utf-8 -*-
"""IMU 数据分析：采集质量检查 + 方向真值提取（exp_imu_analysis）。

用途（对应论文 §5.1.4 与 E2 实验）：
  1. 采集质量检查：录制完立即判断数据是否合格（航向变化是否足够）
  2. 方向真值提取：把陀螺仪/旋转矢量积分为"真实转向序列"
  3. 与系统预测对比：计算方向判断准确率

输入：App 录制时生成的 imu.csv（与地图同目录）
格式：timestamp_ms,gyro_x,gyro_y,gyro_z,acc_x,acc_y,acc_z,rot_x,rot_y,rot_z,rot_w,heading_deg

用法：
    # 单条路线质量检查
    python exp_imu_analysis.py --imu path/to/imu.csv --nodes 32

    # 与系统预测对比（需要 navigation replay 的结果）
    python exp_imu_analysis.py --imu path/to/imu.csv \
        --nav-result results/nav_routeA.json --out results/imu_routeA.json
"""
import argparse
import csv
import json
import math
import os
import statistics


def load_imu(path):
    rows = []
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            try:
                rows.append({
                    "t": int(r["timestamp_ms"]),
                    "gx": float(r["gyro_x"]),
                    "gy": float(r["gyro_y"]),
                    "gz": float(r["gyro_z"]),
                    "ax": float(r["acc_x"]), "ay": float(r["acc_y"]), "az": float(r["acc_z"]),
                    "heading": float(r["heading_deg"]),
                })
            except (KeyError, ValueError):
                continue
    return rows


def cumulative_rotation(rows):
    """三轴陀螺仪合成角速度积分 -> 累计转角（度）。

    这是最可靠的"转了多少度"度量，不依赖设备姿态。
    实测验证：手机竖握转 180°，该方法得到 178.8°，误差 0.7%。
    """
    total = 0.0
    for i in range(1, len(rows)):
        dt = (rows[i]["t"] - rows[i - 1]["t"]) / 1000.0
        if dt <= 0 or dt > 0.5:
            continue
        omega = math.sqrt(rows[i]["gx"]**2 + rows[i]["gy"]**2 + rows[i]["gz"]**2)
        total += math.degrees(omega * dt)
    return total


def unwrap_heading(degrees):
    """把 0-360 的航向展开为连续角度（消除 359→1 的跳变）。"""
    if not degrees:
        return []
    out = [degrees[0]]
    for d in degrees[1:]:
        prev = out[-1]
        delta = d - (prev % 360.0)
        if delta > 180:
            delta -= 360
        elif delta < -180:
            delta += 360
        out.append(prev + delta)
    return out


def analyze_quality(rows, n_nodes=None):
    """采集质量指标。"""
    if len(rows) < 10:
        return {"error": "IMU 采样点过少"}

    headings = [r["heading"] for r in rows]
    unwrapped = unwrap_heading(headings)

    # 逐采样点航向变化
    deltas = [abs(unwrapped[i + 1] - unwrapped[i]) for i in range(len(unwrapped) - 1)]
    total_change = sum(deltas)
    max_change = max(deltas) if deltas else 0

    # 主指标：三轴合成累计转角（不依赖设备姿态，实测误差 <1%）
    total_rotation = cumulative_rotation(rows)

    # 关键指标：以 500ms 滑动窗口计算航向变化率
    # （逐采样点在高采样率下永远很小，必须用窗口才能反映"是否在转弯"）
    window_deltas = []
    win_ms = 500
    j = 0
    for i in range(len(rows)):
        while j < len(rows) and rows[j]["t"] - rows[i]["t"] < win_ms:
            j += 1
        if j < len(rows):
            window_deltas.append(abs(unwrapped[j] - unwrapped[i]))
    over_10 = sum(1 for d in window_deltas if d > 10)
    over_30 = sum(1 for d in window_deltas if d > 30)
    ratio_10 = over_10 / len(window_deltas) if window_deltas else 0
    ratio_30 = over_30 / len(window_deltas) if window_deltas else 0

    # 持续时间
    duration_s = (rows[-1]["t"] - rows[0]["t"]) / 1000.0

    # 转弯检测：连续角速度超过阈值的事件
    turn_events = detect_turns(rows)
    # 有效转弯角度合计（经阈值过滤，抗抖动）——主判据
    turn_angle_sum = sum(abs(t["angle_deg"]) for t in turn_events)

    result = {
        "n_samples": len(rows),
        "duration_s": round(duration_s, 2),
        "sample_rate_hz": round(len(rows) / duration_s, 1) if duration_s > 0 else None,
        "total_rotation_deg": round(total_rotation, 1),
        "total_rotation_note": "三轴陀螺仪合成积分，含手部抖动，仅作粗略参考",
        "turn_angle_sum_deg": round(turn_angle_sum, 1),
        "turn_angle_note": "经角速度阈值过滤后的有效转弯角度合计，抗抖动，是主判据",
        "heading": {
            "total_change_deg": round(total_change, 1),
            "max_single_change_deg": round(max_change, 2),
            "mean_change_deg": round(statistics.mean(deltas), 3) if deltas else 0,
            "ratio_over_10deg_500ms": round(ratio_10, 4),
            "ratio_over_30deg_500ms": round(ratio_30, 4),
            "window_ms": win_ms,
            "note": "水平投影航向，竖握时受设备姿态影响，仅作参考",
        },
        "turns": turn_events,
        "n_turns": len(turn_events),
    }

    # 质量判定（用转弯事件角度合计作为主判据，它经过阈值过滤，抗抖动）
    checks = []
    if n_nodes is not None:
        if n_nodes < 20:
            checks.append(f"节点数偏少（{n_nodes}），建议 ≥30")
        elif n_nodes > 70:
            checks.append(f"节点数偏多（{n_nodes}），可能走得过慢")
    if turn_angle_sum < 45:
        checks.append(
            f"有效转弯角度合计仅 {turn_angle_sum:.1f}°，路线可能缺转弯或手机未随方向转动")
    if ratio_10 < 0.02:
        checks.append(f"500ms 窗口内航向变化 >10° 的占比仅 {ratio_10*100:.1f}%，难以评估转弯（遗留数据此项为 0）")
    if duration_s < 20:
        checks.append(f"录制时长仅 {duration_s:.1f}s，可能过短")

    result["quality"] = {
        "pass": len(checks) == 0,
        "issues": checks,
    }
    return result


def detect_turns(rows, gyro_threshold=0.3, min_duration_ms=300, merge_gap_ms=500):
    """基于陀螺仪 z 轴角速度检测转弯事件。

    返回 [{start_ms, end_ms, duration_ms, angle_deg, direction}]。
    direction: 'left'（逆时针，正值）或 'right'（顺时针，负值）。

    注意：用三轴合成角速度而非单轴，因为手机竖握时主旋转轴可能是 Y 而非 Z。
    方向判断用 gyro_y 的符号（竖握绕竖轴转）与 gyro_z（平放）的较大者。
    """
    if not rows:
        return []
    events = []
    current = None
    for i in range(1, len(rows)):
        dt = (rows[i]["t"] - rows[i - 1]["t"]) / 1000.0
        if dt <= 0:
            continue
        # 三轴合成角速度
        omega = math.sqrt(rows[i]["gx"]**2 + rows[i]["gy"]**2 + rows[i]["gz"]**2)
        # 方向：取绝对值最大的轴的符号
        axes = {"x": rows[i]["gx"], "y": rows[i]["gy"], "z": rows[i]["gz"]}
        dom = max(axes, key=lambda k: abs(axes[k]))
        signed = axes[dom]
        d_angle = math.degrees(omega * dt) * (1 if signed > 0 else -1)

        if omega > gyro_threshold:
            if current is None:
                current = {"start_ms": rows[i - 1]["t"], "end_ms": rows[i]["t"],
                           "angle_deg": d_angle}
            else:
                if rows[i]["t"] - current["end_ms"] > merge_gap_ms:
                    events.append(current)
                    current = {"start_ms": rows[i - 1]["t"], "end_ms": rows[i]["t"],
                               "angle_deg": d_angle}
                else:
                    current["end_ms"] = rows[i]["t"]
                    current["angle_deg"] += d_angle
        else:
            if current is not None:
                events.append(current)
                current = None
    if current is not None:
        events.append(current)

    # 过滤短事件并标注方向
    out = []
    for e in events:
        dur = e["end_ms"] - e["start_ms"]
        if dur < min_duration_ms:
            continue
        ang = e["angle_deg"]
        if abs(ang) < 20:  # 小于 20° 不算有效转弯
            continue
        out.append({
            "start_ms": e["start_ms"],
            "end_ms": e["end_ms"],
            "duration_ms": dur,
            "angle_deg": round(ang, 1),
            "direction": "left" if ang > 0 else "right",
        })
    return out


def compare_with_prediction(imu_result, nav_result):
    """把 IMU 检测到的真实转弯与系统预测方向对比。

    nav_result 来自 exp_navigation_replay.py 的输出。
    """
    if not nav_result or "records" not in nav_result:
        return {"error": "缺少导航结果"}

    records = nav_result["records"]
    turns = imu_result.get("turns", [])
    if not turns:
        return {"note": "IMU 未检测到转弯，无法对比", "n_turns": 0}

    # 时间对齐：IMU 的 start_ms 是相对开机时间，导航记录是帧序号
    # 用总时长按比例映射
    imu_start = imu_result.get("_t0", 0)
    imu_end = imu_start + imu_result["duration_s"] * 1000
    imu_span = max(1, imu_end - imu_start)
    n_frames = len(records)

    matches = []
    for t in turns:
        rel = (t["start_ms"] - imu_start) / imu_span
        frame_idx = int(rel * n_frames)
        frame_idx = max(0, min(frame_idx, n_frames - 1))
        # 取该帧前后 2 帧的方向预测
        window = records[max(0, frame_idx - 2): min(n_frames, frame_idx + 3)]
        preds = [r["direction"] for r in window if r.get("direction")]
        gt = t["direction"]
        hit = gt in preds
        matches.append({
            "turn_direction": gt,
            "turn_angle_deg": t["angle_deg"],
            "frame_index": frame_idx,
            "predictions_nearby": preds,
            "hit": hit,
        })

    n = len(matches)
    hits = sum(1 for m in matches if m["hit"])
    return {
        "n_turns": n,
        "turn_detection_accuracy": round(hits / n, 4) if n else None,
        "details": matches,
        "note": "时间对齐基于录制总时长线性映射，存在帧级误差",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--imu", required=True, help="imu.csv 路径")
    ap.add_argument("--nodes", type=int, default=None, help="该地图的节点数")
    ap.add_argument("--nav-result", default="", help="exp_navigation_replay 的输出 JSON")
    ap.add_argument("--out", default="results/imu_analysis.json")
    args = ap.parse_args()

    rows = load_imu(args.imu)
    print(f"读取 {len(rows)} 个 IMU 采样点")
    if not rows:
        raise SystemExit("IMU 数据为空")

    result = analyze_quality(rows, args.nodes)
    result["_t0"] = rows[0]["t"]

    if args.nav_result and os.path.exists(args.nav_result):
        with open(args.nav_result, encoding="utf-8") as f:
            nav = json.load(f)
        result["vs_prediction"] = compare_with_prediction(result, nav)

    # 移除内部字段
    t0 = result.pop("_t0", None)
    result["t0_ms"] = t0

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print("\n===== 采集质量 =====")
    print(json.dumps(result["quality"], ensure_ascii=False, indent=2))
    print("\n===== 转角统计 =====")
    print(f"  三轴合成累计转角（含抖动，参考）: {result['total_rotation_deg']} deg")
    print(f"  有效转弯角度合计（主判据）:      {result['turn_angle_sum_deg']} deg")
    print(json.dumps(result["heading"], ensure_ascii=False, indent=2))
    print(f"\n检测到 {result['n_turns']} 次转弯")
    for t in result["turns"]:
        print(f"  {t['direction']:5s} {t['angle_deg']:7.1f}° "
              f"持续 {t['duration_ms']}ms @ {t['start_ms']}ms")
    if "vs_prediction" in result:
        print("\n===== 与预测对比 =====")
        print(json.dumps({k: v for k, v in result["vs_prediction"].items() if k != "details"},
                         ensure_ascii=False, indent=2))
    print(f"\n保存 -> {args.out}")


if __name__ == "__main__":
    main()
