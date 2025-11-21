from __future__ import annotations

import os
import platform
import re
import shutil
import socket
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence


@dataclass(slots=True)
class DeviceStatus:
    hostname: str
    ip_address: str
    os_release: str
    battery_percentage: str
    hardware_items: list[tuple[str, str]] = field(default_factory=list)
    gps_items: list[tuple[str, str]] = field(default_factory=list)
    gps_raw_sentences: list[str] = field(default_factory=list)


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
    hardware_items = _collect_hardinfo_summary()
    gps_items, gps_raw = _collect_gps_info()
    return DeviceStatus(
        hostname=_get_hostname(),
        ip_address=_get_ip_address(),
        os_release=platform.platform(),
        battery_percentage=_get_battery_percentage(),
        hardware_items=hardware_items,
        gps_items=gps_items,
        gps_raw_sentences=gps_raw,
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


HARDINFO_DEFAULT_SECTIONS: tuple[str, ...] = (
    "devices.cpu",
    "devices.memory",
    "devices.storage",
    "devices.network",
    "devices.battery",
)

HARDINFO_PRIORITY_KEYWORDS: tuple[str, ...] = (
    "processor",
    "cpu",
    "model",
    "board",
    "device",
    "memory",
    "ram",
    "storage",
    "flash",
    "disk",
    "network",
    "ethernet",
    "wifi",
    "battery",
)


def _collect_hardinfo_summary() -> list[tuple[str, str]]:
    binary = shutil.which("hardinfo")
    if not binary:
        return []

    sections_env = os.getenv("HARDINFO_SECTIONS")
    if sections_env:
        sections = [section.strip() for section in sections_env.split(",") if section.strip()]
    else:
        sections = list(HARDINFO_DEFAULT_SECTIONS)

    if not sections:
        sections = ["devices.cpu"]

    cmd = [binary, "-r", *sections]
    try:
        output = subprocess.check_output(
            cmd,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=float(os.getenv("HARDINFO_TIMEOUT", "4.0")),
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return []

    limit = max(int(os.getenv("HARDINFO_SUMMARY_LIMIT", "12")), 1)
    summary: list[tuple[str, str]] = []
    seen: set[str] = set()

    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("="):
            continue
        if ":" not in line:
            continue

        key, value = [part.strip(" \t:") for part in line.split(":", 1)]
        if not key or not value:
            continue

        normalized_key = re.sub(r"\s+", " ", key)
        lower_key = normalized_key.lower()
        if lower_key in seen:
            continue

        is_priority = any(keyword in lower_key for keyword in HARDINFO_PRIORITY_KEYWORDS)
        if not is_priority and len(summary) >= limit:
            continue

        summary.append((normalized_key, value.strip()))
        seen.add(lower_key)

        if len(summary) >= limit and not os.getenv("HARDINFO_ALLOW_OVERFLOW"):
            break

    return summary[:limit]


def _collect_gps_info() -> tuple[list[tuple[str, str]], list[str]]:
    sample_path = os.getenv("GPS_SAMPLE_FILE")
    if sample_path:
        try:
            nmea_lines = [
                line.strip()
                for line in Path(sample_path).read_text().splitlines()
                if line.strip()
            ]
        except OSError:
            nmea_lines = []
    else:
        microcom_path = shutil.which("microcom")
        if not microcom_path:
            return ([], [])

        device_path = os.getenv("GPS_SERIAL_DEVICE", "/dev/ttyUSB0")
        skip_check = os.getenv("GPS_SKIP_DEVICE_CHECK") == "1"
        if not skip_check and not Path(device_path).exists():
            return ([], [])

        baud = os.getenv("GPS_SERIAL_BAUD", "9600")

        try:
            timeout = float(os.getenv("GPS_READ_TIMEOUT", "3.0"))
        except ValueError:
            timeout = 3.0

        timeout_ms = max(int(timeout * 1000), 500)
        cmd = [microcom_path, "-s", str(baud), "-t", str(timeout_ms), device_path]

        try:
            completed = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout + 1.5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ([], [])

        nmea_lines = [
            line.strip()
            for line in completed.stdout.splitlines()
            if line.strip()
        ]

    if not nmea_lines:
        return ([], [])

    sentences = [line for line in nmea_lines if line.startswith("$")]
    parsed = _parse_nmea_sentences(sentences)
    items = _gps_dict_to_items(parsed)

    if items:
        if sample_path:
            items.append(("数据源", f"样本文件：{Path(sample_path).name}"))
        else:
            device_label = os.getenv("GPS_SERIAL_DEVICE", "/dev/ttyS0")
            items.append(("串口", device_label))

    raw_preview = sentences[-3:] if sentences else nmea_lines[-3:]
    return (items, raw_preview)


def _parse_nmea_sentences(lines: Sequence[str]) -> dict[str, Any]:
    data: dict[str, Any] = {}
    gga_data: dict[str, Any] = {}
    rmc_data: dict[str, Any] = {}

    for line in lines:
        sentence = line.split("*", 1)[0]
        parts = sentence.split(",")
        if not parts or not parts[0]:
            continue

        talker = parts[0].upper()
        if talker.endswith("RMC"):
            parsed = _parse_rmc(parts)
            if parsed:
                rmc_data = parsed
        elif talker.endswith("GGA"):
            parsed = _parse_gga(parts)
            if parsed:
                gga_data = parsed

    data.update(gga_data)
    data.update(rmc_data)
    return data


def _parse_rmc(parts: Sequence[str]) -> dict[str, Any]:
    if len(parts) < 10:
        return {}

    status = parts[2].upper() if len(parts) > 2 else ""
    if status != "A":
        return {}

    lat = _nmea_to_decimal(parts[3], parts[4] if len(parts) > 4 else "")
    lon = _nmea_to_decimal(parts[5], parts[6] if len(parts) > 6 else "")
    speed_knots = _safe_float(parts[7]) if len(parts) > 7 else None
    track_angle = _safe_float(parts[8]) if len(parts) > 8 else None
    timestamp = _parse_nmea_datetime(parts[1], parts[9]) if len(parts) > 9 else None

    data: dict[str, Any] = {}
    if lat is not None:
        data["latitude"] = lat
    if lon is not None:
        data["longitude"] = lon
    if speed_knots is not None:
        data["speed_kmh"] = speed_knots * 1.852
    if track_angle is not None:
        data["heading_deg"] = track_angle
    if timestamp:
        data["timestamp_utc"] = timestamp
    return data


NMEA_FIX_QUALITY = {
    0: "无效 (0)",
    1: "GPS (1)",
    2: "差分GPS (2)",
    4: "RTK 固定 (4)",
    5: "RTK 浮动 (5)",
    6: "推算 (6)",
}


def _parse_gga(parts: Sequence[str]) -> dict[str, Any]:
    if len(parts) < 10:
        return {}

    lat = _nmea_to_decimal(parts[2], parts[3] if len(parts) > 3 else "")
    lon = _nmea_to_decimal(parts[4], parts[5] if len(parts) > 5 else "")
    fix_quality_code = _safe_int(parts[6]) if len(parts) > 6 else None
    satellites = _safe_int(parts[7]) if len(parts) > 7 else None
    hdop = _safe_float(parts[8]) if len(parts) > 8 else None
    altitude = _safe_float(parts[9]) if len(parts) > 9 else None

    data: dict[str, Any] = {}
    if lat is not None:
        data["latitude"] = lat
    if lon is not None:
        data["longitude"] = lon
    if fix_quality_code is not None:
        data["fix_quality"] = NMEA_FIX_QUALITY.get(fix_quality_code, f"未知 ({fix_quality_code})")
    if satellites is not None:
        data["satellites"] = satellites
    if hdop is not None:
        data["hdop"] = hdop
    if altitude is not None:
        data["altitude_m"] = altitude
    return data


def _nmea_to_decimal(value: str, direction: str) -> Optional[float]:
    value = value.strip()
    direction = direction.strip().upper()
    if not value or not direction:
        return None

    try:
        if direction in {"N", "S"}:
            degrees = int(value[:2])
            minutes = float(value[2:])
        elif direction in {"E", "W"}:
            degrees = int(value[:3])
            minutes = float(value[3:])
        else:
            return None
    except (ValueError, IndexError):
        return None

    decimal = degrees + minutes / 60.0
    if direction in {"S", "W"}:
        decimal *= -1
    return decimal


def _parse_nmea_datetime(time_str: str, date_str: str) -> Optional[str]:
    time_str = time_str.strip()
    date_str = date_str.strip()
    if len(time_str) < 6 or len(date_str) != 6:
        return None

    try:
        hour = int(time_str[0:2])
        minute = int(time_str[2:4])
        second = int(time_str[4:6])
        microsecond = 0
        if "." in time_str:
            fraction = time_str.split(".", 1)[1]
            microsecond = int(float(f"0.{fraction}") * 1_000_000)

        day = int(date_str[0:2])
        month = int(date_str[2:4])
        year = int(date_str[4:6]) + 2000

        dt = datetime(year, month, day, hour, minute, second, microsecond, tzinfo=timezone.utc)
        return dt.isoformat()
    except (ValueError, IndexError):
        return None


def _safe_float(value: str) -> Optional[float]:
    try:
        return float(value.strip())
    except (ValueError, AttributeError):
        return None


def _safe_int(value: str) -> Optional[int]:
    try:
        return int(value.strip())
    except (ValueError, AttributeError):
        return None


def _gps_dict_to_items(data: dict[str, Any]) -> list[tuple[str, str]]:
    if not data:
        return []

    items: list[tuple[str, str]] = []
    mappings: list[tuple[str, str, Optional[str]]] = [
        ("timestamp_utc", "UTC 时间", None),
        ("latitude", "纬度", "{:.6f}°"),
        ("longitude", "经度", "{:.6f}°"),
        ("altitude_m", "海拔 (m)", "{:.1f}"),
        ("speed_kmh", "速度 (km/h)", "{:.1f}"),
        ("heading_deg", "航向 (°)", "{:.1f}"),
        ("satellites", "卫星数量", None),
        ("hdop", "HDOP", "{:.1f}"),
        ("fix_quality", "定位质量", None),
    ]

    for key, label, fmt in mappings:
        if key not in data or data[key] is None:
            continue
        value = data[key]
        if fmt and isinstance(value, (int, float)):
            items.append((label, fmt.format(value)))
        else:
            items.append((label, str(value)))

    return items

