"""GPU NoMaD inference backend with no ROS or GUI dependencies."""

from __future__ import annotations

import io
import sys
import threading
from collections import deque
from pathlib import Path
from typing import Any, Deque, Dict, List

import numpy as np
import torch
import yaml
from diffusers.schedulers.scheduling_ddpm import DDPMScheduler
from PIL import Image
from torchvision import transforms


class NomadBackend:
    # ---- 失锁恢复机制参数 ----
    # 最佳距离超过此阈值（NoMaD 距离预测头输出的度量值）视为"当前帧与窗口内
    # 所有节点都不像"，位置可能已失锁。
    LOST_DISTANCE_THRESHOLD = 6.0
    # 连续多少帧失锁后开始扩大搜索窗口
    LOST_PATIENCE = 2
    # 扩大搜索窗口的倍数（相对默认 radius）
    LOST_RADIUS_MULTIPLIER = 3

    def __init__(self, runtime_root: Path, config_path: Path, checkpoint_path: Path):
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA is not available")
        self.runtime_root = runtime_root.resolve()
        sys.path.insert(0, str(self.runtime_root))
        self.config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        self.device = torch.device("cuda")
        self.model = self._build_model()
        checkpoint = torch.load(checkpoint_path, map_location=self.device)
        self.model.load_state_dict(checkpoint, strict=True)
        self.model.to(self.device).eval()
        self.scheduler = DDPMScheduler(
            num_train_timesteps=self.config["num_diffusion_iters"],
            beta_schedule="squaredcos_cap_v2",
            clip_sample=True,
            prediction_type="epsilon",
        )
        self.context_size = int(self.config["context_size"])
        self.image_size = tuple(self.config["image_size"])
        self.frames: Dict[str, Deque[Image.Image]] = {}
        self.lock = threading.Lock()
        # 节点图预处理缓存：(地图路径, 文件签名) -> 堆叠张量（CPU）
        self._node_cache: Dict[Any, torch.Tensor] = {}
        self._node_cache_limit = 8
        self.transform = transforms.Compose(
            [
                transforms.ToTensor(),
                transforms.Normalize(
                    mean=[0.485, 0.456, 0.406],
                    std=[0.229, 0.224, 0.225],
                ),
            ]
        )

    def _build_model(self):
        from diffusion_policy.model.diffusion.conditional_unet1d import ConditionalUnet1D
        from vint_train.models.nomad.nomad import DenseNetwork, NoMaD
        from vint_train.models.nomad.nomad_vint import NoMaD_ViNT, replace_bn_with_gn

        encoder = NoMaD_ViNT(
            obs_encoding_size=self.config["encoding_size"],
            context_size=self.config["context_size"],
            mha_num_attention_heads=self.config["mha_num_attention_heads"],
            mha_num_attention_layers=self.config["mha_num_attention_layers"],
            mha_ff_dim_factor=self.config["mha_ff_dim_factor"],
        )
        encoder = replace_bn_with_gn(encoder)
        noise_predictor = ConditionalUnet1D(
            input_dim=2,
            global_cond_dim=self.config["encoding_size"],
            down_dims=self.config["down_dims"],
            cond_predict_scale=self.config["cond_predict_scale"],
        )
        distance_predictor = DenseNetwork(embedding_dim=self.config["encoding_size"])
        return NoMaD(
            vision_encoder=encoder,
            noise_pred_net=noise_predictor,
            dist_pred_net=distance_predictor,
        )

    def warmup(self) -> None:
        size = (self.image_size[0], self.image_size[1])
        obs = torch.zeros(
            1,
            3 * (self.context_size + 1),
            size[1],
            size[0],
            device=self.device,
        )
        goal = torch.zeros(1, 3, size[1], size[0], device=self.device)
        mask = torch.zeros(1, dtype=torch.long, device=self.device)
        with torch.inference_mode():
            condition = self.model(
                "vision_encoder",
                obs_img=obs,
                goal_img=goal,
                input_goal_mask=mask,
            )
            self.model("dist_pred_net", obsgoal_cond=condition)
        torch.cuda.synchronize()

    def _prepare_image(self, image: Image.Image) -> torch.Tensor:
        image = image.convert("RGB").resize(self.image_size)
        return self.transform(image)

    def _node_tensors(self, map_dir: Path, node_files: List[Path]) -> torch.Tensor:
        """获取（并缓存）拓扑图全部节点的预处理张量。

        优化点：原实现对每一帧都要重新 Image.open + resize + normalize 5~9 张
        节点图（radius=4），是纯重复劳动。节点图在会话期间不变，因此可安全缓存。

        缓存键为 (地图目录, 节点文件名列表, 各文件 mtime 与大小)，
        任何文件变动都会使缓存失效并重新计算，保证与实时解码**逐字节等价**。
        """
        signature = tuple(
            (p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in node_files
        )
        cache_key = (str(map_dir), signature)
        cached = self._node_cache.get(cache_key)
        if cached is not None:
            return cached

        # 按原有顺序逐个预处理，结果与 predict() 中逐帧调用 _prepare_image 完全一致
        tensors = [self._prepare_image(Image.open(path)) for path in node_files]
        stacked = torch.stack(tensors, dim=0)          # CPU 上缓存，避免占用显存
        # 仅保留最近若干个地图的缓存，防止内存无限增长
        if len(self._node_cache) >= self._node_cache_limit:
            self._node_cache.pop(next(iter(self._node_cache)))
        self._node_cache[cache_key] = stacked
        return stacked

    @staticmethod
    def _node_id(root: Path, node: Path) -> str:
        return str(node.relative_to(root)).replace("\\", "/")

    @staticmethod
    def _direction(waypoint: np.ndarray) -> str:
        x, y = float(waypoint[0]), float(waypoint[1])
        if x < -0.2:
            return "back"
        if y > 0.3:
            return "left"
        if y < -0.3:
            return "right"
        if x < 0.2:
            return "unknown"
        return "forward"

    def predict(
        self,
        session_id: str,
        session: Dict[str, Any],
        map_dir: Path,
        node_files: List[Path],
        frame_bytes: bytes,
        num_samples: int = 4,
        radius: int = 4,
        waypoint_index: int = 2,
    ) -> Dict[str, Any]:
        image = Image.open(io.BytesIO(frame_bytes)).convert("RGB")
        context = self.frames.setdefault(
            session_id,
            deque(maxlen=self.context_size + 1),
        )
        context.append(image)
        if len(context) < self.context_size + 1:
            return {
                "status": "warming_up",
                "frames_received": len(context),
                "frames_required": self.context_size + 1,
                "direction": None,
            }

        node_ids = [self._node_id(map_dir, node) for node in node_files]
        try:
            goal_index = node_ids.index(session["destination_node"])
        except ValueError as exc:
            raise RuntimeError("destination node is no longer present") from exc
        closest = int(session.get("closest_node_index", 0))

        # ---- 失锁恢复机制 ----
        # 问题：搜索窗口固定为 closest ± radius。一旦某一帧误判使 closest 落后
        # 真实位置超过 radius，真实节点就永远落在窗口外，后续所有帧都无法恢复
        # （跨会话实验中第 69 帧误判 7 个节点后，系统最高只到 71% 且持续倒退）。
        # 处理：若连续若干帧的最佳距离都高于阈值，说明当前位置不可信，
        # 本轮临时扩大搜索窗口以重新捕获真实位置。
        lost_streak = int(session.get("lost_streak", 0))
        expanded = lost_streak >= self.LOST_PATIENCE
        search_radius = radius * self.LOST_RADIUS_MULTIPLIER if expanded else radius

        start = max(closest - search_radius, 0)
        end = min(closest + search_radius, goal_index)
        if end < start:
            start = end = goal_index

        with self.lock, torch.inference_mode():
            obs = torch.stack([self._prepare_image(frame) for frame in context], dim=0)
            obs = obs.reshape(1, -1, obs.shape[-2], obs.shape[-1]).to(self.device)
            # 使用缓存的全量节点张量，避免每帧重复解码节点图（精度完全一致）
            all_goals = self._node_tensors(map_dir, node_files)
            goals = all_goals[start : end + 1].to(self.device)
            batch_obs = obs.repeat(goals.shape[0], 1, 1, 1)
            mask = torch.zeros(goals.shape[0], dtype=torch.long, device=self.device)
            conditions = self.model(
                "vision_encoder",
                obs_img=batch_obs,
                goal_img=goals,
                input_goal_mask=mask,
            )
            distances = self.model("dist_pred_net", obsgoal_cond=conditions).flatten()
            local_index = int(torch.argmin(distances).item())
            closest = start + local_index
            best_distance = float(distances[local_index].item())

            # ---- 更新失锁计数 ----
            # 最佳距离偏大说明当前帧与窗口内所有节点都不像，位置可能已失锁
            if best_distance > self.LOST_DISTANCE_THRESHOLD:
                lost_streak += 1
            else:
                lost_streak = 0

            close_threshold = 3.0
            subgoal_local = min(
                local_index + int(float(distances[local_index].item()) < close_threshold),
                conditions.shape[0] - 1,
            )
            condition = conditions[subgoal_local].unsqueeze(0).repeat(num_samples, 1)

            actions = torch.randn(
                num_samples,
                int(self.config["len_traj_pred"]),
                2,
                device=self.device,
            )
            self.scheduler.set_timesteps(int(self.config["num_diffusion_iters"]))
            for timestep in self.scheduler.timesteps:
                noise = self.model(
                    "noise_pred_net",
                    sample=actions,
                    timestep=timestep,
                    global_cond=condition,
                )
                actions = self.scheduler.step(
                    model_output=noise,
                    timestep=timestep,
                    sample=actions,
            ).prev_sample

            normalized = actions.detach().cpu().numpy()
            minimum = np.array([-2.5, -4.0], dtype=np.float32)
            maximum = np.array([5.0, 4.0], dtype=np.float32)
            deltas = ((normalized + 1.0) / 2.0) * (maximum - minimum) + minimum
            trajectories = np.cumsum(deltas, axis=1)
            waypoint_candidates = trajectories[:, min(waypoint_index, trajectories.shape[1] - 1)]
            consensus = np.median(waypoint_candidates, axis=0)
            selected_index = int(np.argmin(np.linalg.norm(waypoint_candidates - consensus, axis=1)))
            selected = trajectories[selected_index]
            waypoint = selected[min(waypoint_index, len(selected) - 1)]

        session["closest_node_index"] = closest
        session["current_node"] = node_ids[closest]
        session["lost_streak"] = lost_streak
        previous_waypoint = session.get("smoothed_waypoint")
        if previous_waypoint is not None and len(previous_waypoint) == 2:
            waypoint = 0.65 * np.asarray(previous_waypoint, dtype=np.float32) + 0.35 * waypoint
        session["smoothed_waypoint"] = waypoint.astype(np.float32).tolist()
        arrived = closest >= goal_index
        return {
            "status": "arrived" if arrived else "guiding",
            "current_node": node_ids[closest],
            "destination_node": session["destination_node"],
            "distance_score": float(distances[local_index].item()),
            "direction": "arrived" if arrived else self._direction(waypoint),
            "waypoint": [float(value) for value in waypoint],
            "trajectory": [[float(x), float(y)] for x, y in selected],
            "candidate_trajectories": trajectories.tolist(),
        }
