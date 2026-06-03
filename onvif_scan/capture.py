"""Stream probing + frame capture + quality scoring via ffmpeg/ffprobe/OpenCV."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, urlunparse

# Must be set before OpenCV's ffmpeg backend initializes:
#  - rtsp_transport;tcp  -> avoids UDP packet reordering/loss ("bad cseq" spam)
#  - loglevel -8 (quiet) -> silence libav decode/RTP warnings on stderr
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")
os.environ.setdefault("OPENCV_FFMPEG_LOGLEVEL", "-8")

from .models import Stream


def _sanitize_rtsp(url: str) -> str:
    """Strip credentials from an rtsp URL so they never get drawn onto a screenshot."""
    try:
        p = urlparse(url)
        netloc = p.netloc.split("@")[-1]
        return urlunparse(p._replace(netloc=netloc))
    except Exception:
        return url


def ffmpeg_available() -> bool:
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def _safe_name(s: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in s)


def ffprobe_metadata(rtsp_url: str, timeout: int = 15) -> dict:
    """Pull codec/resolution/advertised-fps from the live stream via ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-rtsp_transport", "tcp",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,codec_name,avg_frame_rate,bit_rate",
        "-of", "json",
        rtsp_url,
    ]
    try:
        out = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        data = json.loads(out.stdout or "{}")
        streams = data.get("streams", [])
        return streams[0] if streams else {}
    except Exception:
        return {}


def _parse_fps(rate: str) -> float:
    try:
        if "/" in rate:
            n, d = rate.split("/")
            d = float(d)
            return round(float(n) / d, 2) if d else 0.0
        return float(rate)
    except Exception:
        return 0.0


def capture_and_measure(
    stream: Stream,
    shots_dir: Path,
    ip: str,
    frames: int = 100,
    shots: int = 2,
    timeout: int = 30,
) -> Stream:
    """Probe metadata, grab N frames to measure real FPS, save screenshots, grade quality."""
    if not stream.rtsp_url:
        stream.error = stream.error or "no rtsp url"
        return stream

    # 1) metadata from ffprobe
    meta = ffprobe_metadata(stream.rtsp_url, timeout=timeout)
    if meta:
        w = int(meta.get("width", 0) or 0)
        h = int(meta.get("height", 0) or 0)
        if w and h:
            stream.width, stream.height = w, h
            stream.resolution = f"{w}x{h}"
        stream.codec = stream.codec or (meta.get("codec_name", "") or "")
        adv = _parse_fps(meta.get("avg_frame_rate", "0"))
        if adv:
            stream.fps_advertised = stream.fps_advertised or adv
        br = meta.get("bit_rate")
        if br and not stream.bitrate_kbps:
            try:
                stream.bitrate_kbps = int(int(br) / 1000)
            except Exception:
                pass
    elif not stream.error:
        stream.error = "unreachable (ffprobe failed)"
        return stream

    # 2) capture frames with OpenCV, measure real FPS
    try:
        import cv2
    except Exception as e:
        stream.error = f"opencv unavailable: {e}"
        return stream

    cap = cv2.VideoCapture(stream.rtsp_url, cv2.CAP_FFMPEG)
    if not cap.isOpened():
        stream.error = "could not open stream"
        cap.release()
        return stream

    grabbed = 0
    sample_frames = []  # raw frames held in memory; written after metrics are known
    start = time.monotonic()
    deadline = start + timeout
    save_at = set()
    if frames > 0 and shots > 0:
        step = max(1, frames // (shots + 1))
        save_at = {step * (i + 1) for i in range(shots)}

    while grabbed < frames and time.monotonic() < deadline:
        ok, frame = cap.read()
        if not ok:
            break
        grabbed += 1
        if grabbed in save_at and len(sample_frames) < shots:
            sample_frames.append(frame.copy())
    elapsed = time.monotonic() - start
    cap.release()

    stream.frames_captured = grabbed
    if grabbed > 1 and elapsed > 0:
        stream.fps_measured = round(grabbed / elapsed, 2)
    if grabbed == 0:
        stream.error = "no frames received"
        return stream

    # 3) score quality on a raw frame, then annotate + save screenshots with the
    #    now-known metrics (measured FPS isn't available until after the loop).
    if sample_frames:
        _score_quality(stream, sample_frames[0])
        for i, frame in enumerate(sample_frames):
            name = f"{ip}_{_safe_name(stream.profile)}_{i + 1}.jpg"
            try:
                annotated = _annotate(frame, stream, ip)
                cv2.imwrite(str(shots_dir / name), annotated)
                stream.screenshots.append(f"shots/{name}")
            except Exception:
                pass
    return stream


def _annotate(frame, stream: Stream, ip: str):
    """Burn key metrics onto the screenshot for at-a-glance review in the report/email."""
    import cv2

    img = frame.copy()
    h, w = img.shape[:2]
    lines = [
        f"{ip}   {stream.profile}",
        f"Resolution: {stream.resolution or '-'}    Codec: {stream.codec or '-'}",
        f"FPS advertised: {stream.fps_advertised or '-'}    measured: {stream.fps_measured or '-'}",
        f"Bitrate: {stream.bitrate_kbps or '-'} kbps    Quality: {stream.quality_score}/100",
        f"RTSP: {_sanitize_rtsp(stream.rtsp_url)}",
    ]
    scale = min(2.0, max(0.5, w / 1280.0))
    font = cv2.FONT_HERSHEY_SIMPLEX
    fs = 0.55 * scale
    thick = max(1, int(round(scale)))
    pad = int(10 * scale)
    line_h = int(30 * scale)
    box_h = pad * 2 + line_h * len(lines)

    overlay = img.copy()
    cv2.rectangle(overlay, (0, 0), (w, box_h), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.55, img, 0.45, 0, img)
    y = pad + int(line_h * 0.75)
    for ln in lines:
        cv2.putText(img, ln, (pad, y), font, fs, (255, 255, 255), thick, cv2.LINE_AA)
        y += line_h
    return img


def _score_quality(stream: Stream, frame) -> None:
    import cv2
    import numpy as np

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    # sharpness: variance of Laplacian (normalized to ~0..1 around a 500 reference)
    lap_var = cv2.Laplacian(gray, cv2.CV_64F).var()
    stream.sharpness = round(min(1.0, lap_var / 500.0), 3)

    # exposure from mean brightness
    mean = float(np.mean(gray))
    if mean < 35:
        stream.exposure = "dark"
    elif mean > 220:
        stream.exposure = "blown"
    else:
        stream.exposure = "ok"

    # composite 0..100
    score = 0.0
    # resolution tier (35 pts)
    px = stream.width * stream.height
    if px >= 1920 * 1080:
        score += 35
    elif px >= 1280 * 720:
        score += 28
    elif px >= 640 * 480:
        score += 18
    else:
        score += 8
    # fps health (30 pts): measured vs advertised
    if stream.fps_advertised > 0:
        ratio = min(1.0, stream.fps_measured / stream.fps_advertised)
        score += 30 * ratio
    elif stream.fps_measured >= 15:
        score += 24
    elif stream.fps_measured > 0:
        score += 15
    # sharpness (20 pts)
    score += 20 * stream.sharpness
    # exposure (15 pts)
    score += 15 if stream.exposure == "ok" else 4

    stream.quality_score = int(round(min(100.0, score)))
