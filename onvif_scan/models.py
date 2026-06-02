"""Data models persisted as JSON in the working directory."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import List, Optional


@dataclass
class Stream:
    profile: str = ""
    rtsp_url: str = ""
    resolution: str = ""          # "2560x1440"
    width: int = 0
    height: int = 0
    codec: str = ""               # "h264" / "h265" / "mjpeg"
    fps_advertised: float = 0.0
    fps_measured: float = 0.0
    bitrate_kbps: int = 0
    screenshots: List[str] = field(default_factory=list)
    quality_score: int = 0
    sharpness: float = 0.0
    exposure: str = ""            # "ok" / "dark" / "blown"
    frames_captured: int = 0
    error: Optional[str] = None


@dataclass
class Device:
    ip: str = ""
    onvif_url: str = ""
    manufacturer: str = ""
    model: str = ""
    firmware: str = ""
    serial: str = ""
    open_ports: List[int] = field(default_factory=list)
    reachable: bool = False
    auth: str = "unknown"         # "ok" / "failed" / "unknown"
    streams: List[Stream] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def status(self) -> str:
        # Working streams are authoritative: if we captured usable streams the device
        # is usable, even if some non-fatal device-level error was recorded.
        usable = [s for s in self.streams if s.error is None and s.frames_captured > 0]
        good = [s for s in usable if s.quality_score >= 70]
        if good:
            return "good"
        if usable:
            return "usable"
        return "failed"


@dataclass
class ScanResult:
    client: str = ""
    scanned_at: str = ""
    devices: List[Device] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ScanResult":
        devices = []
        for dd in d.get("devices", []):
            streams = [Stream(**s) for s in dd.pop("streams", [])]
            dev = Device(**dd)
            dev.streams = streams
            devices.append(dev)
        return cls(
            client=d.get("client", ""),
            scanned_at=d.get("scanned_at", ""),
            devices=devices,
        )
