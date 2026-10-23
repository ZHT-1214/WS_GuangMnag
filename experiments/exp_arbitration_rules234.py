# -*- coding: utf-8 -*-
"""仲裁规则 2/3/4 的定量验证（基于真实录制日志）。

对应审稿问题 2：原论文只验证了规则 1，规则 2/3/4 未触发。
本脚本从三段真实障碍录制日志中提取证据。

核心判据：
  规则 2（冲突复核）：导航方向与避障方向不同 → 应出现 TTS_OVERRIDE 让行播报
  规则 3（保持窗口）：TTS_OVERRIDE 之后 5 秒内不应出现 TTS_NAV（导航播报）
  规则 4（超时/不确定）：TTS_STOP（unknown/stairs/timeout）+ 是否恢复

参数（与 App 实现一致）：
  GUIDANCE_HOLD_MS = 5000
  OBSTACLE_CONFIRMATIONS = 2
"""
import csv
import json
import os
import statistics
from collections import Counter

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
RESULTS_DIR = os.path.join(_REPO, "data", "results")
LABELS_DIR = os.path.join(_REPO, "data", "labels")
ROUTES_DIR = os.path.join(_REPO, "data", "routes")
FIGS_DIR = os.path.join(_REPO, "figures")


LOGDIR = os.path.join(RESULTS_DIR, "arb_logs")
OUT = os.path.join(RESULTS_DIR, "arbitration_rules234.json")

GUIDANCE_HOLD_MS = 5000

# 三段场景（按时间顺序）
SESSIONS = [
    ("arb_993d66ec12224aba8d5a6aedbf9ee289_1792676955325.csv", "障碍偏左"),
    ("arb_f6b9a11c5c804e5abfc5d92cce8f0f92_1792677306070.csv", "障碍偏右"),
    ("arb_20c4a82e3d6445aaa6b88066f624af2e_1792677528900.csv", "障碍居中"),
]


def load(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                r["elapsed_ms"] = int(r["elapsed_ms"])
            except (ValueError, KeyError):
                continue
            rows.append(r)
    return rows


def analyze(path, name):
    rows = load(path)
    if not rows:
        return None

    tts_nav = [r for r in rows if r["type"] == "TTS_NAV"]
    overrides = [r for r in rows if r["type"] == "TTS_OVERRIDE"]
    stops = [r for r in rows if r["type"] == "TTS_STOP"]
    marks = [r for r in rows if r["type"] == "MANUAL"]
    nav_frames = [r for r in rows if r["type"] == "NAV_FRAME"]

    dur = (rows[-1]["elapsed_ms"] - rows[0]["elapsed_ms"]) / 1000

    # ---- 规则 2：冲突让行 ----
    override_dirs = Counter()
    for o in overrides:
        d = o["detail"].split("|")[0] if "|" in o["detail"] else "?"
        override_dirs[d] += 1

    # ---- 规则 3：让行后导航静默 ----
    # 对每次 TTS_OVERRIDE，检查其后 GUIDANCE_HOLD_MS 内是否有 TTS_NAV
    violations = 0
    hold_checks = []
    nav_times = [n["elapsed_ms"] for n in tts_nav]
    for o in overrides:
        t0 = o["elapsed_ms"]
        t1 = t0 + GUIDANCE_HOLD_MS
        # 严格窗口内的导航播报（排除同一毫秒的并发播报）
        inside = [t for t in nav_times if t0 < t < t1]
        violated = len(inside) > 0
        if violated:
            violations += 1
        hold_checks.append({
            "override_t_ms": t0,
            "override_t_s": round(t0 / 1000, 1),
            "override_dir": o["detail"].split("|")[0] if "|" in o["detail"] else "?",
            "nav_inside_hold": violated,
            "nav_times_inside": [round(t / 1000, 1) for t in inside],
        })

    compliant = len(overrides) - violations

    # 让行后的导航静默时长（到下一次导航播报的间隔）
    silences = []
    for o in overrides:
        t0 = o["elapsed_ms"]
        nxt = [t for t in nav_times if t > t0]
        if nxt:
            silences.append((min(nxt) - t0) / 1000)

    # ---- 规则 4：stop 事件 ----
    stop_details = [{"t_s": round(s["elapsed_ms"] / 1000, 1), "detail": s["detail"]}
                    for s in stops]

    # ---- 帧率 ----
    frame_intervals = []
    ft = [r["elapsed_ms"] for r in nav_frames]
    for i in range(1, len(ft)):
        frame_intervals.append((ft[i] - ft[i - 1]) / 1000)

    # ---- 人工标记 ----
    mark_list = [{"t_s": round(m["elapsed_ms"] / 1000, 1), "label": m["detail"]}
                 for m in marks]

    return {
        "session": name,
        "file": path,
        "duration_s": round(dur, 1),
        "n_events": len(rows),
        "n_nav_frames": len(nav_frames),
        "frame_rate_fps": round(1 / statistics.median(frame_intervals), 2)
        if frame_intervals else None,
        "rule2_conflict_overrides": len(overrides),
        "rule2_override_directions": dict(override_dirs),
        "rule3_hold_checks": len(overrides),
        "rule3_violations": violations,
        "rule3_compliance_rate": round(compliant / len(overrides), 4) if overrides else None,
        "rule3_nav_silence_median_s": round(statistics.median(silences), 1) if silences else None,
        "rule3_nav_silence_min_s": round(min(silences), 1) if silences else None,
        "rule3_nav_silence_max_s": round(max(silences), 1) if silences else None,
        "rule4_stop_events": len(stops),
        "rule4_stop_details": stop_details,
        "n_nav_announcements": len(tts_nav),
        "manual_marks": mark_list,
        "hold_checks_detail": hold_checks,
    }


def main():
    print("=" * 80)
    print("仲裁规则 2/3/4 定量验证")
    print("=" * 80)

    results = []
    for fname, label in SESSIONS:
        path = os.path.join(LOGDIR, fname)
        if not os.path.exists(path):
            print(f"缺少 {fname}")
            continue
        r = analyze(path, label)
        if r:
            results.append(r)

    if not results:
        raise SystemExit("无可用日志")

    # 汇总
    total_overrides = sum(r["rule2_conflict_overrides"] for r in results)
    total_violations = sum(r["rule3_violations"] for r in results)
    total_checks = sum(r["rule3_hold_checks"] for r in results)
    total_stops = sum(r["rule4_stop_events"] for r in results)
    total_frames = sum(r["n_nav_frames"] for r in results)
    total_dur = sum(r["duration_s"] for r in results)

    print(f"\n{'场景':<10}{'时长':>7}{'帧数':>6}{'帧率':>7}"
          f"{'规则2':>7}{'规则3违规':>10}{'合规率':>9}{'规则4':>7}")
    print("-" * 80)
    for r in results:
        print(f"{r['session']:<10}{r['duration_s']:>6.0f}s{r['n_nav_frames']:>6}"
              f"{r['frame_rate_fps']:>6.1f}{r['rule2_conflict_overrides']:>7}"
              f"{r['rule3_violations']:>10}"
              f"{(r['rule3_compliance_rate'] or 0)*100:>8.0f}%"
              f"{r['rule4_stop_events']:>7}")

    print("\n" + "=" * 80)
    print("汇总")
    print("=" * 80)
    print(f"  总时长              : {total_dur:.0f} s")
    print(f"  总导航帧            : {total_frames}")
    print(f"  平均帧率            : {total_frames/total_dur:.2f} fps")
    print(f"")
    print(f"  规则 2 冲突让行次数 : {total_overrides}")
    print(f"  规则 3 保持窗口检查 : {total_checks} 次")
    print(f"  规则 3 违规次数     : {total_violations}")
    print(f"  规则 3 合规率       : {(total_checks-total_violations)/total_checks*100:.1f}%"
          if total_checks else "  N/A")
    print(f"  规则 4 降级触发     : {total_stops} 次")

    # 让行方向分布
    alldirs = Counter()
    for r in results:
        for d, c in r["rule2_override_directions"].items():
            alldirs[d] += c
    print(f"\n  让行方向分布: {dict(alldirs)}")

    # 静默时长
    sil = [r["rule3_nav_silence_median_s"] for r in results if r["rule3_nav_silence_median_s"]]
    if sil:
        print(f"  让行后导航静默中位数: {statistics.mean(sil):.1f} s（各场景 {sil}）")

    out = {
        "meta": {
            "description": "Real-recording validation of arbitration rules 2/3/4",
            "hold_window_ms": GUIDANCE_HOLD_MS,
            "n_sessions": len(results),
            "total_duration_s": round(total_dur, 1),
            "total_nav_frames": total_frames,
        },
        "summary": {
            "rule2_conflict_overrides": total_overrides,
            "rule2_override_directions": dict(alldirs),
            "rule3_checks": total_checks,
            "rule3_violations": total_violations,
            "rule3_compliance_rate": round((total_checks - total_violations) / total_checks, 4)
            if total_checks else None,
            "rule4_stop_events": total_stops,
        },
        "sessions": results,
    }
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\n保存 -> {OUT}")


if __name__ == "__main__":
    main()
