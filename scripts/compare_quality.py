"""Collect genuine Phase 2.6 output and timestamped A/B evidence. No inference."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import shutil
import sqlite3

import cv2
import numpy as np
from PIL import Image,ImageDraw

from validate_acceptance import audio_metrics,command,continuity,probe,save,sha
from app.subtitle_quality import frame_mask
from app.subtitles import caption_cues


def check_protected(manifest:Path):
    expected=json.loads(manifest.read_text(encoding='utf-8'))
    changed=[path for path,checksum in expected.items() if not Path(path).is_file() or sha(Path(path))!=checksum]
    if changed:
        raise RuntimeError('Protected Phase 2.5 media/evidence changed: '+', '.join(changed))
    return len(expected)


def collision_metrics(timeline):
    rows=timeline['segments']
    return {'collisions_over_20ms':sum(s['collision_seconds']>.02 for s in rows),
        'unintended_over_100ms':sum(s.get('unintended_collision_seconds',s['collision_seconds'])>.1 for s in rows),
        'max_collision_seconds':max([0]+[s['collision_seconds'] for s in rows]),
        'end_truncated_seconds':sum(s['truncated_seconds'] for s in rows)}


def collect(args):
    root=args.evidence
    root.mkdir(parents=True,exist_ok=True)
    protected_count=check_protected(root/'protected-before.json')
    assert sha(args.source)==args.expected_source_sha256.lower(),'Original test.webm changed'
    work=args.data/'jobs'/args.job_id
    output=args.data/'output'/f'{args.job_id}.mp4'
    metadata=json.loads((work/'tts-metadata.json').read_text())
    report=json.loads((work/'subtitle-report.json').read_text())
    transcript=json.loads((work/'transcript.json').read_text())
    performance=json.loads((work/'performance.json').read_text())
    with sqlite3.connect(f'file:{args.data / "studio.sqlite3"}?mode=ro',uri=True) as connection:
        job=connection.execute('SELECT status,created_at,updated_at,options_json,input_path FROM jobs WHERE id=?',(args.job_id,)).fetchone()
    assert job and job[0].startswith('completed'), 'The actual application job must complete first'
    assert sha(Path(job[4]))==sha(args.clip),'Snapshot/input hash mismatch'
    input_probe,old_probe,new_probe=probe(args.clip),probe(args.previous),probe(output)
    video=next(s for s in new_probe['streams'] if s['codec_type']=='video')
    audio=next(s for s in new_probe['streams'] if s['codec_type']=='audio')
    original_video=next(s for s in input_probe['streams'] if s['codec_type']=='video')
    assert (video['width'],video['height'],video['avg_frame_rate'])==(original_video['width'],original_video['height'],original_video['avg_frame_rate'])
    assert video['codec_name']=='h264' and audio['codec_name']=='aac'
    assert int(audio['sample_rate'])==48000 and audio['channels']==2
    assert abs(float(new_probe['format']['duration'])-60)<.1
    assert abs(float(video['duration'])-float(audio['duration']))<.1
    command(['ffmpeg','-v','error','-xerror','-i',str(output),'-f','null','-'])
    packet_report=continuity(output)
    assert all(s['non_monotonic_dts']==0 for s in packet_report.values())
    cues=caption_cues(transcript['segments'])
    assert cues and all(0<=c['start']<c['end']<=60.1 for c in cues)
    assert all(a['end']<=b['start']+.001 for a,b in zip(cues,cues[1:]))
    assets={'source-audio.wav':'original-audio.wav','speech.wav':'asr-input.wav','background.wav':'background-stem.wav',
        'dub.wav':'english-dialogue.wav','mixed.wav':'mixed-audio.wav','transcript.json':'transcript.json',
        'asr-raw.json':'asr-raw.json','tts-metadata.json':'tts-metadata.json','performance.json':'performance.json',
        'english-subtitles.ass':'english-subtitles.ass','english-subtitles.srt':'english-subtitles.srt',
        'subtitle-report.json':'subtitle-report.json','ocr-trace.json':'ocr-trace.json','stage-cache.json':'stage-cache.json'}
    for source,name in assets.items():
        shutil.copy2(work/source,root/name)
    for stem,name in [('vocals.wav','speech-stem.wav'),('no_vocals.wav','background-stem-native.wav')]:
        shutil.copy2(work/'demucs'/'htdemucs'/'source-audio'/stem,root/name)
    shutil.copytree(work/'voices',root/'english-voice-tracks',dirs_exist_ok=True)
    shutil.copytree(work/'preview',root/'previews',dirs_exist_ok=True)
    final=root/'dubbed-60s-v26.mp4'
    if final.exists() and sha(final)!=sha(output):
        raise RuntimeError('A different Phase 2.6 acceptance output already exists; preserve it before recollecting')
    if not final.exists():
        shutil.copy2(output,final)
    quality={name:audio_metrics(root/name) for name in ('original-audio.wav','speech-stem.wav','background-stem.wav','english-dialogue.wav','mixed-audio.wav')}
    assert quality['mixed-audio.wav']['clipped_sample_count']==0
    assert quality['english-dialogue.wav']['peak']>.001
    fitted={s['segment_id']:audio_metrics(work/'voices'/f"{s['segment_id']}-fit.wav") for s in metadata['segments']}
    assert fitted and all(v['peak']>.001 for v in fitted.values())
    assert all(s['voice_id']==metadata['voices'][next(r['speaker_id'] for r in transcript['segments'] if r['id']==s['segment_id'])] for s in metadata['segments'])
    loudness=command(['ffmpeg','-hide_banner','-i',str(output),'-af','ebur128=peak=true','-f','null','-']).stderr
    (root/'loudness.log').write_text(loudness)
    lufs=float(re.findall(r'I:\s+(-?[\d.]+) LUFS',loudness)[-1])
    peak=float(re.findall(r'Peak:\s+(-?[\d.]+) dBFS',loudness)[-1])
    timing=collision_metrics(metadata['timeline'])
    save(root/'audio-quality-report.json',{'tracks':quality,'fitted_voices':fitted,'timeline':metadata['timeline'],
        **timing,'integrated_lufs':lufs,'true_peak_dbfs':peak,'human_listening':'PENDING_HUMAN_REVIEW'})
    # Compare the lossless strip with the original, before final encoding/burn-in.
    cap=cv2.VideoCapture(str(args.clip))
    patch=cv2.VideoCapture(report['output_video']) if report.get('patch_roi') else None
    index=inactive=changed=outside_changed=0
    while True:
        ok,frame=cap.read()
        if not ok:
            break
        mask=frame_mask(frame,report['regions'],index,report['fps'])
        rebuilt=frame.copy()
        if patch:
            ok2,strip=patch.read()
            assert ok2,'Subtitle strip is shorter than the source'
            x,y,w,h=report['patch_roi']
            rebuilt[y:y+h,x:x+w]=strip
        if not mask.any():
            inactive+=1
            changed+=int(not np.array_equal(frame,rebuilt))
        outside_changed+=int(not np.array_equal(frame[mask==0],rebuilt[mask==0]))
        index+=1
    cap.release()
    if patch:
        patch.release()
    assert changed==0 and outside_changed==0,'Unmasked pixels were modified'
    comparison_root=root/'comparisons'
    for seconds in (20,42,54):
        folder=comparison_root/str(seconds)
        folder.mkdir(parents=True,exist_ok=True)
        for media,name in [(args.clip,'original-source-frame.png'),(args.previous,'phase25-output-frame.png'),(output,'phase26-output-frame.png')]:
            command(['ffmpeg','-y','-v','error','-ss',str(seconds),'-i',str(media),'-frames:v','1','-update','1',str(folder/name)])
        board=Image.new('RGB',(2880,760),'#15181d')
        draw=ImageDraw.Draw(board)
        for i,(name,label) in enumerate([('original-source-frame.png','Original input'),('phase25-output-frame.png','Phase 2.5'),('phase26-output-frame.png','Phase 2.6')]):
            image=Image.open(folder/name)
            board.paste(image.resize((960,540)),(i*960,30))
            board.paste(image.crop((300,875,1620,1080)).resize((960,149)),(i*960,585))
            draw.text((i*960+12,8),f'{label} - {seconds:02d}s',fill='white')
        board.save(folder/'side-by-side.png')
    old=json.loads((args.previous.parent/'audio-quality-report.json').read_text())
    old_summary=json.loads((args.previous.parent/'validation-summary.json').read_text())
    elapsed=sum(p['elapsed_seconds'] for p in performance)
    memory=max([0]+[p.get('container_memory_peak_bytes',0) for p in performance])
    disk=sum(p.stat().st_size for p in work.rglob('*') if p.is_file())
    strip_bytes=Path(report['output_video']).stat().st_size if report.get('patch_roi') else 0
    metrics={'job_id':args.job_id,'status':job[0],'options':json.loads(job[3]),'source_sha256':sha(args.source),
        'clip_sha256':sha(args.clip),'previous_output_sha256':sha(args.previous),'output_sha256':sha(output),
        'protected_files_verified':protected_count,'final_probe':new_probe,'timing':timing,'integrated_lufs':lufs,
        'true_peak_dbfs':peak,'processing_seconds':round(elapsed,3),'stage_attempts':performance,
        'wall_seconds':(datetime.fromisoformat(job[2])-datetime.fromisoformat(job[1])).total_seconds(),
        'peak_cgroup_bytes':memory,'job_disk_bytes':disk,'repair_strip_bytes':strip_bytes,'final_bytes':output.stat().st_size,
        'inactive_frames_compared':inactive,'inactive_frames_changed':changed,'frames_with_changed_unmasked_pixels':outside_changed,
        'output_validation':'PASS','subjective_audio_video_quality':'PENDING_HUMAN_REVIEW'}
    save(root/'validation-summary.json',metrics)
    for name,value in [('ffprobe-input.json',input_probe),('ffprobe-phase25.json',old_probe),('ffprobe-output.json',new_probe),('timestamp-continuity.json',packet_report)]:
        save(root/name,value)
    table=[('Collisions >20 ms',old['collisions_over_20ms'],timing['collisions_over_20ms'],'measured'),
        ('Maximum collision (s)',old['max_collision_seconds'],timing['max_collision_seconds'],'measured'),
        ('Final audio (Hz)',next(s['sample_rate'] for s in old_probe['streams'] if s['codec_type']=='audio'),audio['sample_rate'],'measured'),
        ('Integrated loudness (LUFS)',old['final_integrated_loudness_lufs'],lufs,'measured'),
        ('True peak (dBFS)',old['final_true_peak_dbfs'],peak,'measured'),
        ('All processing attempts (s)',old_summary['processing_seconds_all_attempts'],round(elapsed,3),'different retry/cache histories; not a cold benchmark'),
        ('Peak cgroup memory (bytes)',old_summary['container_memory_peak_bytes'],memory,'includes page cache'),
        ('Lossless repair intermediate (bytes)',1029431357,strip_bytes,'full-frame versus subtitle strip'),
        ('Final MP4 (bytes)',args.previous.stat().st_size,output.stat().st_size,'measured'),
        ('Human audio/video approval','PENDING_HUMAN_REVIEW','PENDING_HUMAN_REVIEW','no listening approval')]
    text='# Phase 2.5 / 2.6 comparison\n\nMetric | Phase 2.5 | Phase 2.6 | Result\n---|---:|---:|---\n'
    text+='\n'.join(' | '.join(map(str,row)) for row in table)
    text+='\n\nTimestamped full frames and readable crops: comparisons/20, comparisons/42, comparisons/54. Visual inspection notes must be added after looking at the actual exported images. OCR alone does not accept reconstruction quality.\n'
    (root/'comparison-report.md').write_text(text,encoding='utf-8')
    check_protected(root/'protected-before.json')
    return metrics


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--job-id',required=True)
    parser.add_argument('--data',type=Path,default=Path('/data'))
    parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--clip',type=Path,required=True)
    parser.add_argument('--previous',type=Path,required=True)
    parser.add_argument('--expected-source-sha256',required=True)
    result=collect(parser.parse_args())
    print(json.dumps({k:result[k] for k in ('job_id','timing','processing_seconds','output_validation','output_sha256')},indent=2))


if __name__=='__main__':
    main()
