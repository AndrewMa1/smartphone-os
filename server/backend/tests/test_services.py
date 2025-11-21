from pathlib import Path

from app.services.camera_manager import CameraConfig, CameraManager, build_default_camera_manager
from app.services.camera_types import FrameTransform
from app.services.recording import RecordingManager
from app.services import system_info


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


def test_nmea_to_decimal():
    lat = system_info._nmea_to_decimal("3723.2475", "N")
    lon = system_info._nmea_to_decimal("12158.3416", "W")
    assert lat is not None
    assert lon is not None
    assert abs(lat - 37.3874583333) < 1e-6
    assert abs(lon - (-121.97236)) < 1e-5


def test_parse_nmea_sentences_combines_rmc_and_gga():
    sentences = [
        "$GPRMC,022517.00,A,3723.2475,N,12158.3416,W,0.123,54.7,191194,,,A*68",
        "$GPGGA,022517.00,3723.2475,N,12158.3416,W,1,05,1.5,18.2,M,-25.7,M,,*76",
    ]
    parsed = system_info._parse_nmea_sentences(sentences)
    assert parsed["satellites"] == 5
    assert parsed["fix_quality"] == "GPS (1)"
    assert abs(parsed["latitude"] - 37.3874583333) < 1e-6
    assert abs(parsed["longitude"] - (-121.97236)) < 1e-5
    assert abs(parsed["altitude_m"] - 18.2) < 1e-6

