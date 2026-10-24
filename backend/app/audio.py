from __future__ import annotations

import math
import tempfile
from pathlib import Path
from typing import Callable

import numpy as np
import soundfile as sf


SAMPLE_RATE = 24000


def compose_timeline(segments: list[dict], voice_files: dict[str, Path], duration: float,
                     output: Path, checkpoint: Callable[[],None] | None=None) -> dict:
    """Mix in one-second blocks, retaining explicit overflow/truncation evidence."""
    total=max(1,math.ceil(duration*SAMPLE_RATE))
    warnings=[]
    tracks=[]
    diagnostics=[]
    active_until=0
    overlaps=0
    for seg in sorted(segments,key=lambda row:float(row["start"])):
        path=voice_files.get(seg["id"])
        if path is None or not path.exists():
            continue
        info=sf.info(path)
        if info.samplerate!=SAMPLE_RATE:
            raise ValueError(f"Unexpected TTS sample rate in {path}: {info.samplerate}")
        offset=max(0,int(float(seg["start"])*SAMPLE_RATE))
        slot=max(1,int((float(seg["end"])-float(seg["start"]))*SAMPLE_RATE))
        if info.frames>slot*1.02:
            warnings.append(f"Segment {seg['id']} remains longer than its original dialogue slot; speech was preserved without extreme acceleration and may overlap following dialogue.")
        collision=max(0,active_until-offset)/SAMPLE_RATE
        if offset<active_until:
            overlaps+=1
        active_until=max(active_until,offset+info.frames)
        truncated=max(0,offset+info.frames-total)/SAMPLE_RATE
        if truncated:
            warnings.append(f"Segment {seg['id']} extends beyond the source video duration; {truncated:.3f}s of its tail cannot fit in the export. Review timing before accepting.")
        diagnostics.append({"segment_id":seg["id"],"speaker_id":seg.get("speaker_id","speaker_1"),
                            "start":offset/SAMPLE_RATE,"source_end":float(seg["end"]),
                            "generated_end":(offset+info.frames)/SAMPLE_RATE,"generated_duration":info.duration,
                            "overflow_seconds":max(0,info.frames-slot)/SAMPLE_RATE,
                            "collision_seconds":collision,"truncated_seconds":truncated})
        tracks.append((offset,info.frames,path))
    peak=0.0
    # A float scratch WAV preserves peaks until a second streaming normalization
    # pass. Audio RAM is bounded even for long sources; disk use is explicit.
    with tempfile.NamedTemporaryFile(suffix=".wav",prefix="timeline-",dir=output.parent,delete=False) as temp:
        scratch=Path(temp.name)
    try:
        with sf.SoundFile(scratch,"w",samplerate=SAMPLE_RATE,channels=2,subtype="FLOAT",format="WAV") as target:
            for start in range(0,total,SAMPLE_RATE):
                if checkpoint:
                    checkpoint()
                end=min(total,start+SAMPLE_RATE)
                block=np.zeros((end-start,2),dtype=np.float32)
                for offset,length,path in tracks:
                    left,right=max(start,offset),min(end,offset+length)
                    if right<=left:
                        continue
                    with sf.SoundFile(path) as audio:
                        audio.seek(left-offset)
                        samples=audio.read(right-left,dtype="float32",always_2d=True)
                    if samples.shape[1]==1:
                        samples=np.repeat(samples,2,axis=1)
                    block[left-start:right-start]+=samples[:,:2]
                peak=max(peak,float(np.max(np.abs(block))))
                target.write(block)
        gain=min(1.0,.93/peak) if peak else 1.0
        with sf.SoundFile(scratch) as source,sf.SoundFile(output,"w",samplerate=SAMPLE_RATE,channels=2,subtype="PCM_16") as target:
            for block in source.blocks(blocksize=SAMPLE_RATE,dtype="float32",always_2d=True):
                if checkpoint:
                    checkpoint()
                target.write(block*gain)
    finally:
        scratch.unlink(missing_ok=True)
    if overlaps:
        warnings.append(f"{overlaps} overlapping dialogue segment(s) were mixed together.")
    return {"duration":duration,"overlap_count":overlaps,"peak_before_limit":peak,
            "normalization_gain":gain,"segments":diagnostics,"warnings":warnings}
