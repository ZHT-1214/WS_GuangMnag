#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对比优化前后的完整推理时延（含节点图解码）。

优化内容：缓存拓扑图节点的预处理张量，避免每帧重复解码。
本脚本在同一进程中分别以"原始方式"和"缓存方式"跑完整推理，
验证输出完全一致的同时量化时延收益。
"""
import io
import os
import statistics
import sys
import time
from collections import deque
from pathlib import Path

import numpy as np
import torch
import yaml
from PIL import Image
from torchvision import transforms
from diffusers.schedulers.scheduling_ddpm import DDPMScheduler

ROOT = os.path.expanduser("~/visualnav-transformer-扩散策略模型")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "diffusion_policy"))

from vint_train.models.nomad.nomad import DenseNetwork, NoMaD
from vint_train.models.nomad.nomad_vint import NoMaD_ViNT, replace_bn_with_gn
from diffusion_policy.model.diffusion.conditional_unet1d import ConditionalUnet1D

CFG = os.path.join(ROOT, "train/config/nomad.yaml")
CKPT = os.path.join(ROOT, "deployment/model_weights/nomad.pth")
MAP = os.path.join(ROOT, "deployment/topomaps/images/my_home_map")

cfg = yaml.safe_load(open(CFG, encoding="utf-8"))
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
image_size = tuple(cfg["image_size"])
ctx = int(cfg["context_size"])
len_traj = int(cfg["len_traj_pred"])
iters = int(cfg["num_diffusion_iters"])
NUM_SAMPLES = 4
RADIUS = 4
WAYPOINT_IDX = 2

tf = transforms.Compose([
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
])


def prepare(img):
    return tf(img.convert("RGB").resize(image_size))


def build_model():
    enc = NoMaD_ViNT(
        obs_encoding_size=cfg["encoding_size"], context_size=ctx,
        mha_num_attention_heads=cfg["mha_num_attention_heads"],
        mha_num_attention_layers=cfg["mha_num_attention_layers"],
        mha_ff_dim_factor=cfg["mha_ff_dim_factor"])
    enc = replace_bn_with_gn(enc)
    noise = ConditionalUnet1D(input_dim=2, global_cond_dim=cfg["encoding_size"],
                              down_dims=cfg["down_dims"],
                              cond_predict_scale=cfg["cond_predict_scale"])
    dist = DenseNetwork(embedding_dim=cfg["encoding_size"])
    m = NoMaD(enc, noise, dist)
    m.load_state_dict(torch.load(CKPT, map_location=device), strict=True)
    return m.to(device).eval()


def run_inference(model, sched, context, node_files, closest, use_cache, cache):
    """跑一次完整推理，返回 (waypoint, closest_index)。"""
    goal_idx = len(node_files) - 1
    start = max(closest - RADIUS, 0)
    end = min(closest + RADIUS, goal_idx)
    if end < start:
        start = end = goal_idx

    with torch.inference_mode():
        obs = torch.stack([prepare(f) for f in context], dim=0)
        obs = obs.reshape(1, -1, obs.shape[-2], obs.shape[-1]).to(device)

        if use_cache:
            goals = cache[start:end + 1].to(device)
        else:
            goals = torch.stack(
                [prepare(Image.open(p)) for p in node_files[start:end + 1]], dim=0
            ).to(device)

        batch_obs = obs.repeat(goals.shape[0], 1, 1, 1)
        mask = torch.zeros(goals.shape[0], dtype=torch.long, device=device)
        cond = model("vision_encoder", obs_img=batch_obs, goal_img=goals,
                     input_goal_mask=mask)
        dists = model("dist_pred_net", obsgoal_cond=cond).flatten()
        local = int(torch.argmin(dists).item())
        closest_new = start + local
        sg = min(local + int(float(dists[local].item()) < 3.0), cond.shape[0] - 1)
        c = cond[sg].unsqueeze(0).repeat(NUM_SAMPLES, 1)

        actions = torch.randn(NUM_SAMPLES, len_traj, 2, device=device)
        sched.set_timesteps(iters)
        for t in sched.timesteps:
            noise = model("noise_pred_net", sample=actions, timestep=t, global_cond=c)
            actions = sched.step(model_output=noise, timestep=t, sample=actions).prev_sample

        norm = actions.detach().cpu().numpy()
        lo = np.array([-2.5, -4.0], dtype=np.float32)
        hi = np.array([5.0, 4.0], dtype=np.float32)
        deltas = ((norm + 1.0) / 2.0) * (hi - lo) + lo
        traj = np.cumsum(deltas, axis=1)
        wps = traj[:, min(WAYPOINT_IDX, traj.shape[1] - 1)]
        consensus = np.median(wps, axis=0)
        sel = int(np.argmin(np.linalg.norm(wps - consensus, axis=1)))
        wp = traj[sel][min(WAYPOINT_IDX, traj.shape[1] - 1)]
    return wp, closest_new


def main():
    node_files = sorted(
        [p for p in Path(MAP).iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png")],
        key=lambda p: int(p.stem) if p.stem.isdigit() else 10**9)
    print(f"节点数: {len(node_files)}")
    print(f"设备: {device}")

    model = build_model()
    sched = DDPMScheduler(num_train_timesteps=iters,
                          beta_schedule="squaredcos_cap_v2",
                          clip_sample=True, prediction_type="epsilon")

    # 预构建缓存
    t0 = time.perf_counter()
    cache = torch.stack([prepare(Image.open(p)) for p in node_files], dim=0)
    print(f"缓存构建: {(time.perf_counter()-t0)*1000:.0f} ms")

    # 预热
    print("预热…")
    warm_ctx = [Image.open(node_files[0])] * (ctx + 1)
    for mode in (False, True):
        run_inference(model, sched, warm_ctx, node_files, 5, mode, cache)
    if torch.cuda.is_available():
        torch.cuda.synchronize()

    # 准备上下文
    context = [Image.open(p) for p in node_files[:ctx + 1]]

    N = 40
    print(f"\n各跑 {N} 次…")

    # ---- 原始方式 ----
    times_orig = []
    wp_orig = []
    for i in range(N):
        closest = 5 + (i % 20)
        if torch.cuda.is_available():
            torch.cuda.synchronize()
        t0 = time.perf_counter()
        wp, c = run_inference(model, sched, context, node_files, closest, False, cache)
        if torch.cuda.is_available():
            torch.cuda.synchronize()
        times_orig.append((time.perf_counter() - t0) * 1000)
        wp_orig.append((wp.tolist(), c))

    # ---- 缓存方式 ----
    times_cache = []
    wp_cache = []
    for i in range(N):
        closest = 5 + (i % 20)
        if torch.cuda.is_available():
            torch.cuda.synchronize()
        t0 = time.perf_counter()
        wp, c = run_inference(model, sched, context, node_files, closest, True, cache)
        if torch.cuda.is_available():
            torch.cuda.synchronize()
        times_cache.append((time.perf_counter() - t0) * 1000)
        wp_cache.append((wp.tolist(), c))

    m_orig = statistics.median(times_orig)
    m_cache = statistics.median(times_cache)

    # 输出一致性：closest 必须完全相同（waypoint 受随机噪声影响，不比较）
    same_closest = all(a[1] == b[1] for a, b in zip(wp_orig, wp_cache))

    print("\n" + "=" * 66)
    print("结果")
    print("=" * 66)
    print(f"  原始（每帧解码节点图）: P50 = {m_orig:.1f} ms")
    print(f"  优化（缓存节点张量）  : P50 = {m_cache:.1f} ms")
    print(f"  节省                  : {m_orig - m_cache:.1f} ms "
          f"({(1 - m_cache/m_orig)*100:.1f}%)")
    print(f"\n  closest 判定一致性    : {'✓ 完全一致' if same_closest else '✗ 有差异'}")

    import json
    out = {
        "meta": {"device": str(device), "n_nodes": len(node_files),
                 "n_iter": N, "num_samples": NUM_SAMPLES, "diffusion_iters": iters},
        "original": {"p50": round(m_orig, 1),
                     "p95": round(sorted(times_orig)[int(N*0.95)], 1)},
        "cached": {"p50": round(m_cache, 1),
                   "p95": round(sorted(times_cache)[int(N*0.95)], 1)},
        "saving_ms": round(m_orig - m_cache, 1),
        "saving_pct": round((1 - m_cache/m_orig) * 100, 1),
        "closest_identical": same_closest,
    }
    with open("/home/num7/cache_bench.json", "w") as f:
        json.dump(out, f, indent=2)
    print(f"\n保存 -> /home/num7/cache_bench.json")


if __name__ == "__main__":
    main()
