"""Validate that a NoMaD checkpoint exactly matches the configured model."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import torch
import yaml


def build_model(runtime_root: Path, config: dict):
    sys.path.insert(0, str(runtime_root))
    from diffusion_policy.model.diffusion.conditional_unet1d import ConditionalUnet1D
    from vint_train.models.nomad.nomad import DenseNetwork, NoMaD
    from vint_train.models.nomad.nomad_vint import NoMaD_ViNT, replace_bn_with_gn

    encoder = NoMaD_ViNT(
        obs_encoding_size=config["encoding_size"],
        context_size=config["context_size"],
        mha_num_attention_heads=config["mha_num_attention_heads"],
        mha_num_attention_layers=config["mha_num_attention_layers"],
        mha_ff_dim_factor=config["mha_ff_dim_factor"],
    )
    encoder = replace_bn_with_gn(encoder)
    noise_predictor = ConditionalUnet1D(
        input_dim=2,
        global_cond_dim=config["encoding_size"],
        down_dims=config["down_dims"],
        cond_predict_scale=config["cond_predict_scale"],
    )
    distance_predictor = DenseNetwork(embedding_dim=config["encoding_size"])
    return NoMaD(
        vision_encoder=encoder,
        noise_pred_net=noise_predictor,
        dist_pred_net=distance_predictor,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    args = parser.parse_args()

    config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    model = build_model(args.runtime_root.resolve(), config)
    checkpoint = torch.load(args.checkpoint, map_location="cpu")
    if not isinstance(checkpoint, dict):
        raise TypeError(f"checkpoint must be a state dict, got {type(checkpoint).__name__}")

    expected = model.state_dict()
    expected_keys = set(expected)
    actual_keys = set(checkpoint)
    missing = sorted(expected_keys - actual_keys)
    unexpected = sorted(actual_keys - expected_keys)
    mismatched = sorted(
        key
        for key in expected_keys & actual_keys
        if tuple(expected[key].shape) != tuple(checkpoint[key].shape)
    )
    print(f"expected_keys={len(expected_keys)} checkpoint_keys={len(actual_keys)}")
    print(f"missing_keys={len(missing)} unexpected_keys={len(unexpected)} shape_mismatches={len(mismatched)}")
    if missing:
        print("missing:", missing[:20])
    if unexpected:
        print("unexpected:", unexpected[:20])
    if mismatched:
        print(
            "shape mismatches:",
            [
                (key, tuple(expected[key].shape), tuple(checkpoint[key].shape))
                for key in mismatched[:20]
            ],
        )
    if missing or unexpected or mismatched:
        return 1

    model.load_state_dict(checkpoint, strict=True)
    print("strict_load=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
