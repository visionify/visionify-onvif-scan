"""Thin wrapper over onvif-zeep to pull device info + stream URIs."""
from __future__ import annotations

from typing import List, Optional, Tuple
from urllib.parse import urlparse, urlunparse

from .models import Device, Stream


COMMON_ONVIF_PORTS = [80, 8000, 8080, 2020, 8899, 8081, 8181, 88]


def _candidate_ports(device: Device) -> List[int]:
    """Ordered, de-duplicated list of ports to try ONVIF on."""
    ports: List[int] = []
    if device.onvif_url:
        p = urlparse(device.onvif_url).port
        if p:
            ports.append(p)
    for p in device.open_ports:
        if p in COMMON_ONVIF_PORTS and p not in ports:
            ports.append(p)
    for p in (80, 8000):
        if p not in ports:
            ports.append(p)
    return ports


def _inject_creds(rtsp_url: str, user: str, password: str) -> str:
    """Put credentials into an rtsp:// URL so ffmpeg can authenticate."""
    if not user:
        return rtsp_url
    p = urlparse(rtsp_url)
    netloc = p.netloc.split("@")[-1]  # strip any existing creds
    netloc = f"{user}:{password}@{netloc}"
    return urlunparse(p._replace(netloc=netloc))


def enumerate_streams(
    device: Device, user: str, password: str, timeout: int = 15
) -> Tuple[bool, List[Stream], Optional[str]]:
    """
    Returns (auth_ok, streams, error). Tries ONVIF first; if the device exposes no
    ONVIF service, returns auth_ok=False so the caller can fall back / move on.
    """
    try:
        from onvif import ONVIFCamera
    except Exception as e:  # pragma: no cover
        return False, [], f"onvif-zeep unavailable: {e}"

    # Try each candidate port until one connects. Auth failures stop immediately
    # (right port, wrong creds); connection/other errors fall through to the next port.
    last_err = "no onvif port responded"
    for port in _candidate_ports(device):
        ok, streams, err = _enumerate_on_port(ONVIFCamera, device, port, user, password)
        if ok:
            device.onvif_url = f"http://{device.ip}:{port}/onvif/device_service"
            return True, streams, None
        if err == "auth failed":
            return False, [], "auth failed"
        last_err = err
    return False, [], last_err


def _enumerate_on_port(ONVIFCamera, device, port, user, password):
    try:
        cam = ONVIFCamera(device.ip, port, user, password)
        info = cam.devicemgmt.GetDeviceInformation()
        device.manufacturer = getattr(info, "Manufacturer", "") or ""
        device.model = getattr(info, "Model", "") or ""
        device.firmware = getattr(info, "FirmwareVersion", "") or ""
        device.serial = getattr(info, "SerialNumber", "") or ""

        media = cam.create_media_service()
        profiles = media.GetProfiles()
        streams: List[Stream] = []
        for prof in profiles:
            s = Stream(profile=getattr(prof, "Name", "") or prof.token)
            # advertised resolution / fps from the encoder config when present
            try:
                enc = prof.VideoEncoderConfiguration
                if enc is not None:
                    res = enc.Resolution
                    s.width = int(getattr(res, "Width", 0) or 0)
                    s.height = int(getattr(res, "Height", 0) or 0)
                    if s.width and s.height:
                        s.resolution = f"{s.width}x{s.height}"
                    s.codec = (getattr(enc, "Encoding", "") or "").lower()
                    rl = getattr(enc, "RateControl", None)
                    if rl is not None:
                        s.fps_advertised = float(getattr(rl, "FrameRateLimit", 0) or 0)
                        s.bitrate_kbps = int(getattr(rl, "BitrateLimit", 0) or 0)
            except Exception:
                pass
            # stream URI
            try:
                req = media.create_type("GetStreamUri")
                req.ProfileToken = prof.token
                req.StreamSetup = {
                    "Stream": "RTP-Unicast",
                    "Transport": {"Protocol": "RTSP"},
                }
                uri = media.GetStreamUri(req)
                s.rtsp_url = _inject_creds(uri.Uri, user, password)
            except Exception as e:
                s.error = f"GetStreamUri failed: {e}"
            streams.append(s)
        return True, streams, None
    except Exception as e:
        msg = str(e)
        low = msg.lower()
        if "auth" in low or "401" in low or "not authorized" in low or "unauthorized" in low:
            return False, [], "auth failed"
        return False, [], f"onvif error: {msg[:200]}"
