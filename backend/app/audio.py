from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import soundfile as sf


SAMPLE_RATE = 24000


def compose_timeline(segments: list[dict], voice_files: dict[str, Path], duration: float,
                     output: Path) -> dict:
    """Place synthesized audio on the source timeline and keep overlong dialogue audible."""
    total = max(1, math.ceil(duration * SAMPLE_RATE))
    mix = np.zeros((total, 2), dtype=np.float32)
    warnings: list[str] = []
    active_until = 0
    overlaps = 0
    for seg in sorted(segments, key=lambda s: float(s["start"])):
        path = voice_files.get(seg["id"])
        if path is None or not path.exists():
            continue
        samples, rate = sf.read(path, dtype="float32", always_2d=True)
        if rate != SAMPLE_RATE:
            raise ValueError(f"Unexpected TTS sample rate in {path}: {rate}")
        if len(samples.shape) and samples.shape[1] == 1:
            samples = np.repeat(samples, 2, axis=1)
        target_len = max(1, int((float(seg["end"]) - float(seg["start"])) * SAMPLE_RATE))
        if len(samples) > target_len * 1.02:
            warnings.append(f"Segment {seg['id']} remains longer than its original dialogue slot; speech was preserved without extreme acceleration and may overlap following dialogue.")
        offset = max(0, int(float(seg["start"]) * SAMPLE_RATE))
        if offset < active_until:
            overlaps += 1
        active_until = max(active_until, offset+len(samples))
        end = min(total, offset + len(samples))
        if offset+len(samples)>total:
            warnings.append(f"Segment {seg['id']} extends beyond the source video duration; only the final video-length tail can be exported.")
        if end > offset:
            mix[offset:end] += samples[:end-offset, :2]
    peak = float(np.max(np.abs(mix))) if mix.size else 0.0
    if peak > 0.93:
        mix *= 0.93 / peak
    sf.write(output, mix, SAMPLE_RATE, subtype="PCM_16")
    if overlaps:
        warnings.append(f"{overlaps} overlapping dialogue segment(s) were mixed together.")
    return {"duration": duration, "overlap_count": overlaps, "peak_before_limit": peak,
            "warnings": warnings}
