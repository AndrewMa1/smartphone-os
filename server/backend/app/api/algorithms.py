from __future__ import annotations

import time
from typing import Iterable

import cv2
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..dependencies import get_algorithm_manager
from ..services.algorithm_manager import AlgorithmManager, AlgorithmState

router = APIRouter()


class AlgorithmInfo(BaseModel):
    algorithm_id: str
    display_name: str
    description: str
    running: bool
    last_sample_at: float | None
    last_frame_shapes: dict[str, tuple[int, ...] | None]

    @classmethod
    def from_state(cls, state: AlgorithmState) -> "AlgorithmInfo":
        return cls(
            algorithm_id=state.algorithm_id,
            display_name=state.display_name,
            description=state.description,
            running=state.running,
            last_sample_at=state.last_sample_at,
            last_frame_shapes=state.last_frame_shapes,
        )


@router.get("/", response_model=list[AlgorithmInfo])
def list_algorithms(manager: AlgorithmManager = Depends(get_algorithm_manager)) -> Iterable[AlgorithmInfo]:
    return [AlgorithmInfo.from_state(state) for state in manager.list_algorithms()]


@router.post("/{algorithm_id}/start", response_model=AlgorithmInfo, status_code=status.HTTP_202_ACCEPTED)
def start_algorithm(algorithm_id: str, manager: AlgorithmManager = Depends(get_algorithm_manager)) -> AlgorithmInfo:
    try:
        state = manager.start(algorithm_id)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="算法不存在")
    return AlgorithmInfo.from_state(state)


@router.post("/{algorithm_id}/stop", response_model=AlgorithmInfo, status_code=status.HTTP_202_ACCEPTED)
def stop_algorithm(algorithm_id: str, manager: AlgorithmManager = Depends(get_algorithm_manager)) -> AlgorithmInfo:
    try:
        state = manager.stop(algorithm_id)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="算法不存在")
    return AlgorithmInfo.from_state(state)


@router.get("/{algorithm_id}/stream/{camera_id}")
def stream_algorithm_camera(algorithm_id: str, camera_id: str, manager: AlgorithmManager = Depends(get_algorithm_manager)) -> StreamingResponse:
    state = manager.get_state(algorithm_id)
    if state is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="算法不存在")

    if not state.running:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="算法未运行")

    required_cameras = list(state.required_cameras) if state.required_cameras else None
    if required_cameras is not None and camera_id not in required_cameras:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="未订阅该摄像头")

    boundary = "frame"

    def iterator() -> Iterable[bytes]:
        while True:
            try:
                frames = manager.get_latest_frames(algorithm_id)
            except KeyError:
                break

            frame = frames.get(camera_id)
            if frame is None:
                time.sleep(0.05)
                continue

            success, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if not success:
                time.sleep(0.05)
                continue

            payload = encoded.tobytes()
            yield (
                b"--" + boundary.encode() + b"\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Content-Length: " + str(len(payload)).encode() + b"\r\n\r\n" + payload + b"\r\n"
            )
            time.sleep(1.0 / 30.0)

    headers = {"Cache-Control": "no-cache", "Pragma": "no-cache"}
    media_type = f"multipart/x-mixed-replace; boundary={boundary}"
    return StreamingResponse(iterator(), media_type=media_type, headers=headers)

