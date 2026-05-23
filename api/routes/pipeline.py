from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.pipeline_manager import PipelineManager

router = APIRouter(prefix="/pipeline", tags=["pipeline"])

_CAMERA_CONFIG_PATH = Path("configs/camera.local.json")


def _get_manager() -> PipelineManager:
    """Overridden in api/main.py after the manager is created."""
    raise RuntimeError("PipelineManager not initialised")  # pragma: no cover


class PipelineStartIn(BaseModel):
    adapter: str = "mock"
    nvidia_endpoint: str = ""
    nvidia_api_key: str = ""


@router.get("/status")
def pipeline_status(manager: PipelineManager = Depends(_get_manager)) -> dict:
    """Return the current state of the vision pipeline subprocess."""
    return manager.status


@router.post("/start")
def pipeline_start(
    req: PipelineStartIn,
    manager: PipelineManager = Depends(_get_manager),
) -> dict:
    """(Re)start the pipeline with a given adapter without re-saving camera config."""
    if not _CAMERA_CONFIG_PATH.exists():
        raise HTTPException(status_code=404, detail="No camera config found. Save camera config first.")
    manager.start(
        config_path=str(_CAMERA_CONFIG_PATH),
        adapter=req.adapter,
        nvidia_endpoint=req.nvidia_endpoint or None,
        nvidia_api_key=req.nvidia_api_key or None,
    )
    return {"status": "started", "adapter": req.adapter}


@router.post("/stop")
def pipeline_stop(manager: PipelineManager = Depends(_get_manager)) -> dict:
    """Stop the running pipeline subprocess (camera config is preserved)."""
    manager.stop()
    return {"status": "stopped"}
