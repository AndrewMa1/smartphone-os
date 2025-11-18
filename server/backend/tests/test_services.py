from pathlib import Path

from app.services.camera_manager import CameraConfig, CameraManager, build_default_camera_manager
from app.services.camera_types import FrameTransform
from app.services.recording import RecordingManager


def test_build_default_camera_manager_configs():
    manager = build_default_camera_manager()
    configs = sorted([cfg.camera_id for cfg in manager.available_cameras()])
    assert configs == ["eye0", "eye1", "world"]


class DummyCameraManager(CameraManager):
    def __init__(self) -> None:
        dummy_config = CameraConfig(
            camera_id="dummy",
            device_index=99,
            display_name="Dummy Cam",
            transform=FrameTransform(),
        )
        super().__init__(configs=[dummy_config])

    def ensure_started(self, camera_id: str) -> bool:
        return True

    def get_frame(self, camera_id: str):
        return None


def test_recording_manager_start_fails_without_frames(tmp_path: Path):
    manager = DummyCameraManager()
    recording_manager = RecordingManager(base_dir=tmp_path, camera_manager=manager)

    record_dir = recording_manager.start(["dummy"])
    assert record_dir is None
    assert not recording_manager.active

