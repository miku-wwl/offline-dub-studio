from __future__ import annotations

import json
import hashlib
import os
import subprocess
import sys
import time
from fractions import Fraction
from pathlib import Path
from typing import Callable

from .audio import SAMPLE_RATE, compose_timeline
from .config import effective_cpu_count, settings
from .db import Database, now
from .domain import JobOptions
from .media import MediaError, probe_media, run
from .models import list_packs
from .providers import ASRProvider, ProviderUnavailable, TTSProvider, TranslationProvider
from .subtitles import readable_caption_margin, write_ass, write_srt
from .subtitle_quality import detect_boxes, redact_video, manual_intervals, VERSION
from .dialogue import duration_budgets, fit_voice


STAGES = ["inspect", "extract", "separate", "transcribe", "translate", "synthesize", "subtitle_processing", "render"]


class JobCancelled(RuntimeError):
    pass


def _dump(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _file_digest(path:Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source,"sha256").hexdigest()


class Pipeline:
    def __init__(self, db: Database, cancel_check: Callable[[], bool]):
        self.db, self.cancel_check = db, cancel_check
        self.asr = ASRProvider()
        self.translation = TranslationProvider()
        self.tts = TTSProvider()

    def _checkpoint(self):
        if self.cancel_check():
            raise JobCancelled("Cancelled by user")

    def run(self, job: dict) -> dict:
        job_id = job["id"]
        source = Path(job["input_path"])
        work = settings.jobs_dir / job_id
        work.mkdir(parents=True, exist_ok=True)
        options = JobOptions.model_validate(job["options"])
        state = {"work":work,"source":source,"options":options,"probe":None,"segments":None,"artifacts":{}}
        cached_stages = {s["name"]:s for s in (job.get("stages") or [])}
        receipt_path=work / 'stage-cache.json'
        receipts=json.loads(receipt_path.read_text()) if receipt_path.exists() else {}
        for index, stage in enumerate(STAGES):
            self._checkpoint()
            if stage=="synthesize" and options.transcript_review_required and not options.transcript_review_approved:
                self.db.log(job_id,"info","Transcript and speaker assignments are ready for review before voice generation.")
                return {"status":"awaiting_transcript_review"}
            if stage == "render" and not options.subtitle_review_approved:
                self.db.log(job_id,"info","Final export is waiting for subtitle preview approval.")
                return {"status":"awaiting_review"}
            old = cached_stages.get(stage)
            fingerprint=self._fingerprint(stage,state)
            receipt=receipts.get(stage,{})
            valid_outputs=all(Path(p).is_file() and _file_digest(Path(p))==h for p,h in receipt.get('outputs',{}).items()) if isinstance(receipt,dict) else False
            if old and old["status"] == "completed" and isinstance(receipt,dict) and receipt.get('input')==fingerprint and valid_outputs:
                artifacts = json.loads(old["artifacts_json"])
                if all(Path(p).exists() for p in artifacts.values() if isinstance(p,str) and ("/" in p or "\\" in p)):
                    state["artifacts"].update(artifacts)
                    self._load_state(stage,state,artifacts)
                    self._update_progress(job_id,stage,100,(index+1)/len(STAGES)*100)
                    self.db.log(job_id,'info',f'Validated dependency cache reused: {stage}')
                    continue
            self.db.execute("INSERT INTO stages(job_id,name,status,progress,started_at,finished_at,error,artifacts_json) VALUES(?,?,?,0,?,NULL,NULL,'{}') "
                            "ON CONFLICT(job_id,name) DO UPDATE SET status=excluded.status,progress=0,started_at=excluded.started_at,finished_at=NULL,error=NULL",
                            (job_id,stage,"running",now()))
            self._update_progress(job_id,stage,0,index/len(STAGES)*100)
            self.db.log(job_id,"info",f"Stage started: {stage}")
            started=time.perf_counter()
            try:
                result = getattr(self,f"_stage_{stage}")(state)
            except BaseException:
                self._record_performance(work,stage,time.perf_counter()-started,"failed_or_cancelled")
                raise
            self._record_performance(work,stage,time.perf_counter()-started,"completed")
            # transcript.json is explicitly editable through the review API;
            # the independent raw ASR result remains immutable and hash checked.
            receipts[stage]={'input':fingerprint,'outputs':{p:_file_digest(Path(p)) for key,p in result.items()
                if key not in {'transcript','subtitle_report'} and isinstance(p,str) and Path(p).is_file()}}
            _dump(receipt_path,receipts)
            state["artifacts"].update(result)
            self.db.execute("UPDATE stages SET status='completed',progress=100,finished_at=?,artifacts_json=? WHERE job_id=? AND name=?",
                            (now(),json.dumps(result),job_id,stage))
            self.db.log(job_id,"info",f"Stage completed: {stage}")
            self._update_progress(job_id,stage,100,(index+1)/len(STAGES)*100)
            if stage == "subtitle_processing" and not options.subtitle_review_approved:
                self.db.log(job_id,"info","Subtitle preview is ready for user review before final export.")
                return {"status":"awaiting_review"}
            if stage == "subtitle_processing" and options.subtitle_review_approved:
                continue
            if stage == "render":
                continue
        # Cached subtitle stage also needs a review boundary when resuming an unapproved job.
        if not options.subtitle_review_approved:
            self.db.log(job_id,"info","Subtitle preview is ready for user review before final export.")
            return {"status":"awaiting_review"}
        _dump(work / "pipeline-result.json", {"status":"completed","artifacts":state["artifacts"]})
        return {"status":"completed"}

    def _fingerprint(self,stage,state):
        work,opts=state['work'],state['options']
        def file(name):
            path=work / name
            return _file_digest(path) if path.is_file() else 'missing'
        segments=state.get('segments') or []
        source_rows=[{k:s.get(k) for k in ('id','start','end','source_text','speaker_id')} for s in segments]
        voiced_rows=[{k:s.get(k) for k in ('id','start','end','translated_text','short_translation','speaker_id')} for s in segments]
        translation_rows=[s.get('translation_provenance',{}).get('manual_override') for s in segments]
        voices=self.db.query('SELECT speaker_id,voice_id FROM speakers WHERE job_id=? ORDER BY speaker_id',(work.name,))
        source_digest=_file_digest(state['source']) if state['source'].is_file() else 'missing'
        repair_path=work / 'subtitle-report.json'
        repair=json.loads(repair_path.read_text()) if repair_path.exists() else {}
        repair_inputs={k:repair.get(k) for k in ('output_video','repair_sha256','patch_roi')}
        if repair.get('output_video') and Path(repair['output_video']).is_file():
            repair_inputs['current_sha256']=_file_digest(Path(repair['output_video']))
        keys={
            'inspect':[source_digest],
            'extract':[source_digest,'48000-stereo'],
            'separate':[file('source-audio.wav'),'htdemucs','48000-bed'],
            'transcribe':[file('speech.wav'),opts.profile,opts.source_language],
            'translate':[source_rows,translation_rows,opts.translation_glossary],
            'synthesize':[voiced_rows,opts.voice_assignments,voices,opts.max_speech_speed],
            'subtitle_processing':[source_digest,voiced_rows,opts.subtitle_mode,opts.subtitle_regions,
                [m.model_dump() for m in opts.temporal_masks],opts.subtitle_font_size,opts.subtitle_margin_v,VERSION],
            'render':[file('dub.wav'),file('background.wav'),file('english-subtitles.ass'),repair_inputs,
                opts.dialogue_gain_db,opts.background_gain_db,'48000-stereo-latency-compensated']}
        return hashlib.sha256(json.dumps(['phase26',keys[stage]],sort_keys=True).encode()).hexdigest()

    def _record_performance(self,work:Path,stage:str,seconds:float,status:str):
        path=work / "performance.json"
        entries=json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        entry={"stage":stage,"elapsed_seconds":round(seconds,3),"status":status,"finished_at":now()}
        try:
            entry["container_memory_peak_bytes"]=int(Path("/sys/fs/cgroup/memory.peak").read_text().strip())
        except (OSError,ValueError):
            pass
        entries.append(entry)
        _dump(path,entries)

    def _update_progress(self, job_id: str, stage: str, stage_progress: float, overall: float):
        self.db.execute("UPDATE jobs SET stage=?,progress=?,updated_at=? WHERE id=?",
                        (stage,round(overall,1),now(),job_id))
        self.db.execute("UPDATE stages SET progress=? WHERE job_id=? AND name=? AND status='running'",
                        (stage_progress,job_id,stage))

    def _load_state(self, stage: str, state: dict, artifacts: dict):
        if stage == "inspect" and artifacts.get("inspection"):
            state["probe"] = json.loads(Path(artifacts["inspection"]).read_text(encoding="utf-8"))
        if stage == "transcribe" and artifacts.get("transcript"):
            state["segments"] = json.loads(Path(artifacts["transcript"]).read_text(encoding="utf-8"))["segments"]
        if stage == "translate" and artifacts.get("transcript"):
            state["segments"] = json.loads(Path(artifacts["transcript"]).read_text(encoding="utf-8"))["segments"]

    def _stage_inspect(self,state):
        data = probe_media(state["source"])
        if not data["has_audio"]:
            raise MediaError("This video has no audio stream to transcribe or dub.")
        path = state["work"] / "inspection.json"
        _dump(path,data)
        state["probe"] = data
        return {"inspection":str(path)}

    def _stage_extract(self,state):
        output = state["work"] / "source-audio.wav"
        run([settings.ffmpeg,"-y","-v","error","-i",str(state["source"]),"-map","0:a:0","-vn","-ac","2","-ar","48000","-c:a","pcm_s16le",str(output)],timeout=None)
        return {"source_audio":str(output)}

    def _stage_separate(self,state):
        pack = next((p for p in list_packs() if p["id"]=="separation-htdemucs"),None)
        if not pack or not pack["ready"]:
            raise ProviderUnavailable("Initialize the Demucs CPU model pack before processing (a model download is required once).")
        source = state["work"] / "source-audio.wav"
        output_dir = state["work"] / "demucs"
        env = os.environ.copy()
        env["TORCH_HOME"] = str(settings.models_dir / "torch")
        env["OMP_NUM_THREADS"] = str(effective_cpu_count())
        env["MKL_NUM_THREADS"] = str(effective_cpu_count())
        result = subprocess.run([sys.executable,"-m","app.demucs_runner","-d","cpu","-n","htdemucs","--two-stems","vocals","-o",str(output_dir),str(source)],
                                capture_output=True,text=True,encoding="utf-8",errors="replace",env=env)
        if result.returncode:
            raise RuntimeError("Demucs separation failed: " + (result.stderr or result.stdout)[-1800:])
        separated = output_dir / "htdemucs" / source.stem
        vocals, bed = separated / "vocals.wav", separated / "no_vocals.wav"
        if not vocals.exists() or not bed.exists():
            raise RuntimeError("Demucs did not produce the expected vocals/no_vocals stems")
        speech, background = state["work"] / "speech.wav", state["work"] / "background.wav"
        run([settings.ffmpeg,"-y","-v","error","-i",str(vocals),"-ac","1","-ar","16000","-c:a","pcm_s16le",str(speech)])
        run([settings.ffmpeg,"-y","-v","error","-i",str(bed),"-ac","2","-ar",str(SAMPLE_RATE),"-c:a","pcm_s16le",str(background)])
        return {"speech_audio":str(speech),"background_audio":str(background),"separation_log":str(output_dir)}

    def _stage_transcribe(self,state):
        profile=state["options"].profile
        model_id="asr-tiny" if profile=="cpu-lite" else "asr-small"
        result=self.asr.transcribe(state["work"] / "speech.wav",model_id,state["options"].source_language)
        transcript=state["work"] / "transcript.json"
        _dump(transcript,result)
        _dump(state['work'] / 'asr-raw.json',result)
        state["segments"]=result["segments"]
        return {"transcript":str(transcript),"asr_model":model_id,'asr_raw':str(state['work'] / 'asr-raw.json')}

    def _stage_translate(self,state):
        transcript=state["work"] / "transcript.json"
        data=json.loads(transcript.read_text(encoding="utf-8"))
        provider=self.translation.translate(data["segments"],state["options"].source_language,state["options"].target_language,state['options'].translation_glossary)
        data["translation_provider"]=provider
        _dump(transcript,data)
        state["segments"]=data["segments"]
        return {"transcript":str(transcript),"translation":str(provider.get("provider"))}

    def _stage_synthesize(self,state):
        tts_pack=next((p for p in list_packs() if p["id"]=="tts-kokoro-en"),None)
        if not tts_pack or not tts_pack["ready"]:
            raise ProviderUnavailable("Initialize the Kokoro CPU voice model pack before processing.")
        transcript_path=state["work"] / "transcript.json"
        data=json.loads(transcript_path.read_text(encoding="utf-8"))
        segments=data["segments"]
        voices=state["options"].voice_assignments
        speaker_rows=self.db.query("SELECT speaker_id,voice_id FROM speakers WHERE job_id=?",(state["work"].name,))
        voices.update({r["speaker_id"]:r["voice_id"] for r in speaker_rows})
        voice_files={}
        metadata=[]
        budgets=duration_budgets(segments,float(state['probe']['duration']))
        synth_dir=state["work"] / "voices"
        synth_dir.mkdir(exist_ok=True)
        for index,seg in enumerate(segments):
            self._checkpoint()
            text=(seg.get('short_translation') or seg.get("translated_text","")).strip()
            if not text:
                continue
            speaker=seg.get("speaker_id") or "speaker_1"
            voice=voices.get(speaker,"af_heart")
            audio_path=synth_dir / f"{seg['id']}.wav"
            tts_meta=self.tts.synthesize(text,voice,audio_path)
            fitted=audio_path.with_name(audio_path.stem+'-fit.wav')
            fitting=fit_voice(audio_path,fitted,budgets[seg['id']]['available_duration'],state['options'].max_speech_speed)
            audio_path=fitted
            tts_meta.update(fitting)
            seg['timing_budget']=budgets[seg['id']]
            seg['adjustment_strategy']=fitting['adjustment_strategy']
            tts_meta['translation_used']=text
            voice_files[seg["id"]]=audio_path
            metadata.append({"segment_id":seg["id"],**tts_meta,'timing_budget':budgets[seg['id']]})
            self._update_progress(state["work"].name,"synthesize",(index+1)/max(1,len(segments))*100,
                                  (STAGES.index("synthesize")+(index+1)/max(1,len(segments)))/len(STAGES)*100)
        duration=float(state["probe"]["duration"])
        dub=state["work"] / "dub.wav"
        timeline=compose_timeline(segments,voice_files,duration,dub,self._checkpoint)
        for warning in timeline["warnings"]:
            self.db.log(state["work"].name,"warning",warning)
        if not segments:
            self.db.log(state["work"].name,"warning","ASR returned no speech segments; review the extracted speech stem and source audio.")
        _dump(state["work"] / "tts-metadata.json",{"segments":metadata,"timeline":timeline,"voices":voices})
        if any(s['truncated_seconds']>.02 for s in timeline['segments']):
            raise RuntimeError('English speech extends beyond the video. Review the saved timing report and shorten the final translation; full raw voice tracks are preserved. Export is blocked rather than discarding spoken content.')
        return {"dub_audio":str(dub),"tts_metadata":str(state["work"] / "tts-metadata.json")}

    def _stage_subtitle_processing(self,state):
        options=state["options"]
        ass=state["work"] / "english-subtitles.ass"
        srt=state["work"] / "english-subtitles.srt"
        write_srt(state["segments"],srt)
        source=state["source"]
        warnings=[]
        if options.subtitle_mode=="none":
            video=source
            (state["work"] / "preview").mkdir(parents=True,exist_ok=True)
            try:
                run([settings.ffmpeg,"-y","-v","error","-i",str(source),"-frames:v","1","-update","1",
                     str(state["work"] / "preview" / "subtitle-original.png")],timeout=120)
            except MediaError:
                pass
            report={"mode":"none","soft_subtitles_removed":True,"hard_subtitles_processed":False,"warnings":[]}
        else:
            def subtitle_progress(done,total,offset,weight):
                fraction=offset+weight*min(1,done/max(1,total))
                self._update_progress(state["work"].name,"subtitle_processing",fraction*100,
                                      (STAGES.index("subtitle_processing")+fraction)/len(STAGES)*100)
            boxes, warnings=detect_boxes(source,options.subtitle_regions,state["work"] / "ocr-trace.json",self._checkpoint,
                                         lambda done,total:subtitle_progress(done,total,0,.8))
            fps=float(Fraction(str(state['probe'].get('fps') or 25)))
            boxes+=manual_intervals([m.model_dump() for m in options.temporal_masks],fps)
            video=state["work"] / "repaired-silent.mp4"
            source_hash=_file_digest(source)
            previous_path=state["work"] / "subtitle-report.json"
            try:
                previous=json.loads(previous_path.read_text(encoding="utf-8")) if previous_path.exists() else {}
            except (OSError,json.JSONDecodeError):
                previous={}
            previous_video=Path(previous.get("output_video") or video)
            same_regions=json.dumps(previous.get("regions"),sort_keys=True)==json.dumps(boxes,sort_keys=True)
            if (previous.get('quality_version')==VERSION and previous.get("source_sha256")==source_hash and previous.get("mode")==options.subtitle_mode
                    and same_regions and previous_video.is_file()
                    and previous.get("repair_sha256")==_file_digest(previous_video)):
                keys=("width","height","fps","frames_processed","masked_frames","unmasked_frames","regions",
                      "mask_applied","output_video","technique","patch_roi")
                result={key:previous[key] for key in keys}
                result["repair_cache_reused"]=True
                subtitle_progress(1,1,.8,.2)
            else:
                result=redact_video(source,video,boxes,state["work"] / "preview",options.subtitle_mode,self._checkpoint,
                                    lambda done,total:subtitle_progress(done,total,.8,.2))
                result["repair_cache_reused"]=False
            video=Path(result["output_video"])
            report={"mode":options.subtitle_mode,**result,"manual_search_regions":options.subtitle_regions,'quality_version':VERSION,
                    'temporal_manual_masks':[m.model_dump() for m in options.temporal_masks],
                    "source_sha256":source_hash,"repair_sha256":_file_digest(video),
                    "soft_subtitles_removed":True,"hard_subtitles_processed":bool(boxes),"warnings":warnings}
        margin=readable_caption_margin(int(state["probe"]["height"]),report.get("regions",[]),options.subtitle_margin_v)
        write_ass(state["segments"],ass,options.subtitle_font_size,margin)
        report["requested_subtitle_margin_v"]=options.subtitle_margin_v
        report["effective_subtitle_margin_v"]=margin
        if margin>options.subtitle_margin_v:
            report["caption_placement_note"]="English captions are placed above the detected source subtitle band for readability."
        preview_video=source if report.get('patch_roi') else video
        if state["segments"]:
            first=next((s for s in state["segments"] if s.get("translated_text")),None)
            if first:
                preview_path=state["work"] / "preview" / "english-subtitle.png"
                preview_path.parent.mkdir(parents=True,exist_ok=True)
                timestamp=max(0.0,float(first["start"]))
                try:
                    # Input seeking resets frame PTS to zero; restore the seek offset so
                    # ASS events at their source timeline still appear in this preview.
                    ass_filter=f"setpts=PTS+{timestamp:.3f}/TB,ass={ass.as_posix()}"
                    if report.get('patch_roi'):
                        x,y,_w,_h=report['patch_roi']
                        preview_inputs=['-ss',f'{timestamp:.3f}','-i',str(source),'-ss',f'{timestamp:.3f}','-i',str(video)]
                        preview_filter=['-filter_complex',f'[0:v][1:v]overlay={x}:{y},{ass_filter}']
                    else:
                        preview_inputs=['-ss',f'{timestamp:.3f}','-i',str(preview_video)]
                        preview_filter=['-vf',ass_filter]
                    run([settings.ffmpeg,"-y","-v","error",*preview_inputs,*preview_filter,
                         "-frames:v","1","-update","1",str(preview_path)],timeout=120)
                    report["english_subtitle_preview"]=str(preview_path)
                except MediaError as exc:
                    warnings.append(f"English subtitle still preview could not be rendered: {exc}")
                    report["warnings"]=warnings
        path=state["work"] / "subtitle-report.json"
        _dump(path,report)
        return {"subtitle_file":str(ass),"subtitle_srt":str(srt),"subtitle_report":str(path),"subtitle_video":str(video),
                "subtitle_preview":str(state["work"] / "preview")}

    def _stage_render(self,state):
        options=state["options"]
        work=state["work"]
        report=json.loads((work / "subtitle-report.json").read_text(encoding="utf-8"))
        bed=work / "background.wav"
        dub=work / "dub.wav"
        mixed=work / "mixed.wav"
        duration=float(state["probe"]["duration"])
        bg_db=options.background_gain_db
        dlg_db=options.dialogue_gain_db
        run([settings.ffmpeg,"-y","-v","error","-i",str(bed),"-i",str(dub),"-filter_complex",
             f"[0:a]volume={bg_db}dB[bg];[1:a]volume={dlg_db}dB[dlg];[bg][dlg]amix=inputs=2:duration=longest:dropout_transition=0:normalize=0,alimiter=limit=0.94:level=0:latency=1[out]",
             "-map","[out]","-ar",str(SAMPLE_RATE),"-c:a","pcm_s16le",str(mixed)],timeout=None)
        output=settings.data_dir / "output" / f"{state['work'].name}.mp4"
        subtitle=work / "english-subtitles.ass"
        # Job-generated filenames are UUIDs under the app data root; all arguments remain separate.
        patch=report.get('patch_roi')
        if patch:
            x,y,_w,_h=patch
            inputs=['-i',str(state['source']),'-i',str(report['output_video']),'-i',str(mixed)]
            filters=['-filter_complex',f'[0:v][1:v]overlay={x}:{y},ass={subtitle.as_posix()}[video]','-map','[video]','-map','2:a:0']
        else:
            inputs=['-i',str(report.get('output_video') or state['source']),'-i',str(mixed)]
            filters=['-map','0:v:0','-map','1:a:0','-vf',f'ass={subtitle.as_posix()}']
        run([settings.ffmpeg,"-y","-v","error",*inputs,*filters,"-c:v","libx264","-preset","veryfast","-crf","20",
             "-pix_fmt","yuv420p","-c:a","aac","-b:a","192k","-movflags","+faststart","-t",f"{duration:.3f}",str(output)],timeout=None)
        if not output.is_file() or output.stat().st_size < 1024:
            raise RuntimeError("FFmpeg did not create a valid MP4 output")
        final_probe=probe_media(output)
        report["final_probe"]={"duration":final_probe["duration"],"width":final_probe["width"],"height":final_probe["height"],
                                "fps":final_probe["fps"],"has_audio":final_probe["has_audio"],
                                "subtitle_streams":len(final_probe["subtitle_streams"])}
        _dump(work / "subtitle-report.json",report)
        return {"video":str(output),"mixed_audio":str(mixed),"subtitle_report":str(work / "subtitle-report.json")}
