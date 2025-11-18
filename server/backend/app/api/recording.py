from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from ..dependencies import get_camera_manager, get_recording_manager
from ..services.camera_manager import CameraManager
from ..services.recording import RecordingManager

router = APIRouter()


class RecordingRequest(BaseModel):
    camera_ids: Optional[list[str]] = None


class RecordingStatus(BaseModel):
    active: bool
    record_dir: Optional[str] = None


@router.get("/status", response_model=RecordingStatus)
def get_status(recording_manager: RecordingManager = Depends(get_recording_manager)) -> RecordingStatus:
    record_dir = recording_manager.record_dir
    return RecordingStatus(active=recording_manager.active, record_dir=str(record_dir) if record_dir else None)


@router.post("/start", response_model=RecordingStatus, status_code=status.HTTP_202_ACCEPTED)
def start_recording(
    payload: RecordingRequest,
    recording_manager: RecordingManager = Depends(get_recording_manager),
    camera_manager: CameraManager = Depends(get_camera_manager),
) -> RecordingStatus:
    camera_ids = payload.camera_ids
    if not camera_ids:
        camera_ids = [cfg.camera_id for cfg in camera_manager.available_cameras()]

    for camera_id in camera_ids:
        if camera_manager.get_config(camera_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"摄像头 {camera_id} 不存在")
        camera_manager.ensure_started(camera_id)

    record_dir = recording_manager.start(camera_ids)
    if record_dir is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="无法开启录制")

    return RecordingStatus(active=True, record_dir=str(record_dir))


@router.post("/stop", response_model=RecordingStatus, status_code=status.HTTP_202_ACCEPTED)
def stop_recording(recording_manager: RecordingManager = Depends(get_recording_manager)) -> RecordingStatus:
    record_dir = recording_manager.stop()
    if record_dir is None:
        return RecordingStatus(active=False, record_dir=None)

    return RecordingStatus(active=False, record_dir=str(record_dir))

