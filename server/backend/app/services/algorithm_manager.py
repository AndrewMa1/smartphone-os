from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Iterable, Optional

import numpy as np

from .camera_manager import CameraManager


@dataclass
class AlgorithmState:
    algorithm_id: str
    display_name: str
    description: str
    required_cameras: Iterable[str] = field(default_factory=list)
    running: bool = False
    last_sample_at: Optional[float] = None
    last_frame_shapes: Dict[str, Optional[tuple[int, ...]]] = field(default_factory=dict)


class AlgorithmManager:
    """Manage lifecycle of vision algorithms that consume camera streams."""

    def __init__(self, camera_manager: CameraManager) -> None:
        self._camera_manager = camera_manager
        self._states: Dict[str, AlgorithmState] = {
            "eye_tracking": AlgorithmState(
                algorithm_id="eye_tracking",
                display_name="眼动算法",
                description="基于双目近眼红外摄像头的眼动识别算法。",
                required_cameras=["eye0", "eye1", "world"],
            ),
        }
        self._lock = threading.Lock()

    def list_algorithms(self) -> Iterable[AlgorithmState]:
        with self._lock:
            return list(self._states.values())

    def get_state(self, algorithm_id: str) -> Optional[AlgorithmState]:
        with self._lock:
            return self._states.get(algorithm_id)

    def start(self, algorithm_id: str) -> AlgorithmState:
        with self._lock:
            state = self._states.get(algorithm_id)
            if state is None:
                raise KeyError(algorithm_id)

            if state.running:
                return state

            required_cameras = (
                list(state.required_cameras) if state.required_cameras else [cfg.camera_id for cfg in self._camera_manager.available_cameras()]
            )
            state.required_cameras = required_cameras

        for camera_id in required_cameras:
            self._camera_manager.ensure_started(camera_id)

        # Snapshot current frame metadata
        frame_shapes: Dict[str, Optional[tuple[int, ...]]] = {}
        for camera_id in required_cameras:
            frame = self._camera_manager.get_frame(camera_id)
            frame_shapes[camera_id] = frame.shape if frame is not None else None
        

        with self._lock:
            state = self._states.get(algorithm_id)
            if state is None:
                raise KeyError(algorithm_id)
            state.last_sample_at = time.time()
            state.last_frame_shapes = frame_shapes
            state.running = True
            return state

    def stop(self, algorithm_id: str) -> AlgorithmState:
        with self._lock:
            state = self._states.get(algorithm_id)
            if state is None:
                raise KeyError(algorithm_id)

            state.running = False
            return state

    def get_latest_frames(self, algorithm_id: str) -> Dict[str, Optional[np.ndarray]]:
        with self._lock:
            state = self._states.get(algorithm_id)
            if state is None:
                raise KeyError(algorithm_id)
            camera_ids = list(state.required_cameras) if state.required_cameras else [
                cfg.camera_id for cfg in self._camera_manager.available_cameras()
            ]

        frames: Dict[str, Optional[np.ndarray]] = {}
        shapes: Dict[str, Optional[tuple[int, ...]]] = {}
        for camera_id in camera_ids:
            frame = self._camera_manager.get_frame(camera_id)
            frames[camera_id] = frame.copy() if frame is not None else None
            shapes[camera_id] = frame.shape if frame is not None else None

        with self._lock:
            state = self._states.get(algorithm_id)
            if state is None:
                raise KeyError(algorithm_id)
            state.last_sample_at = time.time()
            state.last_frame_shapes = shapes

        return frames


