"""Collect and validate a completed real-video job without calling any model.

Run inside the image with project source mounted read-only and /data writable.
This reports measured evidence and leaves subjective acceptance pending.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import soundfile as sf

from app.subtitles import active_boxes, caption_cues


def command(args):
    result=subprocess.run(args,capture_output=True,text=True,encoding="utf-8",errors="replace")
    if result.returncode:
        raise RuntimeError(f"Command failed: {args[:3]}\n{result.stderr[-2000:]}")
    return result


def save(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding="utf-8")


def sha(path):
    h=hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda:source.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()


def probe(path):
    return json.loads(command(["ffprobe","-v","error","-show_streams","-show_format","-of","json",str(path)]).stdout)


def continuity(path):
    packets=json.loads(command(["ffprobe","-v","error","-show_packets","-show_entries",
                                "packet=stream_index,dts_time,pts_time,duration_time","-of","json",str(path)]).stdout)["packets"]
    streams={}
    previous={}
    for packet in packets:
        index=packet["stream_index"]
        result=streams.setdefault(str(index),{"packets":0,"non_monotonic_dts":0,"largest_gap_seconds":0.0})
        result["packets"]+=1
        dts=float(packet.get("dts_time",packet.get("pts_time",0)))
        duration=float(packet.get("duration_time",0))
        if index in previous:
            last,last_duration=previous[index]
            result["non_monotonic_dts"]+=int(dts<last-.00001)
            result["largest_gap_seconds"]=round(max(result["largest_gap_seconds"],dts-last-last_duration),6)
        previous[index]=(dts,duration)
    return streams


def audio_metrics(path):
    peak=squares=clipped=count=0
    silent=[]
    with sf.SoundFile(path) as source:
        rate=source.samplerate
        channels=source.channels
        for i,block in enumerate(source.blocks(blocksize=rate//4,dtype="float32",always_2d=True)):
            peak=max(peak,float(np.max(np.abs(block))))
            clipped+=int(np.sum(np.abs(block)>=.999))
            squares+=float(np.sum(block.astype(np.float64)**2))
            count+=block.size
            if float(np.sqrt(np.mean(block**2)))<10**(-55/20):
                silent.append(i*.25)
    spans=[]
    for start in silent:
        if spans and abs(spans[-1][1]-start)<.001:
            spans[-1][1]=start+.25
        else:
            spans.append([start,start+.25])
    rms=math.sqrt(squares/max(1,count))
    return {"duration":sf.info(path).duration,"sample_rate":rate,"channels":channels,
            "peak":peak,"peak_dbfs":20*math.log10(max(peak,1e-12)),
            "rms_dbfs":20*math.log10(max(rms,1e-12)),"clipped_sample_count":clipped,
            "silence_threshold_dbfs":-55,"silent_spans_seconds":spans}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--source",type=Path,required=True)
    parser.add_argument("--clip",type=Path,required=True)
    parser.add_argument("--job-id",required=True)
    parser.add_argument("--evidence",type=Path,required=True)
    parser.add_argument("--data",type=Path,default=Path("/data"))
    parser.add_argument("--expected-source-sha256",required=True)
    args=parser.parse_args()
    evidence=args.evidence
    evidence.mkdir(parents=True,exist_ok=True)
    work=args.data / "jobs" / args.job_id
    output=args.data / "output" / f"{args.job_id}.mp4"
    assert sha(args.source)==args.expected_source_sha256.lower(),"User source hash changed"
    assert output.is_file() and output.stat().st_size>1024
    source_probe,input_probe,output_probe=probe(args.source),probe(args.clip),probe(output)
    for name,value in [("source",source_probe),("input",input_probe),("output",output_probe)]:
        save(evidence / f"ffprobe-{name}.json",value)
    streams=output_probe["streams"]
    video=next(stream for stream in streams if stream["codec_type"]=="video")
    audio=next(stream for stream in streams if stream["codec_type"]=="audio")
    assert video["codec_name"]=="h264" and audio["codec_name"]=="aac"
    assert (video["width"],video["height"])==(1920,1080)
    assert video["avg_frame_rate"]=="25/1"
    assert abs(float(output_probe["format"]["duration"])-60)<.1
    assert abs(float(video["duration"])-float(audio["duration"]))<.1
    decode=command(["ffmpeg","-v","error","-xerror","-i",str(output),"-f","null","-"])
    (evidence / "output-decode.log").write_text(decode.stderr or "No decode errors.\n",encoding="utf-8")
    integrity={"source":continuity(args.source),"input":continuity(args.clip),"output":continuity(output)}
    assert all(stream["non_monotonic_dts"]==0 for group in integrity.values() for stream in group.values())
    save(evidence / "timestamp-continuity.json",integrity)
    files={"test-60s.mp4":args.clip,"dubbed-60s.mp4":output,"original-audio.wav":work / "source-audio.wav",
           "speech-stem.wav":work / "demucs" / "htdemucs" / "source-audio" / "vocals.wav",
           "asr-input.wav":work / "speech.wav","background-stem.wav":work / "background.wav",
           "background-stem-original.wav":work / "demucs" / "htdemucs" / "source-audio" / "no_vocals.wav",
           "english-dialogue.wav":work / "dub.wav","mixed-audio.wav":work / "mixed.wav",
           "transcript.json":work / "transcript.json","english-subtitles.ass":work / "english-subtitles.ass",
           "english-subtitles.srt":work / "english-subtitles.srt","tts-metadata.json":work / "tts-metadata.json",
           "ocr-trace.json":work / "ocr-trace.json","subtitle-report.json":work / "subtitle-report.json",
           "performance.json":work / "performance.json",
           "subtitle-mask-preview.png":work / "preview" / "subtitle-mask.png",
           "subtitle-repaired-preview.png":work / "preview" / "subtitle-repaired.png",
           "english-subtitle-preview.png":work / "preview" / "english-subtitle.png"}
    missing=[]
    for name,path in files.items():
        if path.is_file():
            shutil.copyfile(path,evidence / name)
        else:
            missing.append({"artifact":name,"reason":"Not produced by this job; inspect subtitle mode/stage status."})
    shutil.copytree(work / "voices",evidence / "english-voice-tracks",dirs_exist_ok=True)
    transcript=json.loads((work / "transcript.json").read_text(encoding="utf-8"))
    segments=transcript["segments"]
    cues=caption_cues(segments)
    assert cues and all(0<=cue["start"]<cue["end"]<=60.1 for cue in cues)
    subtitle_overlaps=[i for i in range(1,len(cues)) if cues[i]["start"]<cues[i-1]["end"]-.01]
    assert not subtitle_overlaps,"Unexpected overlapping English caption intervals"
    assert all(max(map(len,cue["text"].splitlines()))<=54 and len(cue["text"].splitlines())<=2 for cue in cues)
    save(evidence / "translation.json",{"provider":transcript.get("translation_provider"),"segments":segments})
    tts=json.loads((work / "tts-metadata.json").read_text(encoding="utf-8"))
    voice_by_segment={row["segment_id"]:row["voice_id"] for row in tts["segments"]}
    for seg in segments:
        if seg.get("translated_text","").strip():
            assert voice_by_segment[seg["id"]]==tts["voices"][seg["speaker_id"]],"Speaker voice changed unexpectedly"
    assigned={seg["speaker_id"]:tts["voices"][seg["speaker_id"]] for seg in segments}
    assert len(set(assigned.values()))==len(assigned),"This multi-speaker acceptance sample requires distinct assigned voices"
    save(evidence / "speaker-assignments.json",{"method":"manual visual proposals; NOT automatic diarization",
         "identity_status":"PENDING_HUMAN_REVIEW","voices":tts["voices"],
         "segments":[{key:seg[key] for key in ("id","start","end","source_text","translated_text","speaker_id")} for seg in segments]})
    metrics={name:audio_metrics(evidence / name) for name in ("original-audio.wav","speech-stem.wav","background-stem.wav","english-dialogue.wav","mixed-audio.wav")}
    voice_metrics={path.name:audio_metrics(path) for path in (evidence / "english-voice-tracks").glob("*.wav")}
    assert voice_metrics and all(value["peak"]>.001 for value in voice_metrics.values())
    assert metrics["mixed-audio.wav"]["clipped_sample_count"]==0
    assert metrics["english-dialogue.wav"]["peak"]>.01
    loudness=command(["ffmpeg","-hide_banner","-i",str(output),"-vn","-af","ebur128=peak=true","-f","null","-"])
    (evidence / "loudness-ebur128.log").write_text(loudness.stderr,encoding="utf-8")
    integrated=re.findall(r"I:\s+(-?[\d.]+) LUFS",loudness.stderr)
    true_peak=re.findall(r"Peak:\s+(-?[\d.]+) dBFS",loudness.stderr)
    audio_report={"tracks":metrics,"synthesized_voice_tracks":voice_metrics,"timeline":tts["timeline"],
                  "final_integrated_loudness_lufs":float(integrated[-1]) if integrated else None,
                  "final_true_peak_dbfs":float(true_peak[-1]) if true_peak else None,
                  "human_listening":"PENDING_HUMAN_REVIEW","background_preservation":"PENDING_HUMAN_REVIEW",
                  "original_dialogue_residual":"PENDING_HUMAN_REVIEW"}
    timing_rows=tts["timeline"]["segments"]
    audio_report["collisions_over_20ms"]=sum(row["collision_seconds"]>.02 for row in timing_rows)
    audio_report["max_collision_seconds"]=max((row["collision_seconds"] for row in timing_rows),default=0)
    audio_report["end_truncated_seconds"]=sum(row["truncated_seconds"] for row in timing_rows)
    audio_report["timing_acceptance"]="PARTIAL" if audio_report["collisions_over_20ms"] or audio_report["end_truncated_seconds"] else "PASS"
    save(evidence / "audio-quality-report.json",audio_report)
    # Verify ALL inactive frames against the lossless intermediate, before burn-in.
    report=json.loads((work / "subtitle-report.json").read_text(encoding="utf-8"))
    intervals=report.get("regions",[])
    comparison={"inactive_frames_compared":0,"inactive_frames_changed":0}
    if report.get("mask_applied"):
        before=cv2.VideoCapture(str(args.clip))
        after=cv2.VideoCapture(report["output_video"])
        index=0
        while True:
            ok,frame=before.read()
            ok2,repaired=after.read()
            assert ok==ok2,"Subtitle intermediate frame count mismatch"
            if not ok:
                break
            if not active_boxes(intervals,index,25):
                comparison["inactive_frames_compared"]+=1
                comparison["inactive_frames_changed"]+=int(not np.array_equal(frame,repaired))
            index+=1
        before.release()
        after.release()
        assert comparison["inactive_frames_changed"]==0
    save(evidence / "temporal-mask-validation.json",comparison)
    job_file=evidence / "job.json"
    job=json.loads(job_file.read_text(encoding="utf-8-sig")) if job_file.exists() else {}
    snapshot_sha=sha(Path(job["input_path"])) if job.get("input_path") else None
    assert snapshot_sha==sha(args.clip),"Imported snapshot differs from the unmodified inbox clip"
    timings={stage["name"]:(datetime.fromisoformat(stage["finished_at"])-datetime.fromisoformat(stage["started_at"])).total_seconds()
             for stage in job.get("stages",[]) if stage.get("finished_at") and stage.get("started_at")}
    performance_file=work / "performance.json"
    performance=json.loads(performance_file.read_text(encoding="utf-8")) if performance_file.exists() else []
    if performance:
        timings={entry["stage"]:entry["elapsed_seconds"] for entry in performance if entry["status"]=="completed"}
    manifest={"job_id":args.job_id,"source_sha256":sha(args.source),"clip_sha256":sha(args.clip),"import_snapshot_sha256":snapshot_sha,"output_sha256":sha(output),
              "stage_seconds":timings,"processing_seconds_all_attempts":round(sum(entry["elapsed_seconds"] for entry in performance),3),
              "processing_seconds_selected_stages":round(sum(timings.values()),3),
              "container_memory_peak_bytes":max((entry.get("container_memory_peak_bytes",0) for entry in performance),default=0),
              "automated_media_validation":"PASS","subtitle_cues":len(cues),
              "subjective_audio_video_acceptance":"PENDING_HUMAN_REVIEW","missing_artifacts":missing,
              "files":[{"name":str(path.relative_to(evidence)),"bytes":path.stat().st_size} for path in sorted(evidence.rglob("*")) if path.is_file()]}
    save(evidence / "validation-summary.json",manifest)
    print(json.dumps({key:value for key,value in manifest.items() if key!="files"},ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
