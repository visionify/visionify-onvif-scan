"""Simple JSON-backed state for a scan run."""
from __future__ import annotations

import json
from pathlib import Path

from .models import ScanResult, Device


def workdir(path: str | None = None) -> Path:
    d = Path(path) if path else Path.cwd() / "onvif-scan"
    d.mkdir(parents=True, exist_ok=True)
    (d / "shots").mkdir(exist_ok=True)
    return d


def save(result: ScanResult, wd: Path) -> Path:
    out = wd / "results.json"
    out.write_text(json.dumps(result.to_dict(), indent=2))
    # human-readable device list
    lines = [f"{d.ip}\t{d.manufacturer}\t{d.model}\t{d.onvif_url}" for d in result.devices]
    (wd / "devices.txt").write_text("\n".join(lines) + "\n")
    return out


def load(wd: Path) -> ScanResult:
    p = wd / "results.json"
    if not p.exists():
        raise FileNotFoundError(f"No results.json in {wd}. Run `onvif-scan search` first.")
    return ScanResult.from_dict(json.loads(p.read_text()))
