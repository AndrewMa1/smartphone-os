import sys
import time
from typing import List, Tuple

import cv2
import numpy as np
import uvc


def select_pupil_devices() -> List[dict]:
    devices = uvc.device_list()
    pupils = [dev for dev in devices if "pupil cam2" in (dev.get("name") or "").lower()]
    if len(pupils) < 2:
        raise RuntimeError(f"Expected at least 2 Pupil Cam2 devices, found {len(pupils)}")
    # sort by device address for deterministic order
    return sorted(pupils[:2], key=lambda dev: dev.get("device_address", 0))


def show_frame(window_name: str, frame) -> None:
    if hasattr(frame, "bgr") and frame.bgr is not None:
        img = frame.bgr
    elif hasattr(frame, "img") and frame.img is not None:
        img = frame.img
    else:
        img = frame.asarray(np.uint8)  # type: ignore[attr-defined]

    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)

    cv2.imshow(window_name, img)


def main() -> None:
    eye_devices = select_pupil_devices()
    captures: List[Tuple[dict, uvc.Capture]] = []
    try:
        for idx, dev in enumerate(eye_devices):
            uid = dev["uid"]
            cap = uvc.Capture(uid)
            captures.append((dev, cap))
            print(f"[open] {dev['name']} UID={uid} address={dev.get('device_address')}")
            cv2.namedWindow(f"Eye {idx}", cv2.WINDOW_NORMAL)

        for idx in range(100):
            for window_index, (dev, cap) in enumerate(captures):
                frame = cap.get_frame()
                print(
                    f"[{idx:03}] {dev['name']} addr={dev.get('device_address')} "
                    f"resolution={frame.width}x{frame.height} timestamp={frame.timestamp}"
                )
                show_frame(f"Eye {window_index}", frame)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                print("Quit requested by user")
                return
            time.sleep(0.01)
    finally:
        for dev, cap in captures:
            try:
                cap.close()
            except Exception:
                pass
        cv2.destroyAllWindows()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)