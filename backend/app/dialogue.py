"""Duration budgets and bounded fitting; never discard non-silent speech."""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import soundfile as sf

from .config import settings
from .media import run


def duration_budgets(segments: list[dict], duration: float) -> dict[str, dict]:
    rows=sorted(segments,key=lambda s:float(s['start']))
    result={}
    for index,row in enumerate(rows):
        start,end=float(row['start']),float(row['end'])
        following=rows[index+1:]
        next_start=float(following[0]['start']) if following else duration
        source_overlap=max(0,end-next_start) if following else 0
        # Preserve measured source overlap. An ASR overlap is evidence of an
        # interval, not proof that there really are two simultaneous speakers.
        available=max(.05,min(duration,end if source_overlap else next_start)-start)
        text=row.get('short_translation') or row.get('translated_text','')
        result[row['id']]={'source_interval':[start,end],'next_dialogue_start':next_start,
            'available_duration':available,'source_overlap_seconds':source_overlap,
            'estimated_english_duration':len(text.split())/2.7,
            'requires_timing_review':len(text.split())/2.7>available*1.25}
    return result


def fit_voice(source: Path, destination: Path, available: float, max_speed: float=1.25) -> dict:
    samples,rate=sf.read(source,dtype='float32',always_2d=True)
    # Only remove low-energy outer padding; retain 40 ms of context either side.
    active=np.flatnonzero(np.max(np.abs(samples),axis=1)>.002)
    left=max(0,int(active[0])-round(.04*rate)) if len(active) else 0
    right=min(len(samples),int(active[-1])+1+round(.04*rate)) if len(active) else len(samples)
    trimmed=source.with_name(source.stem+'-padding-trimmed.wav')
    sf.write(trimmed,samples[left:right],rate,subtype='PCM_16')
    speaking=(right-left)/rate
    speed=min(max_speed,max(1,speaking/max(.05,available)))
    # atempo is followed by exactly one resample to the final 48 kHz timeline.
    run([settings.ffmpeg,'-y','-v','error','-i',str(trimmed),'-af',f'atempo={speed:.9f},aresample=48000',
         '-ar','48000','-ac','1','-c:a','pcm_s16le',str(destination)])
    actual=sf.info(destination).duration
    return {'raw_duration':len(samples)/rate,'duration_after_stretch':actual,
        'available_duration':available,'trimmed_leading_silence':left/rate,
        'trimmed_trailing_silence':(len(samples)-right)/rate,'time_stretch_ratio':speed,
        'overflow_duration':max(0,actual-available),'sample_rate':48000,
        'adjustment_strategy':'outer-silence-trim+bounded-atempo+single-48k-resample',
        'speech_samples_discarded':0,'timing_warning':actual>available+.02,
        'expected_samples':math.ceil(actual*48000)}
