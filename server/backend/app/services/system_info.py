from __future__ import annotations

import platform
import shutil
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(slots=True)
class DeviceStatus:
    hostname: str
    ip_address: str
    os_release: str
    battery_percentage: str


def _read_sysfs_battery() -> Optional[str]:
    base = Path("/sys/class/power_supply")
    if not base.exists():
        return None

    for entry in base.iterdir():
        try:
            power_type = (entry / "type").read_text().strip().lower()
        except OSError:
            continue

        if power_type not in {"battery", "ups"}:
            continue

        capacity_file = entry / "capacity"
        if capacity_file.exists():
            value = _read_int(capacity_file)
            if value is not None:
                return f"{value}%"

        # Some boards expose charge/energy information instead of capacity
        current_file = _first_existing(entry, ["charge_now", "energy_now"])
        full_file = _first_existing(entry, ["charge_full", "energy_full"])
        if current_file and full_file:
            current = _read_int(current_file)
            full = _read_int(full_file)
            if current is not None and full and full > 0:
                percentage = int((current / full) * 100)
                percentage = max(0, min(percentage, 100))
                return f"{percentage}%"

        voltage_file = entry / "capacity_level"
        if voltage_file.exists():
            try:
                level = voltage_file.read_text().strip()
                if level:
                    return level
            except OSError:
                continue
    return None


def _read_pmset_battery() -> Optional[str]:
    try:
        output = subprocess.check_output(["pmset", "-g", "batt"], text=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None

    for line in output.splitlines():
        if "%" in line:
            percent_part = line.split("%")[0].split()[-1]
            try:
                value = int(percent_part)
                if 0 <= value <= 100:
                    return f"{value}%"
            except ValueError:
                continue
    return None


def _get_ip_address() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return "未知"


def _get_hostname() -> str:
    try:
        return socket.gethostname()
    except OSError:
        return "未知"


def _get_battery_percentage() -> str:
    for getter in (_read_sysfs_battery, _read_pmset_battery):
        value = getter()
        if value:
            return value

    upower_value = _read_upower_battery()
    if upower_value:
        return upower_value

    return "未知"


def get_device_status() -> DeviceStatus:
    return DeviceStatus(
        hostname=_get_hostname(),
        ip_address=_get_ip_address(),
        os_release=platform.platform(),
        battery_percentage=_get_battery_percentage(),
    )


def _read_int(path: Path) -> Optional[int]:
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def _first_existing(base: Path, names: list[str]) -> Optional[Path]:
    for name in names:
        candidate = base / name
        if candidate.exists():
            return candidate
    return None


def _read_upower_battery() -> Optional[str]:
    upower = shutil.which("upower")
    if not upower:
        return None

    try:
        devices_output = subprocess.check_output([upower, "-e"], text=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None

    battery_paths = [
        line.strip()
        for line in devices_output.splitlines()
        if "battery" in line.lower()
    ]
    if not battery_paths:
        return None

    for device_path in battery_paths:
        try:
            details = subprocess.check_output([upower, "-i", device_path], text=True)
        except subprocess.CalledProcessError:
            continue

        for line in details.splitlines():
            line = line.strip().lower()
            if line.startswith("percentage:"):
                percent_str = line.split(":", 1)[1].strip().strip("% ")
                try:
                    value = int(percent_str)
                    if 0 <= value <= 100:
                        return f"{value}%"
                except ValueError:
                    continue
    return None

