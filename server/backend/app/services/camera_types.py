from dataclasses import dataclass, field
from typing import Optional


@dataclass
class FrameTransform:
    rotate_code: Optional[int] = None
    flip_horizontal: bool = False
    flip_vertical: bool = False


@dataclass
class CameraConfig:
    camera_id: str
    device_index: int
    display_name: str
    frame_width: int = 640
    frame_height: int = 480
    fps: float = 30.0
    backend: Optional[int] = None
    fourcc: Optional[str] = None
    transform: FrameTransform = field(default_factory=FrameTransform)
    access_method: str = "opencv"
    vendor_id: Optional[int] = None
    product_id: Optional[int] = None
    serial_number: Optional[str] = None
    device_uid: Optional[str] = None
    device_address: Optional[int] = None

