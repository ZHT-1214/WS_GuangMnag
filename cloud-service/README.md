# WS_plus cloud service

This service is the Android-facing protocol layer. It can run on a CPU-only
server for map management and session handling. Topology navigation uses the
NoMaD backend; camera assistance uses the optional YOSO sidecar.

Set `WSPLUS_NOMAD_ENABLED=1` together with `WSPLUS_RUNTIME_ROOT`,
`WSPLUS_NOMAD_CONFIG`, and `WSPLUS_NOMAD_CHECKPOINT` to load the GPU backend.
Set `WSPLUS_API_TOKEN` before exposing the service outside a local or SSH tunnel;
map and navigation endpoints then require `Authorization: Bearer <token>`.

## Local run

```bash
python -m pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8000
```

The GPU runtime uses `requirements-gpu.txt` from a Python environment that
already contains a CUDA-compatible PyTorch build.

## YOSO camera service

Run `yoso_service.py` with the Python environment that contains YOSO,
Detectron2, PyTorch, and OpenCV. It listens on `127.0.0.1:8001` by default;
keep it on loopback because the Android-facing API proxies requests to it.

```bash
cd /root/wsplus-cloud
nohup env \
  WSPLUS_YOSO_ROOT=/root/YOSO \
  WSPLUS_YOSO_CONFIG=/root/YOSO/projects/YOSO/configs/coco/panoptic-segmentation/YOSO-R50.yaml \
  WSPLUS_YOSO_CHECKPOINT='/root/ws/modle1/yoso_res50_coco (1).pth' \
  /root/miniconda3/envs/YOSO/bin/python yoso_service.py \
  > yoso-service.log 2>&1 < /dev/null &
```

`GET /health` reports YOSO readiness under `yoso.inference_ready` and
`capabilities.yoso_vision`. The app sends JPEG frames to the following routes:

- `POST /v1/vision/obstacle`: returns a suggested direction or asks the user to stop and confirm.
- `POST /v1/vision/find?item=<name>`: searches common COCO items and reports a 3x3 image position.
- `POST /v1/vision/describe`: summarizes recognized object and scene categories.

YOSO segmentation does not provide metric distance or reliable spatial
relationships. Treat directions as assistance only, retain the white cane,
and stop to confirm when the result is uncertain. The scene response is a
category summary, not open-ended visual question answering.

## Tencent Cloud speech recognition

Set `WSPLUS_TENCENT_SECRET_ID`, `WSPLUS_TENCENT_SECRET_KEY`, and optionally
`WSPLUS_TENCENT_REGION` in the private `.env` file next to `run-gpu.sh`. The
script loads this file before starting the API; do not put these credentials in
the Android app or commit `.env`.

- `POST /v1/voice/transcribe`: multipart field `file` containing 16 kHz mono PCM WAV audio (up to 1 MB).
- `GET /health`: reports availability under `capabilities.voice_asr`.

## Endpoints

- `GET /health`: service and inference capability status.
- `GET /v1/maps`: imported topology maps.
- `POST /v1/maps`: multipart ZIP upload.
- `DELETE /v1/maps/{map_id}`: remove a map.
- `POST /v1/navigation/sessions`: create a session with `map_id` and `destination_node`.
- `GET /v1/navigation/sessions/{session_id}`: inspect session state.
- `POST /v1/navigation/sessions/{session_id}/frames`: submit a camera frame. Returns
  `503` until the GPU model backend is ready.
