# -*- coding: utf-8 -*-
"""跨会话导航评测（使用 DTW 真值）。

背景（对应审稿问题 1）：原 E2 用拓扑图自身的节点图重放查询同一张拓扑图，
属于"自测自"，100% 到达率无信息量。本实验用**不同会话、不同光照、不同节点数**
重录的路线作为查询帧，检验真实使用场景（今天走的路 vs 昨天建图）下的泛化能力。

真值来源：DTW 单调对齐（见 build_cross_session_gt.py）
  - 朴素最近邻在长走廊会非单调跳动，不可用
  - DTW 强制路径单调递增，是 VT&R 领域标准做法

API 路径（依据 /openapi.json）：
  GET  /v1/maps
  POST /v1/navigation/sessions
  POST /v1/navigation/sessions/{session_id}/frames
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
from pathlib import Path


def http_json(url, method="GET", payload=None, headers=None, timeout=120):
    data = None
    hdrs = dict(headers or {})
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", "replace")
            code = r.status
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        code = e.code
    dt = (time.perf_counter() - t0) * 1000
    try:
        parsed = json.loads(body)
    except Exception:
        parsed = {"_raw": body[:500]}
    return code, parsed, dt


def post_frame(url, jpeg, token="", timeout=120):
    """提交帧到 /v1/navigation/sessions/{sid}/frames（multipart）。"""
    boundary = "----wsplus" + uuid.uuid4().hex
    body = io.BytesIO()
    body.write(f"--{boundary}\r\n".encode())
    body.write(b'Content-Disposition: form-data; name="file"; filename="f.jpg"\r\n')
    body.write(b"Content-Type: image/jpeg\r\n\r\n")
    body.write(jpeg)
    body.write(f"\r\n--{boundary}--\r\n".encode())
    raw = body.getvalue()
    hdrs = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=raw, headers=hdrs, method="POST")
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            txt = r.read().decode("utf-8", "replace")
            code = r.status
    except urllib.error.HTTPError as e:
        txt = e.read().decode("utf-8", "replace")
        code = e.code
    dt = (time.perf_counter() - t0) * 1000
    try:
        parsed = json.loads(txt)
    except Exception:
        parsed = {"_raw": txt[:300]}
    return code, parsed, dt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--service", default="http://127.0.0.1:8000")
    ap.add_argument("--token", default="")
    ap.add_argument("--map-id", required=True)
    ap.add_argument("--query-dir", required=True)
    ap.add_argument("--gt", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    hdrs = {"Authorization": f"Bearer {args.token}"} if args.token else {}

    # ---- 参考地图（GET /v1/maps）----
    code, maps, _ = http_json(f"{args.service}/v1/maps", headers=hdrs)
    if code != 200:
        raise SystemExit(f"读取地图列表失败: {code} {maps}")
    target = None
    for m in (maps if isinstance(maps, list) else maps.get("maps", [])):
        if m.get("map_id") == args.map_id or m.get("id") == args.map_id:
            target = m
            break
    if not target:
        print("可用地图:")
        for m in (maps if isinstance(maps, list) else maps.get("maps", [])):
            print(f"  {m.get('map_id') or m.get('id')}: {m.get('name')} "
                  f"({len(m.get('nodes', []))} 节点)")
        raise SystemExit(f"地图 {args.map_id} 不存在")

    ref_nodes = target.get("nodes") or []
    n_ref = len(ref_nodes)
    # 节点可能是字符串或对象
    node_names = [nd if isinstance(nd, str) else nd.get("name") for nd in ref_nodes]
    name2idx = {nm: k for k, nm in enumerate(node_names)}
    print(f"参考地图: {n_ref} 节点，目标 {node_names[-1]}")

    # ---- 真值 ----
    gt = json.load(open(args.gt, encoding="utf-8"))
    gt_map = {r["query_frame"]: r for r in gt["records"]}
    print(f"真值: {len(gt_map)} 帧，覆盖 {gt['meta']['coverage']*100:.0f}%")

    # ---- 查询帧 ----
    qdir = Path(args.query_dir)
    qfiles = sorted([p for p in qdir.iterdir()
                     if p.suffix.lower() in (".jpg", ".jpeg", ".png") and p.stem.isdigit()],
                    key=lambda p: int(p.stem))
    print(f"查询帧: {len(qfiles)}")

    # ---- 建会话 ----
    code, sess, _ = http_json(
        f"{args.service}/v1/navigation/sessions", method="POST",
        payload={"map_id": args.map_id, "destination_node": node_names[-1]},
        headers=hdrs)
    if code not in (200, 201):
        raise SystemExit(f"建会话失败: {code} {sess}")
    sid = sess.get("session_id") or sess.get("id")
    print(f"会话: {sid}\n")

    frame_url = f"{args.service}/v1/navigation/sessions/{sid}/frames"

    records = []
    for i, f in enumerate(qfiles):
        code, resp, dt = post_frame(frame_url, f.read_bytes(), token=args.token)
        # 响应结构：{"status":"ok", "inference_ready":bool, "result":{...}}
        inner = resp.get("result") if isinstance(resp.get("result"), dict) else resp
        cur = inner.get("current_node")
        idx = name2idx.get(cur) if cur else None
        g = gt_map.get(f.name)
        records.append({
            "i": i, "file": f.name,
            "http": code,
            "pred_node": cur, "pred_index": idx,
            "pred_progress": round(idx / max(n_ref - 1, 1), 4) if idx is not None else None,
            "gt_node": g["gt_ref_node"] if g else None,
            "gt_progress": g["gt_ref_progress"] if g else None,
            "direction": inner.get("direction"),
            "status": inner.get("status"),
            "rtt_ms": round(dt, 1),
        })
        if i % 10 == 0 or i == len(qfiles) - 1:
            r = records[-1]
            pp = "None" if r["pred_progress"] is None else f"{r['pred_progress']:.2f}"
            gp = "None" if r["gt_progress"] is None else f"{r['gt_progress']:.2f}"
            print(f"  [{i:2d}] http={code} pred={pp} gt={gp} "
                  f"node={cur} {r['direction']} {r['status']}")

    # ---- 统计 ----
    valid = [r for r in records
             if r["pred_progress"] is not None and r["gt_progress"] is not None]
    print(f"\n有效判定: {len(valid)}/{len(records)}")

    errs = [abs(r["pred_progress"] - r["gt_progress"]) for r in valid]
    signed = [r["pred_progress"] - r["gt_progress"] for r in valid]
    seq = [r["pred_progress"] for r in valid]
    regressions = sum(1 for k in range(1, len(seq)) if seq[k] < seq[k - 1] - 0.05)
    arrived = sum(1 for r in records if r["status"] == "arrived")
    last = records[-1] if records else {}

    summary = {
        "map_id": args.map_id,
        "n_ref_nodes": n_ref,
        "n_query_frames": len(qfiles),
        "n_valid": len(valid),
        "valid_rate": round(len(valid) / len(records), 4) if records else 0,
        "gt_method": gt["meta"]["method"],
        "gt_coverage": gt["meta"]["coverage"],
        "gt_mean_alignment_sim": gt["meta"]["mean_alignment_sim"],
        "progress_error_median": round(statistics.median(errs), 4) if errs else None,
        "progress_error_mean": round(statistics.mean(errs), 4) if errs else None,
        "progress_error_p90": round(sorted(errs)[min(int(len(errs) * 0.9), len(errs) - 1)], 4) if errs else None,
        "signed_bias": round(statistics.mean(signed), 4) if signed else None,
        "regressions": regressions,
        "regression_rate": round(regressions / max(len(valid) - 1, 1), 4),
        "arrived_frames": arrived,
        "final_status": last.get("status"),
        "final_pred_progress": last.get("pred_progress"),
        "rtt_p50": round(statistics.median([r["rtt_ms"] for r in records]), 1) if records else None,
    }

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    json.dump({"summary": summary, "records": records},
              open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    print("\n" + "=" * 64)
    print("跨会话导航评测结果")
    print("=" * 64)
    print(f"  真值方法         : {summary['gt_method']}")
    print(f"  真值覆盖         : {summary['gt_coverage']*100:.0f}%")
    print(f"  对齐平均相似度   : {summary['gt_mean_alignment_sim']:.4f}")
    print(f"  有效判定率       : {summary['valid_rate']*100:.1f}%")
    if errs:
        print(f"  进度误差中位数   : {summary['progress_error_median']*100:.1f}%")
        print(f"  进度误差均值     : {summary['progress_error_mean']*100:.1f}%")
        print(f"  进度误差 P90     : {summary['progress_error_p90']*100:.1f}%")
        print(f"  系统性偏差       : {summary['signed_bias']*100:+.1f}%")
    else:
        print("  ⚠ 无有效判定，无法计算误差")
    print(f"  回退次数         : {regressions}")
    print(f"  到达判定帧数     : {arrived}")
    print(f"  末帧状态         : {summary['final_status']}")
    print(f"\n保存 -> {args.out}")


if __name__ == "__main__":
    main()
