# -*- coding: utf-8 -*-
"""实验编排：一键跑完导航成功率 + 仲裁器消融（exp_run_all）。

前提：
  1. 云端服务已启动且 inference_ready / yoso_vision 均为 true
  2. 本地已有若干条已录制的路线目录（每条一个文件夹，含 0.jpg, 1.jpg, ...）

用法：
  python exp_run_all.py --service http://127.0.0.1:8000 \
      --routes routes.json --out-dir results/

routes.json 格式（map_id 需先上传到云端；也可用 --auto-upload 自动上传）：
[
  {"name": "routeA_01", "dir": "D:/maps/routeA_01"},
  ...
]

--auto-upload 模式下只需给 dir，脚本会：
  1. 打包 ZIP
  2. POST /v1/maps 上传
  3. 拿到 map_id 后跑重放
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
import uuid
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable


def http_json(url, method="GET", payload=None, headers=None, timeout=120):
    data = json.dumps(payload).encode() if payload is not None else None
    hdrs = dict(headers or {})
    if data:
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def upload_map(service, token, map_dir, name):
    """把地图目录打包成 ZIP 并上传。"""
    zip_path = os.path.join(os.environ.get("TEMP", "/tmp"), f"{name}-{uuid.uuid4().hex[:8]}.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(os.listdir(map_dir)):
            if f.lower().endswith((".jpg", ".jpeg", ".png")):
                z.write(os.path.join(map_dir, f), f)

    boundary = "----map" + uuid.uuid4().hex
    with open(zip_path, "rb") as f:
        content = f.read()
    body = b"".join([
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="file"; filename="{name}.zip"\r\n'.encode(),
        b"Content-Type: application/zip\r\n\r\n",
        content,
        f"\r\n--{boundary}--\r\n".encode(),
    ])
    hdrs = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"{service}/v1/maps", data=body, headers=hdrs, method="POST")
    with urllib.request.urlopen(req, timeout=180) as r:
        info = json.loads(r.read().decode("utf-8", "replace"))
    os.remove(zip_path)
    return info["id"], info["node_count"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--service", default="http://127.0.0.1:8000")
    ap.add_argument("--token", default="")
    ap.add_argument("--routes", required=True, help="routes.json")
    ap.add_argument("--out-dir", default="results")
    ap.add_argument("--auto-upload", action="store_true", help="自动上传地图（否则用给定的 map_id）")
    ap.add_argument("--skip-navigation", action="store_true")
    ap.add_argument("--skip-arbitration", action="store_true")
    args = ap.parse_args()

    service = args.service.rstrip("/")
    os.makedirs(args.out_dir, exist_ok=True)

    health = http_json(f"{service}/health", headers={"Authorization": f"Bearer {args.token}"} if args.token else {})
    print(f"服务状态: inference_ready={health.get('inference_ready')}, "
          f"yoso={health.get('capabilities', {}).get('yoso_vision')}")
    if not health.get("inference_ready"):
        raise SystemExit("NoMaD 未就绪，终止")

    with open(args.routes, encoding="utf-8") as f:
        routes = json.load(f)

    # ---- 1. 准备地图 ----
    prepared = []
    for r in routes:
        if args.auto_upload:
            print(f"上传地图 {r['name']} ...")
            mid, cnt = upload_map(service, args.token, r["dir"], r["name"])
            print(f"  -> map_id={mid}, {cnt} 节点")
            prepared.append({"name": r["name"], "map_id": mid, "map_dir": r["dir"]})
        else:
            prepared.append({"name": r["name"], "map_id": r["map_id"], "map_dir": r["dir"]})

    # ---- 2. 导航成功率 ----
    if not args.skip_navigation:
        batch_path = os.path.join(args.out_dir, "batch_routes.json")
        with open(batch_path, "w", encoding="utf-8") as f:
            json.dump(prepared, f, ensure_ascii=False, indent=2)
        nav_out = os.path.join(args.out_dir, "navigation_all.json")
        print(f"\n===== 导航成功率实验（{len(prepared)} 条路线）=====")
        subprocess.run([PY, os.path.join(HERE, "exp_navigation_replay.py"),
                        "--service", service, "--token", args.token,
                        "--batch", batch_path, "--out", nav_out], check=False)
    else:
        nav_out = None

    # ---- 3. 仲裁器消融（用导航实验产生的方向序列）----
    if not args.skip_arbitration and nav_out and os.path.exists(nav_out):
        print("\n===== 仲裁器消融 =====")
        with open(nav_out, encoding="utf-8") as f:
            nav = json.load(f)
        for r in nav.get("routes", []):
            if "error" in r:
                continue
            trace = {
                "nav": [rec["direction"] for rec in r["records"]],
                "obs": [None] * len(r["records"]),
                "stairs": [False] * len(r["records"]),
                "t": [i * 0.7 for i in range(len(r["records"]))],
                "route": r.get("name", r["map_id"]),
                "condition": "replay",
            }
            tp = os.path.join(args.out_dir, f"trace_{r.get('name', 'x')}.json")
            with open(tp, "w", encoding="utf-8") as f:
                json.dump(trace, f, ensure_ascii=False, indent=2)
            ap_out = os.path.join(args.out_dir, f"arbitration_{r.get('name', 'x')}.json")
            subprocess.run([PY, os.path.join(HERE, "exp_arbitration.py"),
                            "--trace", tp, "--out", ap_out], check=False)

    print(f"\n全部完成，结果在 {os.path.abspath(args.out_dir)}")


if __name__ == "__main__":
    main()
