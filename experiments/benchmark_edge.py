#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Jetson Orin Nano 边缘推理时延基准测试。

目的：测量 NoMaD 在边缘设备上的单帧推理时延，与云端 RTX 4090 的
103.7 ms 做公平对比（同一模型、同一推理流程、同一输入数据）。

不依赖 FastAPI/HTTP，直接调用模型，避免服务层开销干扰时延测量。

用法：
    ~/miniforge3/envs/jetson_env/bin/python benchmark_edge.py \
        --runtime-root ~/visualnav-transformer-扩散策略模型 \
        --config ~/visualnav-transformer-扩散策略模型/train/config/nomad.yaml \
        --checkpoint ~/visualnav-transformer-扩散策略模型/deployment/model_weights/nomad.pth \
        --map-dir ~/visualnav-transformer-扩散策略模型/deployment/topomaps/images/my_home_map \
        --frames 60 --out edge_latency.json
"""
import argparse
import json
import os
import statistics
import sys
import time


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runtime-root", required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--map-dir", required=True)
    ap.add_argument("--frames", type=int, default=60)
    ap.add_argument("--num-samples", type=int, default=4)
    ap.add_argument("--waypoint-index", type=int, default=2)
    ap.add_argument("--radius", type=int, default=4)
    ap.add_argument("--close-threshold", type=float, default=3.0)
    ap.add_argument("--out", default="edge_latency.json")
    args = ap.parse_args()

    import numpy as np
    import torch
    import yaml
    from PIL import Image
    from torchvision import transforms
    from diffusers.schedulers.scheduling_ddpm import DDPMScheduler

    runtime = os.path.abspath(os.path.expanduser(args.runtime_root))
    sys.path.insert(0, runtime)
    sys.path.insert(0, os.path.join(runtime, "diffusion_policy"))

    print("=" * 62)
    print("Jetson 边缘推理基准")
    print("=" * 62)
    print(f"torch      : {torch.__version__}")
    print(f"CUDA       : {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"GPU        : {torch.cuda.get_device_name(0)}")
    print(f"runtime    : {runtime}")

    cfg = yaml.safe_load(open(os.path.expanduser(args.config), encoding="utf-8"))
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    # ---- 构建模型（与云端 inference.py 完全一致）----
    from vint_train.models.nomad.nomad import DenseNetwork, NoMaD
    from vint_train.models.nomad.nomad_vint import NoMaD_ViNT, replace_bn_with_gn
    from diffusion_policy.model.diffusion.conditional_unet1d import ConditionalUnet1D

    t0 = time.perf_counter()
    encoder = NoMaD_ViNT(
        obs_encoding_size=cfg["encoding_size"],
        context_size=cfg["context_size"],
        mha_num_attention_heads=cfg["mha_num_attention_heads"],
        mha_num_attention_layers=cfg["mha_num_attention_layers"],
        mha_ff_dim_factor=cfg["mha_ff_dim_factor"],
    )
    encoder = replace_bn_with_gn(encoder)
    noise_pred = ConditionalUnet1D(
        input_dim=2,
        global_cond_dim=cfg["encoding_size"],
        down_dims=cfg["down_dims"],
        cond_predict_scale=cfg["cond_predict_scale"],
    )
    dist_pred = DenseNetwork(embedding_dim=cfg["encoding_size"])
    model = NoMaD(encoder, noise_pred, dist_pred)

    ckpt = torch.load(os.path.expanduser(args.checkpoint), map_location=device)
    model.load_state_dict(ckpt, strict=True)
    model.to(device).eval()
    load_ms = (time.perf_counter() - t0) * 1000
    print(f"模型加载   : {load_ms:.0f} ms")

    num_params = sum(p.numel() for p in model.parameters())
    print(f"参数量     : {num_params:,} ({num_params/1e6:.2f} M)")

    scheduler = DDPMScheduler(
        num_train_timesteps=cfg["num_diffusion_iters"],
        beta_schedule="squaredcos_cap_v2",
        clip_sample=True,
        prediction_type="epsilon",
    )
    context_size = int(cfg["context_size"])
    image_size = tuple(cfg["image_size"])   # (W, H)
    len_traj = int(cfg["len_traj_pred"])

    tf = transforms.Compose([
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406],
                             std=[0.229, 0.224, 0.225]),
    ])

    # ---- 加载拓扑图节点 ----
    map_dir = os.path.expanduser(args.map_dir)
    files = sorted([f for f in os.listdir(map_dir)
                    if f.lower().endswith((".jpg", ".jpeg", ".png"))
                    and os.path.splitext(f)[0].isdigit()],
                   key=lambda x: int(os.path.splitext(x)[0]))
    if not files:
        raise SystemExit(f"地图目录无有效节点: {map_dir}")
    print(f"地图       : {map_dir} ({len(files)} 节点)")

    nodes = []
    for f in files:
        im = Image.open(os.path.join(map_dir, f)).convert("RGB").resize(image_size)
        nodes.append(tf(im))
    goal_tensor = torch.stack(nodes).to(device)   # (N,3,H,W)

    # ---- 预热（第一次推理含 CUDA kernel 编译，单独统计）----
    print("\n预热中…")
    warm_obs = torch.zeros(1, 3 * (context_size + 1), image_size[1], image_size[0],
                           device=device)
    warm_goal = goal_tensor[:1]
    warm_mask = torch.zeros(1, dtype=torch.long, device=device)
    with torch.inference_mode():
        t_w = time.perf_counter()
        _ = model("vision_encoder", obs_img=warm_obs, goal_img=warm_goal,
                  input_goal_mask=warm_mask)
        torch.cuda.synchronize() if torch.cuda.is_available() else None
        warmup_ms = (time.perf_counter() - t_w) * 1000
    print(f"首次推理（含 kernel 编译）: {warmup_ms:.0f} ms")

    # ---- 正式计时 ----
    print(f"\n开始 {args.frames} 帧测量…")
    records = []
    ctx_frames = [torch.zeros(3, image_size[1], image_size[0], device=device)
                  for _ in range(context_size + 1)]

    for i in range(args.frames):
        node_idx = i % len(nodes)
        frame = nodes[node_idx].to(device)

        # 维护上下文队列
        ctx_frames.pop(0)
        ctx_frames.append(frame)
        obs = torch.stack(ctx_frames).unsqueeze(0)              # (1,C+1,3,H,W)
        obs = obs.view(1, -1, image_size[1], image_size[0])     # (1,3*(C+1),H,W)

        # 子目标窗口
        start = max(node_idx - args.radius, 0)
        end = min(node_idx + args.radius + 1, len(nodes))
        cand = goal_tensor[start:end]

        if torch.cuda.is_available():
            torch.cuda.synchronize()
        t_frame = time.perf_counter()

        with torch.inference_mode():
            # 1) 视觉编码 + 距离预测
            obs_rep = obs.repeat(cand.shape[0], 1, 1, 1)
            mask = torch.zeros(cand.shape[0], dtype=torch.long, device=device)
            cond = model("vision_encoder", obs_img=obs_rep, goal_img=cand,
                         input_goal_mask=mask)
            dists = model("dist_pred_net", obsgoal_cond=cond).flatten()
            min_idx = int(torch.argmin(dists).item())
            closest = start + min_idx

            # 2) 子目标推进
            sg_local = min(min_idx + int(dists[min_idx].item() < args.close_threshold),
                           cond.shape[0] - 1)
            sg_cond = cond[sg_local].unsqueeze(0)

            # 3) 扩散去噪
            naction = torch.randn(
                (args.num_samples, len_traj, 2), device=device)
            scheduler.set_timesteps(int(cfg["num_diffusion_iters"]))
            cond_rep = sg_cond.repeat(args.num_samples, 1)
            for k in scheduler.timesteps:
                noise = model("noise_pred_net", sample=naction,
                              timestep=k, global_cond=cond_rep)
                naction = scheduler.step(model_output=noise, timestep=k,
                                         sample=naction).prev_sample
            actions = naction.cpu().numpy()

            # 4) 轨迹共识
            median = np.median(actions, axis=0)
            best = min(actions, key=lambda a: float(np.linalg.norm(a - median)))
            wp = best[args.waypoint_index]

        if torch.cuda.is_available():
            torch.cuda.synchronize()
        dt_ms = (time.perf_counter() - t_frame) * 1000

        # 方向映射（与 inference.py 一致）
        x, y = float(wp[0]), float(wp[1])
        if x < -0.2:
            direction = "back"
        elif y > 0.3:
            direction = "left"
        elif y < -0.3:
            direction = "right"
        elif x < 0.2:
            direction = "unknown"
        else:
            direction = "forward"

        records.append({
            "i": i,
            "node": files[node_idx],
            "closest": files[closest] if closest < len(files) else None,
            "direction": direction,
            "rtt_ms": round(dt_ms, 1),
        })
        if i % 10 == 0 or i == args.frames - 1:
            print(f"  [{i:2d}] {files[node_idx]:10s} -> {direction:8s} "
                  f"closest={files[closest] if closest < len(files) else '?':10s} "
                  f"{dt_ms:.0f} ms")

    # ---- 统计（剔除前 4 帧 warmup）----
    warm = min(4, len(records) // 4)
    steady = records[warm:]
    vals = [r["rtt_ms"] for r in steady]
    vals_sorted = sorted(vals)
    stats = {
        "n": len(vals),
        "p50": round(statistics.median(vals), 1),
        "mean": round(statistics.mean(vals), 1),
        "p95": round(vals_sorted[min(int(len(vals_sorted) * 0.95), len(vals_sorted) - 1)], 1),
        "min": round(min(vals), 1),
        "max": round(max(vals), 1),
        "std": round(statistics.pstdev(vals), 1) if len(vals) > 1 else 0.0,
    }

    from collections import Counter
    dir_dist = dict(Counter(r["direction"] for r in steady))

    result = {
        "meta": {
            "device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU",
            "torch": torch.__version__,
            "cuda": torch.cuda.is_available(),
            "num_params": num_params,
            "model_load_ms": round(load_ms, 0),
            "warmup_first_inference_ms": round(warmup_ms, 0),
            "map": os.path.basename(map_dir),
            "n_nodes": len(files),
            "frames_requested": args.frames,
            "warmup_frames_skipped": warm,
            "num_samples": args.num_samples,
            "diffusion_iters": int(cfg["num_diffusion_iters"]),
        },
        "steady_state": stats,
        "direction_distribution": dir_dist,
        "records": records,
    }

    out = os.path.expanduser(args.out)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 62)
    print("结果（稳态）")
    print("=" * 62)
    print(f"  P50 = {stats['p50']} ms")
    print(f"  P95 = {stats['p95']} ms")
    print(f"  mean= {stats['mean']} ms   std={stats['std']} ms")
    print(f"  min = {stats['min']} ms   max={stats['max']} ms")
    print(f"  方向分布: {dir_dist}")
    print(f"\n云端 RTX 4090 实测 P50 = 103.7 ms")
    print(f"边缘/云端 时延比 = {stats['p50']/103.7:.2f}x")
    print(f"\n保存 -> {out}")


if __name__ == "__main__":
    main()
