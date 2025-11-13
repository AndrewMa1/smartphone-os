from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, Optional

import cv2
from .camera_manager import CameraManager

LOGGER = logging.getLogger(__name__)


def create_record_directory(base_dir: Path) -> Path:
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    target = base_dir / timestamp
    target.mkdir(parents=True, exist_ok=True)
    return target


@dataclass
class RecordingTarget:
    camera_id: str
    video_writer: cv2.VideoWriter


class RecordingSession:
    def __init__(
        self,
        camera_manager: CameraManager,
        record_dir: Path,
        camera_ids: Iterable[str],
        fps: float = 30.0,
        fourcc: str = "mp4v",
    ) -> None:
        self._camera_manager = camera_manager
        self._record_dir = record_dir
        self._camera_ids = list(camera_ids)
        self._fps = fps
        self._fourcc = cv2.VideoWriter_fourcc(*fourcc)

        self._targets: Dict[str, RecordingTarget] = {}
        self._thread: Optional[threading.Thread] = None
        self._running = threading.Event()

    def start(self) -> bool:
        if self.is_active:
            LOGGER.warning("Recording session already active")
            return False

        if not self._prepare_targets():
            self._release_targets()
            return False

        self._running.set()
        self._thread = threading.Thread(target=self._record_loop, daemon=True)
        self._thread.start()
        LOGGER.info("Recording session started at %s", self._record_dir)
        return True

    def stop(self) -> None:
        if not self.is_active:
            return

        self._running.clear()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

        self._release_targets()
        LOGGER.info("Recording session stopped")

    @property
    def is_active(self) -> bool:
        return self._running.is_set()

    @property
    def record_dir(self) -> Path:
        return self._record_dir

    def _prepare_targets(self) -> bool:
        for camera_id in self._camera_ids:
            frame = self._camera_manager.get_frame(camera_id)
            if frame is None:
                LOGGER.error("Cannot initialize recording; camera %s has no frame", camera_id)
                return False

            height, width = frame.shape[:2]
            video_path = self._record_dir / f"{camera_id}.mp4"
            writer = cv2.VideoWriter(str(video_path), self._fourcc, self._fps, (width, height))
            if not writer.isOpened():
                LOGGER.error("Failed to open video writer for %s", video_path)
                return False

            self._targets[camera_id] = RecordingTarget(camera_id=camera_id, video_writer=writer)

        return True

    def _record_loop(self) -> None:
        interval = 1.0 / self._fps
        next_tick = time.perf_counter()

        while self._running.is_set():
            now = time.perf_counter()
            if now < next_tick:
                time.sleep(next_tick - now)

            for camera_id, target in list(self._targets.items()):
                frame = self._camera_manager.get_frame(camera_id)
                if frame is None:
                    LOGGER.warning("Skipping frame for %s; no data", camera_id)
                    continue

                if frame.ndim == 2:
                    frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)

                target.video_writer.write(frame)

            next_tick = max(next_tick + interval, time.perf_counter())

    def _release_targets(self) -> None:
        for target in self._targets.values():
            target.video_writer.release()
        self._targets.clear()


class RecordingManager:
    def __init__(self, base_dir: Path, camera_manager: CameraManager) -> None:
        self._base_dir = base_dir
        self._camera_manager = camera_manager
        self._current_session: Optional[RecordingSession] = None
        self._lock = threading.Lock()

    @property
    def active(self) -> bool:
        return self._current_session is not None and self._current_session.is_active

    @property
    def record_dir(self) -> Optional[Path]:
        if self._current_session is None:
            return None
        return self._current_session._record_dir

    def start(self, camera_ids: Iterable[str]) -> Optional[Path]:
        with self._lock:
            if self.active:
                LOGGER.warning("A recording session is already active")
                return self._current_session.record_dir if self._current_session else None

            target_dir = create_record_directory(self._base_dir)
            session = RecordingSession(
                camera_manager=self._camera_manager,
                record_dir=target_dir,
                camera_ids=camera_ids,
            )

            if not session.start():
                LOGGER.error("Unable to start recording session")
                return None

            self._current_session = session
            return session.record_dir

    def stop(self) -> Optional[Path]:
        with self._lock:
            if not self.active or self._current_session is None:
                return None

            record_dir = self._current_session.record_dir
            self._current_session.stop()
            self._current_session = None
            return record_dir

