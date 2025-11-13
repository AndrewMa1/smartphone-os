from fastapi import Request

from .services.algorithm_manager import AlgorithmManager
from .services.camera_manager import CameraManager
from .services.recording import RecordingManager


def get_camera_manager(request: Request) -> CameraManager:
    manager = getattr(request.app.state, "camera_manager", None)
    if manager is None:
        raise RuntimeError("Camera manager has not been initialized")
    return manager


def get_recording_manager(request: Request) -> RecordingManager:
    manager = getattr(request.app.state, "recording_manager", None)
    if manager is None:
        raise RuntimeError("Recording manager has not been initialized")
    return manager


def get_algorithm_manager(request: Request) -> AlgorithmManager:
    manager = getattr(request.app.state, "algorithm_manager", None)
    if manager is None:
        raise RuntimeError("Algorithm manager has not been initialized")
    return manager

