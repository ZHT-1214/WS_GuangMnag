# -*- coding: utf-8 -*-
"""实验脚本框架：导航成功率评测（exp_navigation）。

对一次导航会话的全过程打点：起点、目标节点、到达与否、用时、
停车次数（由 App 端仲裁器 stop 事件累计）、每帧方向序列。
真机侧由 App 日志导出 trace JSON 后运行本脚本汇总。

用法：
    python exp_navigation.py --traces traces/ --out summary.json
"""
import argparse
import glob
import json
import os
import statistics


def summarize_trace(path):
    t = json.load(open(path, encoding="utf-8"))
    nav = t.get("nav") or []
    stops = t.get("stops", 0)
    duration = (t.get("t") or [0])[-1]
    arrived = bool(t.get("arrived", nav and nav[-1] == "arrived"))
    return {
        "file": os.path.basename(path),
        "arrived": arrived,
        "duration_s": round(duration, 1),
        "frames": len(nav),
        "stops": stops,
        "route": t.get("route", ""),
        "condition": t.get("condition", ""),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--traces", required=True, help="包含 trace JSON 的目录")
    ap.add_argument("--out", default="summary.json")
    args = ap.parse_args()

    files = sorted(glob.glob(os.path.join(args.traces, "*.json")))
    if not files:
        raise SystemExit(f"no traces found in {args.traces}")
    rows = [summarize_trace(f) for f in files]

    by_cond = {}
    for r in rows:
        by_cond.setdefault(r["condition"], []).append(r)

    summary = {}
    for cond, rs in by_cond.items():
        n = len(rs)
        arrived = sum(1 for r in rs if r["arrived"])
        summary[cond] = {
            "n": n,
            "success_rate": round(arrived / n, 3) if n else 0.0,
            "median_duration_s": round(statistics.median([r["duration_s"] for r in rs]), 1) if n else None,
            "mean_stops": round(statistics.mean([r["stops"] for r in rs]), 2) if n else None,
        }

    out = {"per_trace": rows, "summary_by_condition": summary}
    json.dump(out, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
