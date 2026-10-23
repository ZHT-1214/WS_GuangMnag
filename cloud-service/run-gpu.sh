#!/usr/bin/env bash
set -euo pipefail

service_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "${service_dir}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${service_dir}/.env"
  set +a
fi
export WSPLUS_DATA_ROOT="${WSPLUS_DATA_ROOT:-${service_dir}/data}"
export WSPLUS_NOMAD_ENABLED=1
export WSPLUS_RUNTIME_ROOT="${WSPLUS_RUNTIME_ROOT:-${service_dir}/runtime}"
export WSPLUS_NOMAD_CONFIG="${WSPLUS_NOMAD_CONFIG:-${service_dir}/config/nomad.yaml}"
export WSPLUS_NOMAD_CHECKPOINT="${WSPLUS_NOMAD_CHECKPOINT:-${service_dir}/model_weights/nomad.pth}"
export PYTHONPATH="${WSPLUS_RUNTIME_ROOT}:${WSPLUS_RUNTIME_ROOT}/diffusion_policy:${PYTHONPATH:-}"
python_bin="${WSPLUS_NOMAD_PYTHON:-/root/wsplus-nomad-venv/bin/python}"

cd "${service_dir}"
exec "${python_bin}" -m uvicorn app:app --host 0.0.0.0 --port "${WSPLUS_PORT:-8000}"
