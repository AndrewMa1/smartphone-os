from __future__ import annotations

import logging
import os
import platform
import threading
import time
from typing import Dict, Iterable, Optional

import cv2
import numpy as np

from .camera_types import CameraConfig, FrameTransform

LOGGER = logging.getLogger(__name__)

ASSIGNED_LIBUVC_UIDS: set[str] = set()


class CameraStream:
    """Manage individual camera capture loop."""

    def __init__(self, config: CameraConfig) -> None:
        self.config = config
        self.capture: Optional[cv2.VideoCapture] = None
        self._uvc_capture = None
        self._uvc_uid: Optional[str] = None
        self._thread: Optional[threading.Thread] = None
        self._running = threading.Event()
        self._frame_lock = threading.Lock()
        self._latest_frame: Optional[np.ndarray] = None
        self._latest_timestamp: float = 0.0

    def start(self) -> bool:
        if self.is_running:
            return True

        if self.config.access_method == "libuvc":
            return self._start_libuvc()
        return self._start_opencv()

    def _start_opencv(self) -> bool:
        backend = self.config.backend
        if backend is not None:
            self.capture = cv2.VideoCapture(self.config.device_index, backend)
        else:
            self.capture = cv2.VideoCapture(self.config.device_index)

        if not self.capture.isOpened():
            LOGGER.error("Failed to open camera %s (index=%s)", self.config.camera_id, self.config.device_index)
            self.capture.release()
            self.capture = None
            return False

        self._configure_capture()
        self._running.set()
        self._thread = threading.Thread(target=self._capture_loop_opencv, daemon=True)
        self._thread.start()
        LOGGER.info("Camera %s started", self.config.camera_id)
        return True

    def _start_libuvc(self) -> bool:
        try:
            import uvc
        except ImportError:
            LOGGER.error("pyuvc 未安装，无法访问摄像头 %s", self.config.camera_id)
            return False

        if self._uvc_uid:
            ASSIGNED_LIBUVC_UIDS.discard(self._uvc_uid)
            self._uvc_uid = None

        try:
            devices = uvc.device_list()
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("列举 UVC 设备失败: %s", exc)
            return False

        used_uids = ASSIGNED_LIBUVC_UIDS.copy()
        target = self._select_uvc_device(devices, used_uids)
        if target is None:
            LOGGER.error(
                "未找到匹配的红外摄像头 (vendor=%s, product=%s, uid=%s, address=%s) 对应 %s",
                self.config.vendor_id,
                self.config.product_id,
                self.config.device_uid,
                self.config.device_address,
                self.config.camera_id,
            )
            return False

        try:
            self._uvc_capture = uvc.Capture(target["uid"])
            self.config.device_uid = target.get("uid")
            if self.config.device_address is None:
                self.config.device_address = target.get("device_address")
            self._apply_uvc_mode()
            self._uvc_uid = self.config.device_uid
            if self._uvc_uid:
                ASSIGNED_LIBUVC_UIDS.add(self._uvc_uid)
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("打开红外摄像头失败 %s: %s", self.config.camera_id, exc)
            self._uvc_capture = None
            return False

        self._running.set()
        self._thread = threading.Thread(target=self._capture_loop_libuvc, daemon=True)
        self._thread.start()
        LOGGER.info("Camera %s started (libuvc, uid=%s)", self.config.camera_id, self.config.device_uid)
        return True

    def _select_uvc_device(self, devices: list[dict], used_uids: set[str]) -> Optional[dict]:
        def matches(device: dict) -> bool:
            if self.config.device_uid and device.get("uid") != self.config.device_uid:
                return False
            if self.config.device_address is not None and device.get("device_address") != self.config.device_address:
                return False
            if self.config.vendor_id is not None and device.get("idVendor") != self.config.vendor_id:
                return False
            if self.config.product_id is not None and device.get("idProduct") != self.config.product_id:
                return False
            if self.config.serial_number is not None and device.get("serialNumber") != self.config.serial_number:
                return False
            return True

        # exact match
        for dev in devices:
            if matches(dev) and dev.get("uid") not in used_uids:
                return dev

        # fallback: try ignoring uid/address if not specified
        for dev in devices:
            if dev.get("uid") in used_uids:
                continue
            if self.config.vendor_id is None or dev.get("idVendor") == self.config.vendor_id:
                if self.config.product_id is None or dev.get("idProduct") == self.config.product_id:
                    return dev
        return None

    def _apply_uvc_mode(self) -> None:
        if self._uvc_capture is None:
            return
        capture = self._uvc_capture
        try:
            mode = capture.frame_mode
        except Exception as exc:  # noqa: BLE001
            LOGGER.debug("获取 UVC 模式失败: %s", exc)
            return

        width = int(self.config.frame_width or mode[0])
        height = int(self.config.frame_height or mode[1])
        fps = int(self.config.fps or mode[2])

        try:
            capture.frame_mode = (width, height, fps)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("设置 UVC 模式失败，使用默认值: %s", exc)

    def stop(self) -> None:
        if not self.is_running:
            return

        self._running.clear()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

        if self.capture is not None:
            self.capture.release()
            self.capture = None

        if self._uvc_capture is not None:
            try:
                self._uvc_capture.close()
            except Exception:  # noqa: BLE001
                LOGGER.debug("关闭 UVC 摄像头异常", exc_info=True)
            self._uvc_capture = None
        if self._uvc_uid:
            ASSIGNED_LIBUVC_UIDS.discard(self._uvc_uid)
            self._uvc_uid = None

        LOGGER.info("Camera %s stopped", self.config.camera_id)

    @property
    def is_running(self) -> bool:
        return self._running.is_set()

    def get_frame(self) -> Optional[np.ndarray]:
        with self._frame_lock:
            if self._latest_frame is None:
                return None
            return self._latest_frame.copy()

    def get_timestamp(self) -> float:
        with self._frame_lock:
            return self._latest_timestamp

    def _configure_capture(self) -> None:
        if self.capture is None:
            return

        self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, float(self.config.frame_width))
        self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, float(self.config.frame_height))
        self.capture.set(cv2.CAP_PROP_FPS, float(self.config.fps))

        if self.config.fourcc:
            fourcc_value = cv2.VideoWriter_fourcc(*self.config.fourcc)
            self.capture.set(cv2.CAP_PROP_FOURCC, fourcc_value)

    def _capture_loop_opencv(self) -> None:
        assert self.capture is not None
        backoff = 0.05

        while self._running.is_set():
            ret, frame = self.capture.read()
            if not ret or frame is None:
                LOGGER.warning("Failed to read frame from %s, retrying", self.config.camera_id)
                time.sleep(backoff)
                backoff = min(backoff * 2, 1.0)
                continue

            frame = self._apply_transform(frame, self.config.transform)
            with self._frame_lock:
                self._latest_frame = frame
                self._latest_timestamp = time.time()
            backoff = 0.05

    def _capture_loop_libuvc(self) -> None:
        try:
            import uvc
        except ImportError:  # pragma: no cover
            LOGGER.error("pyuvc 未安装")
            self._running.clear()
            return

        capture: Optional[uvc.Capture] = self._uvc_capture
        if capture is None:
            LOGGER.error("libuvc capture 未初始化")
            self._running.clear()
            return

        while self._running.is_set():
            try:
                frame = capture.get_frame(timeout=1.0)
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("读取 UVC 帧失败: %s", exc)
                time.sleep(0.05)
                continue

            if frame is None:
                time.sleep(0.05)
                continue

            np_frame: Optional[np.ndarray] = None
            if hasattr(frame, "bgr"):
                np_frame = frame.bgr
            elif hasattr(frame, "img"):
                np_frame = frame.img
            else:
                try:
                    np_frame = frame.asarray(np.uint8)  # type: ignore[attr-defined]
                except Exception:  # noqa: BLE001
                    LOGGER.debug("无法转换帧为 numpy", exc_info=True)
                    time.sleep(0.01)
                    continue

            if np_frame is None:
                time.sleep(0.01)
                continue

            if np_frame.ndim == 2:
                np_frame = cv2.cvtColor(np_frame, cv2.COLOR_GRAY2BGR)

            np_frame = self._apply_transform(np_frame, self.config.transform)
            with self._frame_lock:
                self._latest_frame = np_frame
                self._latest_timestamp = time.time()

    @staticmethod
    def _apply_transform(frame: np.ndarray, transform: FrameTransform) -> np.ndarray:
        if transform.rotate_code is not None:
            frame = cv2.rotate(frame, transform.rotate_code)

        if transform.flip_horizontal:
            frame = cv2.flip(frame, 1)

        if transform.flip_vertical:
            frame = cv2.flip(frame, 0)

        return frame


class CameraManager:
    """Orchestrates access to multiple camera streams."""

    def __init__(self, configs: Iterable[CameraConfig]) -> None:
        self._streams: Dict[str, CameraStream] = {cfg.camera_id: CameraStream(cfg) for cfg in configs}
        self._lock = threading.RLock()

    def available_cameras(self) -> Iterable[CameraConfig]:
        with self._lock:
            return [stream.config for stream in self._streams.values()]

    def get_config(self, camera_id: str) -> Optional[CameraConfig]:
        stream = self._streams.get(camera_id)
        if stream is None:
            return None
        return stream.config

    def is_running(self, camera_id: str) -> bool:
        stream = self._streams.get(camera_id)
        if stream is None:
            return False
        return stream.is_running

    def status_snapshot(self) -> Dict[str, dict]:
        with self._lock:
            return {
                camera_id: {
                    "config": stream.config,
                    "is_running": stream.is_running,
                    "timestamp": stream.get_timestamp(),
                }
                for camera_id, stream in self._streams.items()
            }

    def ensure_started(self, camera_id: str) -> bool:
        stream = self._streams.get(camera_id)
        if stream is None:
            LOGGER.error("Unknown camera id %s", camera_id)
            return False

        with self._lock:
            return stream.start()

    def stop(self, camera_id: str) -> None:
        stream = self._streams.get(camera_id)
        if stream is None:
            return

        with self._lock:
            stream.stop()

    def stop_all(self) -> None:
        with self._lock:
            for stream in self._streams.values():
                stream.stop()

    def get_frame(self, camera_id: str) -> Optional[np.ndarray]:
        stream = self._streams.get(camera_id)
        if stream is None:
            return None
        return stream.get_frame()

    def get_timestamp(self, camera_id: str) -> float:
        stream = self._streams.get(camera_id)
        if stream is None:
            return 0.0
        return stream.get_timestamp()


def build_default_camera_manager() -> CameraManager:
    transform_infrared = FrameTransform(rotate_code=cv2.ROTATE_90_CLOCKWISE)
    transform_world = FrameTransform(flip_horizontal=True, flip_vertical=True)

    configs = _discover_camera_configs(transform_infrared, transform_world)
    return CameraManager(configs=configs)


def _discover_camera_configs(
    transform_infrared: FrameTransform,
    transform_world: FrameTransform,
) -> list[CameraConfig]:
    try:
        import uvc
    except ImportError:
        LOGGER.warning("pyuvc 未安装，将回退到 OpenCV 设备索引")
        return _fallback_opencv_configs(transform_infrared, transform_world)

    try:
        devices = uvc.device_list()
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("枚举 UVC 设备失败，将回退到 OpenCV，错误：%s", exc)
        return _fallback_opencv_configs(transform_infrared, transform_world)

    if not devices:
        LOGGER.warning("未发现任何 UVC 设备，将回退到 OpenCV")
        return _fallback_opencv_configs(transform_infrared, transform_world)

    def by_name(keyword: str) -> list[dict]:
        kw_lower = keyword.lower()
        return [dev for dev in devices if kw_lower in (dev.get("name") or "").lower()]

    # 优先根据名称识别红外与彩色设备
    pupils = by_name("pupil cam2")
    world_candidates = by_name("xgimi") or by_name("camera") or []

    if len(pupils) < 2:
        LOGGER.warning("找到的 Pupil Cam2 设备数量不足 2（仅 %s 个），回退到 OpenCV", len(pupils))
        return _fallback_opencv_configs(transform_infrared, transform_world)

    pupils_sorted = sorted(pupils, key=lambda d: d.get("device_address", 0))
    world_device = (
        sorted(world_candidates, key=lambda d: d.get("device_address", 0))[0]
        if world_candidates
        else None
    )

    configs: list[CameraConfig] = []

    for idx, dev in enumerate(pupils_sorted[:2]):
        camera_id = f"eye{idx}"
        configs.append(
            CameraConfig(
                camera_id=camera_id,
                device_index=idx,
                display_name="左眼红外" if idx == 0 else "右眼红外",
                frame_width=400,
                frame_height=400,
                fps=60.0,
                fourcc="MJPG",
                transform=transform_infrared,
                access_method="libuvc",
                vendor_id=dev.get("idVendor"),
                product_id=dev.get("idProduct"),
                device_uid=dev.get("uid"),
                device_address=dev.get("device_address"),
            )
        )

    if world_device:
        configs.append(
            CameraConfig(
                camera_id="world",
                device_index=2,
                display_name=world_device.get("name") or "外部彩色",
                frame_width=640,
                frame_height=480,
                fps=30.0,
                fourcc="MJPG",
                transform=transform_world,
                access_method="libuvc",
                vendor_id=world_device.get("idVendor"),
                product_id=world_device.get("idProduct"),
                device_uid=world_device.get("uid"),
                device_address=world_device.get("device_address"),
            )
        )
    else:
        LOGGER.warning("未发现彩色摄像头，世界视角将回退到 OpenCV index 2")
        configs.append(
            CameraConfig(
                camera_id="world",
                device_index=2,
                display_name="外部彩色",
                frame_width=640,
                frame_height=480,
                fps=30.0,
                fourcc="MJPG",
                transform=transform_world,
                access_method="opencv",
            )
        )

    return configs


def _fallback_opencv_configs(
    transform_infrared: FrameTransform,
    transform_world: FrameTransform,
) -> list[CameraConfig]:
    return [
        CameraConfig(
            camera_id="eye0",
            device_index=0,
            display_name="左眼红外",
            frame_width=400,
            frame_height=400,
            fourcc="MJPG",
            transform=transform_infrared,
            access_method="opencv",
        ),
        CameraConfig(
            camera_id="eye1",
            device_index=1,
            display_name="右眼红外",
            frame_width=400,
            frame_height=400,
            fourcc="MJPG",
            transform=transform_infrared,
            access_method="opencv",
        ),
        CameraConfig(
            camera_id="world",
            device_index=2,
            display_name="外部彩色",
            frame_width=640,
            frame_height=480,
            fourcc="MJPG",
            transform=transform_world,
            access_method="opencv",
        ),
    ]

