from __future__ import annotations

import time
from typing import Iterable, Iterator

import cv2
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..dependencies import get_camera_manager
from ..services.camera_manager import CameraManager

router = APIRouter()


class CameraInfo(BaseModel):
    camera_id: str
    display_name: str
    running: bool
    width: int
    height: int
    fps: float
    last_frame_ts: float


@router.get("/", response_model=list[CameraInfo])
def list_cameras(camera_manager: CameraManager = Depends(get_camera_manager)) -> Iterable[CameraInfo]:
    snapshot = camera_manager.status_snapshot()
    result = []
    for camera_id, data in snapshot.items():
        config = data["config"]
        result.append(
            CameraInfo(
                camera_id=camera_id,
                display_name=config.display_name,
                running=data["is_running"],
                width=config.frame_width,
                height=config.frame_height,
                fps=config.fps,
                last_frame_ts=data["timestamp"],
            )
        )
    return result


@router.post("/{camera_id}/start", status_code=status.HTTP_202_ACCEPTED)
def start_camera(camera_id: str, camera_manager: CameraManager = Depends(get_camera_manager)) -> dict:
    if camera_manager.ensure_started(camera_id):
        return {"camera_id": camera_id, "status": "started"}
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="无法启动摄像头")


@router.post("/{camera_id}/stop", status_code=status.HTTP_202_ACCEPTED)
def stop_camera(camera_id: str, camera_manager: CameraManager = Depends(get_camera_manager)) -> dict:
    if camera_manager.get_config(camera_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="摄像头不存在")
    camera_manager.stop(camera_id)
    return {"camera_id": camera_id, "status": "stopped"}


@router.get("/{camera_id}/stream")
def stream_camera(camera_id: str, camera_manager: CameraManager = Depends(get_camera_manager)) -> StreamingResponse:
    config = camera_manager.get_config(camera_id)
    if config is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="摄像头不存在")

    if not camera_manager.ensure_started(camera_id):
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="摄像头启动失败")

    def frame_iterator() -> Iterator[bytes]:
        boundary = "--frame"
        sleep_interval = 1.0 / max(config.fps, 1.0)

        try:
            while True:
                frame = camera_manager.get_frame(camera_id)
                if frame is None:
                    time.sleep(0.05)
                    continue

                success, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                if not success:
                    continue

                payload = buffer.tobytes()
                yield (
                    b"%s\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"Content-Length: %d\r\n\r\n%s\r\n"
                    % (boundary.encode(), len(payload), payload)
                )
                time.sleep(sleep_interval)
        except GeneratorExit:
            return

    headers = {"Cache-Control": "no-cache", "Pragma": "no-cache"}
    return StreamingResponse(frame_iterator(), media_type="multipart/x-mixed-replace; boundary=frame", headers=headers)

