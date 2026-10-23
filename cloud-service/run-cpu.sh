#!/usr/bin/env bash
set -euo pipefail

service_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export WSPLUS_DATA_ROOT="${WSPLUS_DATA_ROOT:-${service_dir}/data}"
python_bin="${WSPLUS_API_PYTHON:-/root/wsplus-api-venv/bin/python}"

cd "${service_dir}"
exec "${python_bin}" -m uvicorn app:app --host 0.0.0.0 --port "${WSPLUS_PORT:-8000}"
