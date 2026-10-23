# -*- coding: utf-8 -*-
"""E2 导航成功率与节点跟踪准确率实验（exp_navigation_replay）。

核心思路：不需要真人行走，把录制好的拓扑图节点按顺序重放给云端，
统计系统能否正确跟踪节点、能否到达目标、方向判断是否合理。
这个实验完全客观、可复现，审稿人无法质疑主观性。

用法：
    # 单条路线
    python exp_navigation_replay.py --service http://127.0.0.1:8000 \
        --map-id <云端map_id> --map-dir /path/to/local/map --out results/nav_routeA.json

    # 批量跑多条路线
    python exp_navigation_replay.py --service http://127.0.0.1:8000 \
        --batch batch.json --out results/nav_all.json

batch.json 格式：
[
  {"name": "routeA_01", "map_id": "xxx", "map_dir": "/path/a01"},
  {"name": "routeA_02", "map_id": "yyy", "map_dir": "/path/a02"}
]

输出的核心指标：
  - arrival_rate: 重放完最后一个节点时，系统是否报 arrived
  - node_tracking_accuracy: 系统报的 current_node 与实际重放节点的一致率
  - node_tracking_lag: 系统跟踪滞后的节点数（均值和分布）
  - direction_sequence: 完整方向序列（供仲裁器消融复用）
  - early_arrival_rate: 是否在到达终点前就误报 arrived
  - regression_rate: current_node 是否出现回退（非单调）
"""
import argparse
import io
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request
import uuid
from collections import Counter


def _auth(token):
    return {"Authorization": f"Bearer {token}"} if token else {}


def http_json(url, method="GET", payload=None, headers=None, timeout=60):
    data = None
    hdrs = dict(headers or {})
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"_raw": raw[:400]}


def post_file(url, content, token="", timeout=90):
    boundary = "----nav" + uuid.uuid4().hex
    body = io.BytesIO()
    body.write(f"--{boundary}\r\n".encode())
    body.write(b'Content-Disposition: form-data; name="file"; filename="f.jpg"\r\n')
    body.write(b"Content-Type: image/jpeg\r\n\r\n")
    body.write(content)
    body.write(f"\r\n--{boundary}--\r\n".encode())
    hdrs = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=body.getvalue(), headers=hdrs, method="POST")
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
            code = r.status
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        code = e.code
    dt = (time.perf_counter() - t0) * 1000
    try:
        return code, json.loads(raw), dt
    except Exception:
        return code, {"_raw": raw[:400]}, dt


def load_nodes(map_dir):
    """按序号排序加载节点文件。"""
    files = [f for f in os.listdir(map_dir)
             if f.lower().endswith((".jpg", ".jpeg", ".png")) and f.split(".")[0].isdigit()]
    files.sort(key=lambda x: int(x.split(".")[0]))
    return [os.path.join(map_dir, f) for f in files]


def node_name(path):
    return os.path.basename(path)


def run_one_route(service, token, map_id, map_dir, verbose=True, sleep_s=0.0):
    """重放一条路线，返回详细结果。"""
    nodes = load_nodes(map_dir)
    if len(nodes) < 3:
        return {"error": f"节点太少: {len(nodes)}"}

    dest = node_name(nodes[-1])
    code, sess = http_json(f"{service}/v1/navigation/sessions", method="POST",
                           payload={"map_id": map_id, "destination_node": dest},
                           headers=_auth(token))
    if code != 201:
        return {"error": f"创建会话失败 HTTP {code}: {sess}"}
    sid = sess["session_id"]

    records = []
    for i, path in enumerate(nodes):
        with open(path, "rb") as f:
            jpeg = f.read()
        code, body, ms = post_file(
            f"{service}/v1/navigation/sessions/{sid}/frames", jpeg, token=token)
        res = body.get("result", {}) if isinstance(body, dict) else {}
        expected = node_name(path)
        actual = res.get("current_node")
        records.append({
            "i": i,
            "expected": expected,
            "actual": actual,
            "status": res.get("status"),
            "direction": res.get("direction"),
            "rtt_ms": round(ms, 1),
            "distance_score": res.get("distance_score"),
            "match": (actual == expected),
        })
        if verbose:
            mark = "OK " if actual == expected else "XX "
            print(f"  [{i:2d}/{len(nodes)-1}] {mark} exp={expected:10s} got={str(actual):10s} "
                  f"status={str(res.get('status')):10s} dir={str(res.get('direction')):9s} {ms:.0f}ms")
        if sleep_s > 0:
            time.sleep(sleep_s)

    # ---- 指标计算 ----
    warmup = 4  # context_size + 1
    steady = [r for r in records if r["i"] >= warmup]
    total = len(steady)
    matched = sum(1 for r in steady if r["match"])

    # 节点索引映射（用于计算滞后与回退）
    idx_of = {node_name(p): i for i, p in enumerate(nodes)}

    lags, regressions = [], 0
    prev_idx = None
    for r in steady:
        if r["actual"] in idx_of:
            cur = idx_of[r["actual"]]
            lags.append(cur - r["i"])   # 负=滞后，0=准确，正=超前
            if prev_idx is not None and cur < prev_idx:
                regressions += 1
            prev_idx = cur

    # 到达判断
    final = records[-1]
    arrived = final["status"] == "arrived" or final["direction"] == "arrived"
    # 早到：在最后 10% 节点之前就报 arrived
    early_threshold = max(warmup, int(len(nodes) * 0.9))
    early_arrivals = sum(1 for r in records[:early_threshold]
                         if r["status"] == "arrived" or r["direction"] == "arrived")

    # 方向分布
    dir_counter = Counter(r["direction"] for r in steady if r["direction"])

    return {
        "map_id": map_id,
        "map_dir": map_dir,
        "n_nodes": len(nodes),
        "destination": dest,
        "session_id": sid,
        "metrics": {
            "arrival": bool(arrived),
            "node_tracking_accuracy": round(matched / total, 4) if total else None,
            "node_tracking_correct": matched,
            "node_tracking_total": total,
            "lag_mean": round(statistics.mean(lags), 2) if lags else None,
            "lag_median": round(statistics.median(lags), 2) if lags else None,
            "lag_p10": round(sorted(lags)[int(len(lags)*0.1)], 2) if lags else None,
            "lag_p90": round(sorted(lags)[min(int(len(lags)*0.9), len(lags)-1)], 2) if lags else None,
            "regressions": regressions,
            "regression_rate": round(regressions / total, 4) if total else None,
            "early_arrivals": early_arrivals,
            "direction_distribution": dict(dir_counter),
            "rtt_p50": round(statistics.median([r["rtt_ms"] for r in steady]), 1) if steady else None,
        },
        "records": records,
    }


def summarize_batch(results):
    """汇总多条路线的结果。"""
    ok = [r for r in results if "error" not in r]
    if not ok:
        return {"error": "所有路线都失败"}

    def avg(key):
        vals = [r["metrics"][key] for r in ok if r["metrics"].get(key) is not None]
        return round(statistics.mean(vals), 4) if vals else None

    arrival_rate = sum(1 for r in ok if r["metrics"]["arrival"]) / len(ok)
    return {
        "n_routes": len(ok),
        "arrival_rate": round(arrival_rate, 4),
        "node_tracking_accuracy_mean": avg("node_tracking_accuracy"),
        "lag_mean": avg("lag_mean"),
        "regression_rate_mean": avg("regression_rate"),
        "rtt_p50_mean": avg("rtt_p50"),
        "per_route": [{
            "map_id": r["map_id"],
            "n_nodes": r["n_nodes"],
            "arrival": r["metrics"]["arrival"],
            "accuracy": r["metrics"]["node_tracking_accuracy"],
            "lag_mean": r["metrics"]["lag_mean"],
            "regressions": r["metrics"]["regressions"],
        } for r in ok],
        "failed": [r for r in results if "error" in r],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--service", default="http://127.0.0.1:8000")
    ap.add_argument("--token", default="")
    ap.add_argument("--map-id", default="")
    ap.add_argument("--map-dir", default="")
    ap.add_argument("--batch", default="", help="批量 JSON 文件")
    ap.add_argument("--out", default="results/navigation.json")
    ap.add_argument("--sleep", type=float, default=0.0, help="帧间隔秒数")
    args = ap.parse_args()

    service = args.service.rstrip("/")
    code, health = http_json(f"{service}/health", headers=_auth(args.token))
    print(f"服务健康: HTTP {code}")
    if code != 200 or not health.get("inference_ready"):
        raise SystemExit("服务未就绪，无法进行导航实验")

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)

    if args.batch:
        with open(args.batch, encoding="utf-8") as f:
            routes = json.load(f)
        print(f"批量模式：{len(routes)} 条路线")
        results = []
        for i, r in enumerate(routes):
            print(f"\n===== [{i+1}/{len(routes)}] {r['name']} =====")
            res = run_one_route(service, args.token, r["map_id"], r["map_dir"],
                                sleep_s=args.sleep)
            res["name"] = r["name"]
            results.append(res)
        out = {"summary": summarize_batch(results), "routes": results,
               "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print("\n===== 汇总 =====")
        print(json.dumps(out["summary"], ensure_ascii=False, indent=2))
        print(f"\n保存 -> {args.out}")
    else:
        if not args.map_id or not args.map_dir:
            raise SystemExit("需要 --map-id 和 --map-dir，或用 --batch")
        print(f"\n单路线模式：{args.map_dir}")
        res = run_one_route(service, args.token, args.map_id, args.map_dir,
                            sleep_s=args.sleep)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=2)
        print("\n===== 指标 =====")
        print(json.dumps(res.get("metrics", res), ensure_ascii=False, indent=2))
        print(f"\n保存 -> {args.out}")


if __name__ == "__main__":
    main()
