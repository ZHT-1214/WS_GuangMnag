# -*- coding: utf-8 -*-
"""E3 避障与视觉辅助准确率评测（exp_obstacle_eval）。

思路：构造一个带人工标注的测试集，跑云端 YOSO，统计：
  - 可行方向判断准确率（与人工标注的 ground truth 对比）
  - 楼梯检测的召回率 / 精确率
  - 寻物功能的命中率
  - 环境描述的类别覆盖

两步走：
  1. 生成标注模板：python exp_obstacle_eval.py --make-template --img-dir ./imgs
  2. 人工填写标注后评测：python exp_obstacle_eval.py --labels labels.json --img-dir ./imgs

labels.json 格式：
[
  {"file": "img001.jpg", "passable": "left", "stairs": false, "note": "左侧有通道"},
  ...
]
passable 取值：left / ahead / right / none（none 表示完全无法通行）
stairs：该画面是否含楼梯

用法（评测）：
    python exp_obstacle_eval.py --service http://127.0.0.1:8000 \
        --img-dir ./obstacle_imgs --labels labels.json --out results/obstacle.json
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
from collections import Counter


DIR_MAP = {"left": "left", "ahead": "forward", "right": "right",
           "forward": "forward", "none": "unknown", "unknown": "unknown"}


def _auth(token):
    return {"Authorization": f"Bearer {token}"} if token else {}


def post_file(url, content, token="", timeout=90):
    boundary = "----obs" + uuid.uuid4().hex
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


def make_template(img_dir, out="labels_template.json"):
    """生成标注模板，供人工填写。"""
    files = sorted(f for f in os.listdir(img_dir)
                   if f.lower().endswith((".jpg", ".jpeg", ".png")))
    template = [{
        "file": f,
        "passable": "",      # 填 left / ahead / right / none
        "stairs": None,      # 填 true / false
        "note": ""
    } for f in files]
    with open(out, "w", encoding="utf-8") as fp:
        json.dump(template, fp, ensure_ascii=False, indent=2)
    print(f"标注模板已生成：{out}（{len(files)} 张图）")
    print("\n填写说明：")
    print("  passable: 人站在此处，最安全的通行方向")
    print("            left=向左   ahead=向前   right=向右   none=无路可走")
    print("  stairs:   画面中是否有楼梯（true/false）")
    print("  note:     可选备注")


def evaluate(service, token, img_dir, labels_path, out_path):
    with open(labels_path, encoding="utf-8") as f:
        labels = json.load(f)

    records = []
    print(f"评测 {len(labels)} 张图...")
    for i, item in enumerate(labels):
        fname = item["file"]
        if not item.get("passable"):
            print(f"  [skip] {fname} 未标注")
            continue
        path = os.path.join(img_dir, fname)
        if not os.path.exists(path):
            print(f"  [skip] {fname} 文件不存在")
            continue
        with open(path, "rb") as f:
            jpeg = f.read()

        code, body, ms = post_file(f"{service}/v1/vision/obstacle", jpeg, token)
        pred_dir = body.get("direction") if isinstance(body, dict) else None
        pred_stairs = body.get("stairs") if isinstance(body, dict) else None

        gt = DIR_MAP.get(item["passable"], "unknown")
        records.append({
            "file": fname,
            "gt_passable": item["passable"],
            "gt_direction": gt,
            "pred_direction": pred_dir,
            "gt_stairs": item.get("stairs"),
            "pred_stairs": pred_stairs,
            "correct": pred_dir == gt,
            "rtt_ms": round(ms, 1),
        })
        mark = "OK " if pred_dir == gt else "XX "
        print(f"  [{i+1:3d}] {mark} {fname:20s} gt={gt:8s} pred={str(pred_dir):8s} "
              f"stairs(gt/pred)={item.get('stairs')}/{pred_stairs}")

    if not records:
        raise SystemExit("没有有效样本")

    n = len(records)
    correct = sum(1 for r in records if r["correct"])
    cm = Counter((r["gt_direction"], r["pred_direction"]) for r in records)

    # 楼梯指标
    stairs_recs = [r for r in records if r["gt_stairs"] is not None]
    tp = sum(1 for r in stairs_recs if r["gt_stairs"] and r["pred_stairs"])
    fp = sum(1 for r in stairs_recs if not r["gt_stairs"] and r["pred_stairs"])
    fn = sum(1 for r in stairs_recs if r["gt_stairs"] and not r["pred_stairs"])
    tn = sum(1 for r in stairs_recs if not r["gt_stairs"] and not r["pred_stairs"])

    result = {
        "n_samples": n,
        "direction": {
            "accuracy": round(correct / n, 4),
            "correct": correct,
            "confusion_matrix": {f"{g}->{p}": c for (g, p), c in cm.items()},
            "per_class_accuracy": {},
        },
        "stairs": {
            "n": len(stairs_recs),
            "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "recall": round(tp / (tp + fn), 4) if (tp + fn) else None,
            "precision": round(tp / (tp + fp), 4) if (tp + fp) else None,
            "accuracy": round((tp + tn) / len(stairs_recs), 4) if stairs_recs else None,
        },
        "latency": {
            "p50": round(statistics.median([r["rtt_ms"] for r in records]), 1),
            "mean": round(statistics.mean([r["rtt_ms"] for r in records]), 1),
            "max": round(max(r["rtt_ms"] for r in records), 1),
        },
        "records": records,
    }

    # 每类准确率
    by_gt = {}
    for r in records:
        by_gt.setdefault(r["gt_direction"], []).append(r["correct"])
    for k, v in by_gt.items():
        result["direction"]["per_class_accuracy"][k] = {
            "n": len(v), "acc": round(sum(v) / len(v), 4)
        }

    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print("\n===== 结果 =====")
    print(json.dumps({k: v for k, v in result.items() if k != "records"},
                     ensure_ascii=False, indent=2))
    print(f"\n保存 -> {out_path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--service", default="http://127.0.0.1:8000")
    ap.add_argument("--token", default="")
    ap.add_argument("--img-dir", required=True)
    ap.add_argument("--labels", default="")
    ap.add_argument("--out", default="results/obstacle.json")
    ap.add_argument("--make-template", action="store_true")
    args = ap.parse_args()

    if args.make_template:
        make_template(args.img_dir)
        return

    if not args.labels:
        raise SystemExit("需要 --labels（或用 --make-template 生成模板）")
    evaluate(args.service.rstrip("/"), args.token, args.img_dir, args.labels, args.out)


if __name__ == "__main__":
    main()
