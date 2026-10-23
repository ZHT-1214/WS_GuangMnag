"""WS_plus cloud API.

The API layer is usable without a GPU. Vision inference is deliberately kept
behind a capability check so an online server cannot be mistaken for a ready
navigation model.
"""

from __future__ import annotations

import json
import asyncio
import hmac
import os
import shutil
import tempfile
import uuid
import zipfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from tencent_asr import configured as _voice_asr_configured, transcribe_wav


SERVICE_VERSION = "0.1.0"
DATA_ROOT = Path(os.getenv("WSPLUS_DATA_ROOT", Path(__file__).with_name("data")))
MAP_ROOT = DATA_ROOT / "maps"
MAX_UPLOAD_BYTES = int(os.getenv("WSPLUS_MAX_MAP_BYTES", str(1024 * 1024 * 1024)))
MAX_ZIP_ENTRIES = int(os.getenv("WSPLUS_MAX_ZIP_ENTRIES", "20000"))
ALLOWED_NODE_SUFFIXES = {".jpg", ".jpeg", ".png"}
API_TOKEN = os.getenv("WSPLUS_API_TOKEN", "")

app = FastAPI(title="WS_plus Cloud Service", version=SERVICE_VERSION)
_sessions: Dict[str, Dict[str, Any]] = {}
_backend = None
_backend_error: Optional[str] = "NoMaD backend is disabled"


@app.middleware("http")
async def require_api_token(request: Request, call_next):
    if API_TOKEN and request.url.path not in {"/health", "/docs", "/openapi.json"}:
        supplied = request.headers.get("Authorization", "")
        expected = f"Bearer {API_TOKEN}"
        if not hmac.compare_digest(supplied, expected):
            return JSONResponse(status_code=401, content={"detail": "invalid API token"})
    return await call_next(request)


class NavigationSessionRequest(BaseModel):
    map_id: str = Field(min_length=1, max_length=200)
    destination_node: str = Field(min_length=1, max_length=200)


class NavigationSessionResponse(BaseModel):
    session_id: str
    map_id: str
    destination_node: str
    status: str
    inference_ready: bool
    message: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_child(root: Path, name: str) -> Path:
    """Resolve a user supplied path while preventing traversal."""
    if not name or Path(name).is_absolute():
        raise HTTPException(status_code=400, detail="invalid archive path")
    target = (root / name).resolve()
    root_resolved = root.resolve()
    if target != root_resolved and root_resolved not in target.parents:
        raise HTTPException(status_code=400, detail="archive contains an unsafe path")
    return target


def _node_files(root: Path) -> List[Path]:
    return sorted(
        (
            p
            for p in root.rglob("*")
            if p.is_file()
            and p.suffix.lower() in ALLOWED_NODE_SUFFIXES
            and p.stem.isdigit()
        ),
        key=lambda p: (str(p.parent), int(p.stem) if p.stem.isdigit() else 10**12, p.name),
    )


def _map_summary(map_dir: Path) -> Dict[str, Any]:
    nodes = _node_files(map_dir)
    return {
        "id": map_dir.name,
        "name": map_dir.name,
        "version": 1,
        "node_count": len(nodes),
        "nodes": [str(p.relative_to(map_dir)).replace(os.sep, "/") for p in nodes],
    }


def _node_id(map_dir: Path, node: Path) -> str:
    return str(node.relative_to(map_dir)).replace(os.sep, "/")


def _inference_ready() -> bool:
    return _backend is not None


def _gpu_visible() -> bool:
    if Path("/dev/nvidia0").exists() or os.getenv("NVIDIA_VISIBLE_DEVICES"):
        return True
    try:
        import torch

        return torch.cuda.is_available()
    except Exception:
        return False


def _yoso_request(path: str, payload: Optional[bytes] = None) -> Dict[str, Any]:
    headers = {"Content-Type": "image/jpeg"} if payload is not None else {}
    request = urllib.request.Request(
        f"http://127.0.0.1:{os.getenv('WSPLUS_YOSO_PORT', '8001')}{path}",
        data=payload,
        headers=headers,
        method="POST" if payload is not None else "GET",
    )
    timeout = 60 if payload is not None else 2
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


async def _call_yoso(path: str, payload: Optional[bytes] = None) -> Dict[str, Any]:
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(None, lambda: _yoso_request(path, payload))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise HTTPException(status_code=error.code, detail=detail) from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise HTTPException(status_code=503, detail="YOSO vision service is unavailable") from error


@app.on_event("startup")
def startup() -> None:
    global _backend, _backend_error
    MAP_ROOT.mkdir(parents=True, exist_ok=True)
    if os.getenv("WSPLUS_NOMAD_ENABLED", "0").lower() not in {"1", "true", "yes"}:
        return
    try:
        from inference import NomadBackend

        _backend = NomadBackend(
            runtime_root=Path(os.environ["WSPLUS_RUNTIME_ROOT"]),
            config_path=Path(os.environ["WSPLUS_NOMAD_CONFIG"]),
            checkpoint_path=Path(os.environ["WSPLUS_NOMAD_CHECKPOINT"]),
        )
        _backend.warmup()
        _backend_error = None
    except Exception as error:
        _backend = None
        _backend_error = f"{type(error).__name__}: {error}"


@app.get("/health")
def health() -> Dict[str, Any]:
    try:
        yoso_health = _yoso_request("/health")
    except Exception:
        yoso_health = {"status": "offline", "inference_ready": False}
    return {
        "service": "wsplus-cloud",
        "version": SERVICE_VERSION,
        "status": "ok",
        "gpu_visible": _gpu_visible(),
        "inference_ready": _inference_ready(),
        "inference_error": _backend_error,
        "capabilities": {
            "map_management": True,
            "navigation_sessions": True,
            "visual_inference": _inference_ready(),
            "yoso_vision": bool(yoso_health.get("inference_ready")),
            "voice_asr": _voice_asr_configured(),
        },
        "yoso": yoso_health,
        "time": _now(),
    }


async def _read_vision_frame(file: UploadFile) -> bytes:
    payload = await file.read(8 * 1024 * 1024 + 1)
    if not payload or len(payload) > 8 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="frame must be between 1 byte and 8 MB")
    return payload


@app.post("/v1/vision/obstacle")
async def vision_obstacle(file: UploadFile = File(...)) -> Dict[str, Any]:
    return await _call_yoso("/v1/vision/obstacle", await _read_vision_frame(file))


@app.post("/v1/vision/find")
async def vision_find(item: str, file: UploadFile = File(...)) -> Dict[str, Any]:
    if not item.strip():
        raise HTTPException(status_code=400, detail="item is required")
    path = "/v1/vision/find?item=" + urllib.parse.quote(item.strip(), safe="")
    return await _call_yoso(path, await _read_vision_frame(file))


@app.post("/v1/vision/describe")
async def vision_describe(file: UploadFile = File(...)) -> Dict[str, Any]:
    return await _call_yoso("/v1/vision/describe", await _read_vision_frame(file))


@app.post("/v1/voice/transcribe")
async def transcribe_voice(file: UploadFile = File(...)) -> Dict[str, Any]:
    audio = await file.read(1024 * 1024 + 1)
    if not audio or len(audio) > 1024 * 1024:
        raise HTTPException(status_code=413, detail="audio must be between 1 byte and 1 MB")
    if not _voice_asr_configured():
        raise HTTPException(status_code=503, detail="cloud speech recognition is not configured")
    loop = asyncio.get_running_loop()
    try:
        text = await loop.run_in_executor(None, lambda: transcribe_wav(audio))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return {"text": text}


@app.get("/v1/maps")
def list_maps() -> Dict[str, Any]:
    maps = [_map_summary(p) for p in sorted(MAP_ROOT.iterdir()) if p.is_dir()]
    return {"maps": maps}


@app.post("/v1/maps", status_code=201)
async def upload_map(file: UploadFile = File(...)) -> Dict[str, Any]:
    if not (file.filename or "").lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="map upload must be a ZIP file")

    map_id = uuid.uuid4().hex
    staging = Path(tempfile.mkdtemp(prefix="map-", dir=str(DATA_ROOT)))
    archive_path = staging / "upload.zip"
    total = 0
    try:
        with archive_path.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="map archive is too large")
                output.write(chunk)

        extract_root = staging / "content"
        extract_root.mkdir()
        with zipfile.ZipFile(archive_path) as archive:
            if len(archive.infolist()) > MAX_ZIP_ENTRIES:
                raise HTTPException(status_code=413, detail="map archive has too many entries")
            if sum(info.file_size for info in archive.infolist()) > MAX_UPLOAD_BYTES:
                raise HTTPException(status_code=413, detail="uncompressed map is too large")
            for info in archive.infolist():
                target = _safe_child(extract_root, info.filename)
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)

        nodes = _node_files(extract_root)
        if not nodes:
            raise HTTPException(status_code=400, detail="map archive contains no JPG/PNG node images")
        destination = MAP_ROOT / map_id
        shutil.move(str(extract_root), str(destination))
        summary = _map_summary(destination)
        (destination / "manifest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        return summary
    finally:
        shutil.rmtree(staging, ignore_errors=True)


@app.delete("/v1/maps/{map_id}")
def delete_map(map_id: str) -> Dict[str, Any]:
    target = _safe_child(MAP_ROOT, map_id)
    if not target.is_dir():
        raise HTTPException(status_code=404, detail="map not found")
    shutil.rmtree(target)
    return {"deleted": True, "map_id": map_id}


@app.post("/v1/navigation/sessions", response_model=NavigationSessionResponse, status_code=201)
def create_session(request: NavigationSessionRequest) -> NavigationSessionResponse:
    map_dir = _safe_child(MAP_ROOT, request.map_id)
    if not map_dir.is_dir():
        raise HTTPException(status_code=404, detail="map not found")
    nodes = _node_files(map_dir)
    if request.destination_node not in {_node_id(map_dir, node) for node in nodes}:
        raise HTTPException(status_code=400, detail="destination node not found in map")
    session_id = uuid.uuid4().hex
    ready = _inference_ready()
    status = "ready" if ready else "waiting_for_model"
    message = "visual navigation ready" if ready else "visual navigation model is not loaded; no direction will be returned"
    _sessions[session_id] = {
        "session_id": session_id,
        "map_id": request.map_id,
        "destination_node": request.destination_node,
        "status": status,
        "inference_ready": ready,
        "created_at": _now(),
        "last_frame_at": None,
    }
    return NavigationSessionResponse(
        session_id=session_id,
        map_id=request.map_id,
        destination_node=request.destination_node,
        status=status,
        inference_ready=ready,
        message=message,
    )


@app.get("/v1/navigation/sessions/{session_id}")
def session_status(session_id: str) -> Dict[str, Any]:
    session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="navigation session not found")
    return session


@app.post("/v1/navigation/sessions/{session_id}/frames")
async def submit_frame(session_id: str, file: UploadFile = File(...)) -> Dict[str, Any]:
    session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="navigation session not found")
    if not _inference_ready():
        raise HTTPException(
            status_code=503,
            detail={"message": "visual navigation model is not ready", "reason": _backend_error},
        )
    payload = await file.read(8 * 1024 * 1024 + 1)
    if len(payload) > 8 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="frame is too large")
    session["last_frame_at"] = _now()
    map_dir = _safe_child(MAP_ROOT, session["map_id"])
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(
            None,
            lambda: _backend.predict(
                session_id=session_id,
                session=session,
                map_dir=map_dir,
                node_files=_node_files(map_dir),
                frame_bytes=payload,
            ),
        )
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"visual inference failed: {type(error).__name__}: {error}",
        ) from error
    session["status"] = result["status"]
    return {"status": "ok", "inference_ready": True, "result": result}
