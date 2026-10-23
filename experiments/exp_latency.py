# -*- coding: utf-8 -*-
"""E1 端到端时延实测（exp_latency）。

对接真实云端服务，分段测量导航帧与避障帧的往返时延。

用法（在云端服务器上跑）：
    python3 exp_latency.py --service http://127.0.0.1:8000 \
        --frames 60 --out results/latency.json

用法（从本地经 SSH 隧道跑）：
    python exp_latency.py --service http://127.0.0.1:8000 --frames 60

说明：
- 自动选择节点数最多的地图，并取中间节点作为目标。
- 真实使用该地图的节点图作为输入帧（不是随机噪声），保证推理路径真实。
- 分为"首帧（含上下文建立）"与"稳态帧"分别统计。
- 不使用 requests，避免服务器上缺包；用标准库 urllib 构造 multipart。
"""
import argparse
import io
import json
import os
import statistics
import time
import urllib.error
import urllib.request
import uuid

NAV_INTERVAL_S = 0.7
OBS_INTERVAL_S = 1.0
WARMUP_FRAMES = 4  # context_size + 1


def http_json(url, method="GET", payload=None, headers=None, timeout=60):
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


def post_file(url, filename, content, content_type="image/jpeg", token="", timeout=90):
    boundary = "----wsplus" + uuid.uuid4().hex
    body = io.BytesIO()
    body.write(f"--{boundary}\r\n".encode())
    body.write(f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode())
    body.write(f"Content-Type: {content_type}\r\n\r\n".encode())
    body.write(content)
    body.write(f"\r\n--{boundary}--\r\n".encode())
    payload = body.getvalue()

    hdrs = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=payload, headers=hdrs, method="POST")
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
        parsed = json.loads(raw)
    except Exception:
        parsed = {"_raw": raw[:500]}
    return code, parsed, dt


def pick_map(base, token):
    code, data, _ = http_json(f"{base}/v1/maps", headers=_auth(token))
    maps = [m for m in data.get("maps", []) if m.get("node_count", 0) > 0]
    if not maps:
        raise SystemExit("云端没有可用地图，请先上传")
    maps.sort(key=lambda m: -m["node_count"])
    m = maps[0]
    nodes = m["nodes"]
    dest = nodes[min(len(nodes) // 2, len(nodes) - 1)]
    return m["id"], dest, nodes


def _auth(token):
    return {"Authorization": f"Bearer {token}"} if token else {}


def load_frames(base, map_id, nodes, n, token):
    """下载地图节点图作为输入帧（从服务端读不到文件，故用本地副本）。"""
    local_dir = os.environ.get("WSPLUS_MAP_DIR", "")
    if local_dir and os.path.isdir(local_dir):
        files = sorted([os.path.join(local_dir, f) for f in os.listdir(local_dir)
                        if f.lower().endswith((".jpg", ".jpeg", ".png"))])
        if files:
            print(f"使用本地地图目录: {local_dir} ({len(files)} 帧)")
            return [open(files[i % len(files)], "rb").read() for i in range(n)]
    # 兜底：生成合成 JPEG
    try:
        from PIL import Image
    except ImportError:
        raise SystemExit("需要 Pillow 生成合成帧，或设置 WSPLUS_MAP_DIR 指向本地地图目录")
    frames = []
    for i in range(n):
        img = Image.new("RGB", (640, 480), (100 + i % 50, 120, 140))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=78)
        frames.append(buf.getvalue())
    print(f"使用合成帧 {n} 张（建议设置 WSPLUS_MAP_DIR 用真实图像）")
    return frames


def summarize(rows, key="rtt_ms"):
    vals = [r[key] for r in rows if isinstance(r.get(key), (int, float))]
    if not vals:
        return {}
    s = sorted(vals)
    return {
        "n": len(vals),
        "p50": round(statistics.median(vals), 1),
        "mean": round(statistics.mean(vals), 1),
        "p95": round(s[min(int(len(s) * 0.95), len(s) - 1)], 1),
        "min": round(min(vals), 1),
        "max": round(max(vals), 1),
        "std": round(statistics.pstdev(vals), 1) if len(vals) > 1 else 0.0,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--service", default="http://127.0.0.1:8000")
    ap.add_argument("--token", default="")
    ap.add_argument("--map-id", default="")
    ap.add_argument("--dest", default="")
    ap.add_argument("--frames", type=int, default=60)
    ap.add_argument("--out", default="results/latency.json")
    args = ap.parse_args()

    base = args.service.rstrip("/")
    token = args.token

    print(f"=== 目标服务: {base} ===")
    code, health, ms = http_json(f"{base}/health", headers=_auth(token))
    print(f"/health -> HTTP {code} ({ms:.0f} ms)")
    if code != 200:
        raise SystemExit("服务不可达")
    print(json.dumps(health, ensure_ascii=False, indent=2)[:800])
    if not health.get("inference_ready"):
        raise SystemExit("NoMaD 未就绪，无法测导航时延")
    if not health.get("capabilities", {}).get("yoso_vision"):
        print("⚠ YOSO 未就绪，将跳过避障时延")

    map_id = args.map_id
    dest = args.dest
    nodes = []
    if not map_id:
        map_id, dest, nodes = pick_map(base, token)
    print(f"\n地图: {map_id}  目标节点: {dest}  节点数: {len(nodes) or '未知'}")

    # 创建会话
    code, sess, ms = http_json(f"{base}/v1/navigation/sessions", method="POST",
                               payload={"map_id": map_id, "destination_node": dest},
                               headers=_auth(token))
    print(f"创建会话 -> HTTP {code} ({ms:.0f} ms)")
    if code != 201:
        raise SystemExit(f"会话创建失败: {sess}")
    sid = sess["session_id"]
    print(f"session_id = {sid}")

    frames = load_frames(base, map_id, nodes, args.frames, token)

    nav_rows, obs_rows = [], []
    print(f"\n开始 {args.frames} 轮测量（导航 {NAV_INTERVAL_S}s / 避障 {OBS_INTERVAL_S}s）...")
    for i in range(args.frames):
        jpeg = frames[i % len(frames)]

        # 导航帧
        code, body, ms = post_file(f"{base}/v1/navigation/sessions/{sid}/frames",
                                   "frame.jpg", jpeg, token=token)
        res = body.get("result", {}) if isinstance(body, dict) else {}
        nav_rows.append({
            "i": i,
            "code": code,
            "rtt_ms": round(ms, 1),
            "status": res.get("status"),
            "direction": res.get("direction"),
            "bytes": len(jpeg),
        })
        if i < WARMUP_FRAMES:
            print(f"  [{i}] 导航 warming_up  rtt={ms:.0f} ms status={res.get('status')}")
        elif i % 10 == 0 or i == args.frames - 1:
            print(f"  [{i}] 导航 rtt={ms:.0f} ms  status={res.get('status')}  dir={res.get('direction')}")

        # 避障帧
        if health.get("capabilities", {}).get("yoso_vision"):
            code2, body2, ms2 = post_file(f"{base}/v1/vision/obstacle", "frame.jpg", jpeg, token=token)
            obs_rows.append({
                "i": i,
                "code": code2,
                "rtt_ms": round(ms2, 1),
                "direction": body2.get("direction") if isinstance(body2, dict) else None,
                "stairs": body2.get("stairs") if isinstance(body2, dict) else None,
            })

        if i < args.frames - 1:
            time.sleep(max(NAV_INTERVAL_S, OBS_INTERVAL_S))

    steady_nav = nav_rows[WARMUP_FRAMES:]
    out = {
        "meta": {
            "service": base,
            "map_id": map_id,
            "destination": dest,
            "session_id": sid,
            "frames_requested": args.frames,
            "warmup_frames": WARMUP_FRAMES,
            "frame_bytes_median": round(statistics.median([r["bytes"] for r in nav_rows]), 0),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "health": {k: health.get(k) for k in ("inference_ready", "gpu_visible")},
            "capabilities": health.get("capabilities"),
        },
        "nav": {
            "all": summarize(nav_rows),
            "steady_state": summarize(steady_nav),
            "raw": nav_rows,
        },
        "obstacle": {
            "steady_state": summarize(obs_rows),
            "raw": obs_rows,
        } if obs_rows else {},
    }

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print("\n=== 结果 ===")
    print("导航（稳态）:", json.dumps(out["nav"]["steady_state"], ensure_ascii=False))
    if obs_rows:
        print("避障（稳态）:", json.dumps(out["obstacle"]["steady_state"], ensure_ascii=False))
    print(f"\n已保存 -> {args.out}")

    # 与论文图 3 的估算值对比
    est = 443
    actual = out["nav"]["steady_state"].get("p50")
    if actual:
        print(f"\n论文估算 {est} ms vs 实测 P50 {actual} ms，偏差 {actual-est:+.0f} ms ({(actual-est)/est*100:+.1f}%)")


if __name__ == "__main__":
    main()
