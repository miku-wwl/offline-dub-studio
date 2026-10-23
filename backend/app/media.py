from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Sequence

from .config import settings


class MediaError(RuntimeError):
    pass


def run(args: Sequence[str], *, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    """Run a fixed executable with an argument vector; never invoke a shell."""
    try:
        result = subprocess.run(list(args), check=False, capture_output=True, text=True,
                               timeout=timeout, encoding="utf-8", errors="replace")
    except FileNotFoundError as exc:
        raise MediaError(f"Required program is missing: {args[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise MediaError(f"Media command exceeded its time limit: {args[0]}") from exc
    if result.returncode:
        detail = (result.stderr or result.stdout)[-1800:]
        raise MediaError(f"Media command failed ({result.returncode}): {detail}")
    return result


def probe_media(path: Path) -> dict:
    result = run([settings.ffprobe, "-v", "error", "-show_streams", "-show_format",
                  "-of", "json", str(path)], timeout=120)
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise MediaError("FFprobe returned invalid media metadata") from exc
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if not video:
        raise MediaError("The selected file does not contain a video stream")
    duration = float(video.get("duration") or data.get("format", {}).get("duration") or 0)
    if duration <= 0 or duration > settings.max_duration_seconds:
        raise MediaError(f"Video duration is outside the supported limit (max {settings.max_duration_seconds}s)")
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    subtitle_streams = [s for s in streams if s.get("codec_type") == "subtitle"]
    return {
        "duration": duration,
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "fps": video.get("avg_frame_rate") or video.get("r_frame_rate") or "0/1",
        "video_codec": video.get("codec_name"),
        "has_audio": bool(audio),
        "audio_codec": audio.get("codec_name") if audio else None,
        "audio_streams": [s for s in streams if s.get("codec_type") == "audio"],
        "subtitle_streams": subtitle_streams,
        "format": data.get("format", {}),
        "streams": streams,
    }


def require_tools() -> dict[str, bool]:
    return {name: shutil.which(getattr(settings, name)) is not None
            for name in ("ffmpeg", "ffprobe")}
