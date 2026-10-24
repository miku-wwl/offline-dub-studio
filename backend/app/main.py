from __future__ import annotations

import json
import mimetypes
import math
import os
import subprocess
import shutil
import tempfile
import threading
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from .config import effective_cpu_count, settings
from .db import Database, now
from .domain import JobOptions, SegmentEdit, SpeakerEdit, TemporalMask, TranslationSettings
from .manager import JobManager
from .media import MediaError, probe_media, require_tools
from .models import MODEL_PACKS, initialize, list_packs
from .providers import VOICE_CHOICES
from .pipeline import STAGES


settings.prepare()
db=Database(settings.db_path)
manager=JobManager(db)
model_ops: dict[str,dict[str,Any]]={}
model_lock=threading.Lock()
model_init_lock=threading.Lock()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    manager.start()
    yield
    manager.stop()


app=FastAPI(title="Offline Dub Studio",version="0.1.0",description="Local CPU video dubbing service",lifespan=lifespan)


class CreateJob(BaseModel):
    asset_id: str
    options: JobOptions = Field(default_factory=JobOptions)


class ImportMedia(BaseModel):
    filename: str


class VoiceAssignments(BaseModel):
    assignments: dict[str,SpeakerEdit]


class RetryStage(BaseModel):
    stage: str


class SubtitleRegions(BaseModel):
    regions: list[tuple[int,int,int,int]]


class TemporalMasks(BaseModel):
    masks: list[TemporalMask] = Field(max_length=1000)


def _validate_video_regions(options, width, height, duration):
    for mask in options.temporal_masks:
        if mask.end_time>duration or mask.x+mask.width>width or mask.y+mask.height>height:
            raise HTTPException(422,'Temporal mask must fit within the video dimensions and duration.')
    for x,y,w,h in options.subtitle_regions:
        if x<0 or y<0 or w<2 or h<2 or x+w>width or y+h>height:
            raise HTTPException(422,'Subtitle search region must fit inside the video.')


@app.get('/api/v1/project/translation')
def project_translation():
    path=settings.data_dir / 'project-translation.json'
    return TranslationSettings.model_validate_json(path.read_text()) if path.exists() else TranslationSettings()


@app.put('/api/v1/project/translation')
def update_project_translation(request:TranslationSettings):
    (settings.data_dir / 'project-translation.json').write_text(request.model_dump_json(indent=2),encoding='utf-8')
    return request


@app.get("/api/v1/health")
@app.get("/healthz")
def health():
    return {"status":"ok","service":"offline-dub-studio","version":"0.1.0"}


@app.get("/api/v1/diagnostics")
def diagnostics():
    usage=shutil.disk_usage(settings.data_dir)
    return {"tools":require_tools(),"cpu_count":effective_cpu_count(),
            "data_free_bytes":usage.free,"models_dir_ready":settings.models_dir.exists(),
            "offline_inference":settings.offline,"models":list_packs(),
            "storage":{"data":str(settings.data_dir),"models":str(settings.models_dir)}}


@app.get("/api/v1/models")
def models():
    with model_lock:
        operations={key:value.copy() for key,value in model_ops.items()}
    return {"packs":list_packs(),"operations":operations,"offline_inference":settings.offline}


@app.get("/api/v1/voices")
def voices():
    return {"voices":VOICE_CHOICES}


@app.post("/api/v1/models/{pack_id}/initialize",status_code=202)
def initialize_model(pack_id:str):
    if pack_id not in MODEL_PACKS:
        raise HTTPException(404,"Model pack not found")
    if db.one("SELECT id FROM jobs WHERE status IN ('queued','running','cancelling') LIMIT 1"):
        raise HTTPException(409,"Wait for active conversion jobs to finish before initializing another model.")
    with model_lock:
        current=model_ops.get(pack_id)
        if current and current.get("status")=="running":
            return {"id":pack_id,"status":"running"}
        model_ops[pack_id]={"status":"running","started_at":now(),"error":None}
    def run_init():
        with model_init_lock:
            try:
                result=initialize(pack_id)
                with model_lock:
                    model_ops[pack_id]={"status":"ready","started_at":model_ops[pack_id]["started_at"],"finished_at":now(),"result":result}
            except Exception as exc:
                with model_lock:
                    model_ops[pack_id]={"status":"failed","started_at":model_ops[pack_id]["started_at"],"finished_at":now(),"error":str(exc)[:1200]}
    threading.Thread(target=run_init,name=f"model-init-{pack_id}",daemon=True).start()
    return {"id":pack_id,"status":"running"}


def _asset(asset_id:str):
    row=db.one("SELECT * FROM media WHERE id=?",(asset_id,))
    if not row or not Path(row["path"]).is_file():
        raise HTTPException(404,"Media asset not found")
    row["probe"]=json.loads(row.pop("probe_json"))
    return row


def _store_media(path:Path,display_name:str,media_id:str|None=None,*,probe:dict|None=None)->dict:
    """Register media. Validation never grants ownership of the supplied path."""
    try:
        probe=probe if probe is not None else probe_media(path)
    except MediaError as exc:
        raise HTTPException(422,str(exc)) from exc
    media_id=media_id or str(uuid.uuid4())
    size=path.stat().st_size
    db.execute("INSERT INTO media(id,path,display_name,bytes,probe_json,created_at) VALUES(?,?,?,?,?,?)",
               (media_id,str(path),display_name,size,json.dumps(probe),now()))
    return {"id":media_id,"display_name":display_name,"bytes":size,
            "duration":probe["duration"],"width":probe["width"],"height":probe["height"],
            "has_audio":probe["has_audio"],"subtitle_streams":len(probe["subtitle_streams"])}


def _publish_media(temp:Path,display_name:str)->dict:
    """Publish an app-owned snapshot without replacing an existing asset."""
    media_id=str(uuid.uuid4())
    destination=settings.uploads_dir / f"{media_id}{Path(display_name).suffix.lower()}"
    try:
        probe=probe_media(temp)
    except MediaError as exc:
        raise HTTPException(422,str(exc)) from exc
    # link() is atomic and fails if the destination exists. This link is to the
    # private copied upload, never to the user's inbox file.
    os.link(temp,destination)
    try:
        return _store_media(destination,display_name,media_id,probe=probe)
    except BaseException:
        destination.unlink(missing_ok=True)
        raise


@app.post("/api/v1/media/upload",status_code=201)
async def upload_media(file:UploadFile=File(...)):
    name=Path(file.filename or "video.mp4").name
    suffix=Path(name).suffix.lower()
    if suffix not in {".mp4",".m4v",".mov",".mkv",".webm"}:
        raise HTTPException(415,"Choose a video file (MP4, M4V, MOV, MKV, or WebM).")
    fd,temp_name=tempfile.mkstemp(prefix="upload-",suffix=suffix+".uploading",dir=settings.uploads_dir)
    temp=Path(temp_name)
    size=0
    try:
        with os.fdopen(fd,"wb") as out:
            while chunk:=await file.read(1024*1024):
                size+=len(chunk)
                if size>settings.max_upload_bytes:
                    raise HTTPException(413,"Upload exceeds the configured size limit.")
                out.write(chunk)
            out.flush()
            os.fsync(out.fileno())
        if size==0:
            raise HTTPException(400,"The uploaded file is empty.")
        return _publish_media(temp,name)
    finally:
        temp.unlink(missing_ok=True)
        await file.close()


@app.get("/api/v1/media/inbox")
def inbox_media():
    rows=[]
    for path in sorted(settings.inbox_dir.iterdir(),key=lambda p:p.name.casefold()):
        if path.is_file() and path.suffix.lower() in {".mp4",".m4v",".mov",".mkv",".webm"}:
            rows.append({"filename":path.name,"bytes":path.stat().st_size})
    return {"files":rows}


@app.post("/api/v1/media/import",status_code=201)
def import_media(request:ImportMedia):
    filename=request.filename
    if not filename or Path(filename).name!=filename or filename in {".",".."}:
        raise HTTPException(400,"Choose a direct child of the mounted input folder.")
    candidate=settings.inbox_dir / filename
    try:
        resolved=candidate.resolve(strict=True)
    except OSError as exc:
        raise HTTPException(404,"File not found in the mounted input folder.") from exc
    if resolved.parent!=settings.inbox_dir.resolve() or not resolved.is_file():
        raise HTTPException(400,"Only regular files directly inside the mounted input folder can be imported.")
    if resolved.stat().st_size>settings.max_inbox_bytes:
        raise HTTPException(413,"Inbox file exceeds the configured size limit.")
    if resolved.suffix.lower() not in {".mp4",".m4v",".mov",".mkv",".webm"}:
        raise HTTPException(415,"Choose a video file (MP4, M4V, MOV, MKV, or WebM).")
    if shutil.disk_usage(settings.uploads_dir).free<resolved.stat().st_size+64*1024**2:
        raise HTTPException(507,"Not enough disk space for an independent media snapshot. Free space in the data volume and retry; the inbox source is unchanged.")
    fd,temp_name=tempfile.mkstemp(prefix="import-",suffix=resolved.suffix+".uploading",dir=settings.uploads_dir)
    temp=Path(temp_name)
    try:
        with os.fdopen(fd,"wb") as out,resolved.open("rb") as source:
            before=os.fstat(source.fileno())
            shutil.copyfileobj(source,out,length=1024*1024)
            after=os.fstat(source.fileno())
            if (before.st_size,before.st_mtime_ns,before.st_ctime_ns)!=(after.st_size,after.st_mtime_ns,after.st_ctime_ns):
                raise HTTPException(409,"The inbox file changed during import. Wait for copying to finish and retry.")
            out.flush()
            os.fsync(out.fileno())
        return _publish_media(temp,filename)
    finally:
        temp.unlink(missing_ok=True)


@app.post("/api/v1/jobs",status_code=201)
def create_job(request:CreateJob):
    if request.options.source_language!="zh" or request.options.target_language!="en":
        raise HTTPException(501,"Only Chinese-to-English conversion is available in this release.")
    required=["asr-tiny" if request.options.profile=="cpu-lite" else "asr-small",
              "translation-zh-en","tts-kokoro-en","separation-htdemucs"]
    ready={pack["id"]:pack["ready"] for pack in list_packs()}
    missing=[pack_id for pack_id in required if not ready.get(pack_id,False)]
    if missing:
        raise HTTPException(409,"Initialize the required local model packs before conversion: "+", ".join(missing))
    media=_asset(request.asset_id)
    media_probe=media['probe']
    _validate_video_regions(request.options,media_probe['width'],media_probe['height'],media_probe['duration'])
    request.options.translation_glossary={**project_translation().glossary,**request.options.translation_glossary}
    job_id=str(uuid.uuid4())
    work=settings.jobs_dir / job_id
    work.mkdir(parents=True,exist_ok=True)
    options=request.options.model_dump()
    db.execute("INSERT INTO jobs(id,input_path,display_name,status,stage,progress,created_at,updated_at,options_json) "
               "VALUES(?,?,?,'queued','queued',0,?,?,?)",
               (job_id,media["path"],media["display_name"],now(),now(),json.dumps(options)))
    for speaker,voice in options["voice_assignments"].items():
        db.execute("INSERT OR REPLACE INTO speakers(job_id,speaker_id,voice_id) VALUES(?,?,?)",(job_id,speaker,voice))
    db.log(job_id,"info","Job queued. Model inference stays local to this container.")
    manager.enqueue(job_id)
    return {"id":job_id,"status":"queued","created_at":now()}


def _job_detail(job_id:str)->dict:
    job=db.job(job_id)
    if not job:
        raise HTTPException(404,"Job not found")
    work=settings.jobs_dir / job_id
    transcript=work / "transcript.json"
    job["transcript"]=json.loads(transcript.read_text(encoding="utf-8"))["segments"] if transcript.exists() else []
    job["speakers"]=db.query("SELECT speaker_id,voice_id,label FROM speakers WHERE job_id=? ORDER BY speaker_id",(job_id,))
    job["logs"]=db.query("SELECT timestamp,level,message FROM logs WHERE job_id=? ORDER BY id DESC LIMIT 250",(job_id,))[::-1]
    def elapsed(start:str|None,end:str|None=None)->float|None:
        if not start:
            return None
        try:
            start_at=datetime.fromisoformat(start)
            end_at=datetime.fromisoformat(end) if end else datetime.now(timezone.utc)
            return max(0.0,(end_at-start_at).total_seconds())
        except (TypeError,ValueError):
            return None
    terminal=job["status"] in {"completed","completed_with_warnings","failed","cancelled","interrupted"}
    job["elapsed_seconds"]=elapsed(job["created_at"],job["updated_at"] if terminal else None)
    current_stage=next((stage for stage in job["stages"] if stage["name"]==job["stage"]),None)
    job["current_stage_elapsed_seconds"]=elapsed(
        current_stage["started_at"],current_stage["finished_at"] if current_stage and current_stage["status"]=="completed" else None
    ) if current_stage else None
    output=settings.data_dir / "output" / f"{job_id}.mp4"
    job["download_url"]=f"/api/v1/jobs/{job_id}/artifacts/video" if job["status"].startswith("completed") and output.is_file() else None
    report=work / "subtitle-report.json"
    job["subtitle_report"]=json.loads(report.read_text(encoding="utf-8")) if report.exists() else None
    inspection=work / "inspection.json"
    job["media_info"]=json.loads(inspection.read_text(encoding="utf-8")) if inspection.exists() else None
    return job


@app.get("/api/v1/jobs")
def list_jobs():
    rows=db.query("SELECT id,display_name,status,stage,progress,created_at,updated_at,error FROM jobs ORDER BY created_at DESC LIMIT 100")
    for row in rows:
        output=settings.data_dir / "output" / f"{row['id']}.mp4"
        row["download_url"]=f"/api/v1/jobs/{row['id']}/artifacts/video" if row["status"].startswith("completed") and output.is_file() else None
    return {"jobs":rows}


@app.get("/api/v1/jobs/{job_id}")
def get_job(job_id:str):
    return _job_detail(job_id)


@app.post("/api/v1/jobs/{job_id}/cancel")
def cancel_job(job_id:str):
    row=db.one("SELECT status FROM jobs WHERE id=?",(job_id,))
    if not row:
        raise HTTPException(404,"Job not found")
    if row["status"] in {"completed","completed_with_warnings","failed","cancelled"}:
        raise HTTPException(409,"This job is not running.")
    if row["status"]=="queued":
        db.execute("UPDATE jobs SET cancel_requested=1,status='cancelled',stage='cancelled',updated_at=?,error='Cancelled by user' WHERE id=?",(now(),job_id))
        db.log(job_id,"warning","Queued conversion cancelled before starting.")
        return {"id":job_id,"status":"cancelled"}
    db.execute("UPDATE jobs SET cancel_requested=1,status='cancelling',updated_at=? WHERE id=?",(now(),job_id))
    db.log(job_id,"warning","Cancellation requested; it will be honored at the next safe checkpoint.")
    return {"id":job_id,"status":"cancelling"}


@app.post("/api/v1/jobs/{job_id}/resume")
def resume_job(job_id:str):
    row=db.one("SELECT status FROM jobs WHERE id=?",(job_id,))
    if not row:
        raise HTTPException(404,"Job not found")
    if row["status"] not in {"interrupted","failed","cancelled"}:
        raise HTTPException(409,"Only interrupted, failed, or cancelled jobs can be resumed.")
    db.execute("UPDATE jobs SET status='queued',stage='queued',updated_at=?,error=NULL,cancel_requested=0 WHERE id=?",(now(),job_id))
    db.execute("UPDATE stages SET status='pending',error=NULL WHERE job_id=? AND status IN ('failed','interrupted','running')",(job_id,))
    db.log(job_id,"info","Resume queued. Successful previous stage artifacts will be reused.")
    manager.enqueue(job_id)
    return {"id":job_id,"status":"queued"}


@app.post("/api/v1/jobs/{job_id}/approve-subtitles")
def approve_subtitles(job_id:str):
    row=db.one("SELECT status,options_json FROM jobs WHERE id=?",(job_id,))
    if not row:
        raise HTTPException(404,"Job not found")
    if row["status"]!="awaiting_review":
        raise HTTPException(409,"Subtitle review is available after the preview stage completes.")
    options=json.loads(row["options_json"])
    options["subtitle_review_approved"]=True
    db.execute("UPDATE jobs SET options_json=?,status='queued',stage='queued',updated_at=? WHERE id=?",
               (json.dumps(options),now(),job_id))
    db.log(job_id,"info","User approved the subtitle preview; final export queued.")
    manager.enqueue(job_id)
    return {"id":job_id,"status":"queued"}


@app.post("/api/v1/jobs/{job_id}/retry-stage")
def retry_stage(job_id:str,request:RetryStage):
    row=db.one("SELECT status,options_json FROM jobs WHERE id=?",(job_id,))
    if not row:
        raise HTTPException(404,"Job not found")
    if row["status"] in {"running","queued","cancelling"}:
        raise HTTPException(409,"Wait for active processing to stop before retrying a stage.")
    if request.stage not in STAGES:
        raise HTTPException(422,"Choose a known pipeline stage: "+", ".join(STAGES))
    options=json.loads(row["options_json"])
    if STAGES.index(request.stage)<=STAGES.index("translate"):
        options["transcript_review_approved"]=False
        db.execute("UPDATE jobs SET options_json=? WHERE id=?",(json.dumps(options),job_id))
    _requeue_edited_job(job_id,STAGES[STAGES.index(request.stage):],f"Retry requested from {request.stage}; successful earlier stage artifacts are retained.")
    return {"id":job_id,"status":"queued"}


@app.post("/api/v1/jobs/{job_id}/approve-transcript")
def approve_transcript(job_id:str):
    row=db.one("SELECT status,options_json FROM jobs WHERE id=?",(job_id,))
    if not row:
        raise HTTPException(404,"Job not found")
    if row["status"]!="awaiting_transcript_review":
        raise HTTPException(409,"Transcript approval is available after translation completes.")
    options=json.loads(row["options_json"])
    options["transcript_review_approved"]=True
    db.execute("UPDATE jobs SET options_json=?,status='queued',stage='queued',updated_at=? WHERE id=?",
               (json.dumps(options),now(),job_id))
    db.log(job_id,"info","Transcript and speaker mapping approved for local voice generation; subjective voice identity still requires listening.")
    manager.enqueue(job_id)
    return {"id":job_id,"status":"queued"}


@app.put("/api/v1/jobs/{job_id}/subtitle-regions")
def update_subtitle_regions(job_id:str,request:SubtitleRegions):
    row=db.one("SELECT status,options_json FROM jobs WHERE id=?",(job_id,))
    if not row:
        raise HTTPException(404,"Job not found")
    if row["status"] in {"running","queued","cancelling"}:
        raise HTTPException(409,"Wait until the subtitle preview is ready before adjusting regions.")
    inspection=settings.jobs_dir / job_id / "inspection.json"
    if not inspection.exists():
        raise HTTPException(409,"Video inspection is not available yet.")
    info=json.loads(inspection.read_text(encoding="utf-8"))
    width,height=int(info["width"]),int(info["height"])
    for x,y,w,h in request.regions:
        if x<0 or y<0 or w<2 or h<2 or x+w>width or y+h>height:
            raise HTTPException(422,"Subtitle region must fit inside the source video's dimensions.")
    options=json.loads(row["options_json"])
    options["subtitle_regions"]=[list(region) for region in request.regions]
    options["subtitle_review_approved"]=False
    db.execute("UPDATE jobs SET options_json=? WHERE id=?",(json.dumps(options),job_id))
    _requeue_edited_job(job_id,["subtitle_processing","render"],"Subtitle regions updated; processing a new preview for review.")
    return {"id":job_id,"status":"queued"}




@app.put("/api/v1/jobs/{job_id}/transcript")
def edit_transcript(job_id:str,segments:list[SegmentEdit]):
    job=db.one("SELECT status FROM jobs WHERE id=?",(job_id,))
    if not job:
        raise HTTPException(404,"Job not found")
    if job["status"] in {"running","queued","cancelling"}:
        raise HTTPException(409,"Wait for the current processing stage to finish before editing.")
    ids=[seg.id for seg in segments]
    if len(ids)!=len(set(ids)):
        raise HTTPException(422,"Transcript segment IDs must be unique.")
    duration=0.0
    inspection=settings.jobs_dir / job_id / "inspection.json"
    if inspection.exists():
        duration=float(json.loads(inspection.read_text(encoding="utf-8"))["duration"])
    for segment in segments:
        if segment.end<=segment.start or (duration and segment.end>duration+0.2):
            raise HTTPException(422,f"Segment {segment.id} has an invalid time interval.")
    path=settings.jobs_dir / job_id / "transcript.json"
    payload={"segments":[s.model_dump() for s in segments],"provider":"user-edited"}
    source_changed=False
    if path.exists():
        old=json.loads(path.read_text(encoding="utf-8"))
        previous={s['id']:s for s in old.get('segments',[])}
        payload.update(old)
        payload["segments"]=[s.model_dump() for s in segments]
        from hashlib import sha256
        for row in payload['segments']:
            prior=previous.get(row['id'],{})
            changed_source=row['source_text']!=prior.get('source_text')
            source_changed=source_changed or changed_source
            changed_english=any(row.get(k)!=prior.get(k) for k in ('translated_text','short_translation'))
            if any(row.get(k)!=prior.get(k) for k in ('source_text','translated_text','short_translation')):
                row['translation_provenance']={**prior.get('translation_provenance',{}),
                    'manual_override':{'full':row['translated_text'],'short':row.get('short_translation'),
                        'previous_text':prior.get('translated_text'),'edited_at':now(),'actor':'local-review-client'},
                    'source_sha256':sha256(row['source_text'].encode()).hexdigest(),'human_approved':False}
                if changed_source and not changed_english:
                    row['translation_provenance'].pop('manual_override',None)
                    row['translation_provenance']['source_edit']={'before':prior.get('source_text'),'after':row['source_text'],'edited_at':now()}
            else:
                row['translation_provenance']=prior.get('translation_provenance',{})
        payload["edited_at"]=now()
    path.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    default_voices=["af_heart","af_bella","am_adam","af_nicole","am_michael"]
    speaker_ids=list(dict.fromkeys(s.speaker_id or "speaker_1" for s in segments))
    existing={r["speaker_id"]:r["voice_id"] for r in db.query("SELECT speaker_id,voice_id FROM speakers WHERE job_id=?",(job_id,))}
    for index,speaker_id in enumerate(speaker_ids):
        db.execute("INSERT INTO speakers(job_id,speaker_id,voice_id) VALUES(?,?,?) ON CONFLICT(job_id,speaker_id) DO NOTHING",
                   (job_id,speaker_id,existing.get(speaker_id,default_voices[index%len(default_voices)])))
    for speaker_id in set(existing)-set(speaker_ids):
        db.execute("DELETE FROM speakers WHERE job_id=? AND speaker_id=?",(job_id,speaker_id))
    if source_changed:
        row=db.one('SELECT options_json FROM jobs WHERE id=?',(job_id,))
        options=json.loads(row['options_json'])
        options['transcript_review_approved']=False
        db.execute('UPDATE jobs SET options_json=? WHERE id=?',(json.dumps(options),job_id))
    _requeue_edited_job(job_id,(["translate"] if source_changed else [])+["synthesize","subtitle_processing","render"],"Transcript edits saved; affected translation/audio/subtitle stages queued.")
    return _job_detail(job_id)


@app.put('/api/v1/jobs/{job_id}/temporal-masks')
def update_temporal_masks(job_id:str, request:TemporalMasks):
    row=db.one('SELECT status,options_json FROM jobs WHERE id=?',(job_id,))
    if not row:
        raise HTTPException(404,'Job not found')
    if row['status'] in {'running','queued','cancelling'}:
        raise HTTPException(409,'Wait for processing to stop before editing masks.')
    inspection=settings.jobs_dir / job_id / 'inspection.json'
    if not inspection.exists():
        raise HTTPException(409,'Video inspection is not available.')
    info=json.loads(inspection.read_text())
    options=JobOptions.model_validate_json(row['options_json'])
    options.temporal_masks=request.masks
    _validate_video_regions(options,info['width'],info['height'],info['duration'])
    options.subtitle_review_approved=False
    db.execute('UPDATE jobs SET options_json=? WHERE id=?',(options.model_dump_json(),job_id))
    _requeue_edited_job(job_id,['subtitle_processing','render'],'Explicit time-bounded masks updated; new preview required.')
    return {'id':job_id,'status':'queued'}


@app.put("/api/v1/jobs/{job_id}/speakers")
def edit_speakers(job_id:str,request:VoiceAssignments):
    job=db.one("SELECT status FROM jobs WHERE id=?",(job_id,))
    if not job:
        raise HTTPException(404,"Job not found")
    if job["status"] in {"running","queued","cancelling"}:
        raise HTTPException(409,"Wait for the current processing stage to finish before editing.")
    from .providers import VALID_VOICES
    for speaker,edit in request.assignments.items():
        if edit.voice_id not in VALID_VOICES:
            raise HTTPException(422,f"Unsupported voice ID for {speaker}.")
        db.execute("INSERT INTO speakers(job_id,speaker_id,voice_id) VALUES(?,?,?) ON CONFLICT(job_id,speaker_id) DO UPDATE SET voice_id=excluded.voice_id",
                   (job_id,speaker,edit.voice_id))
    _requeue_edited_job(job_id,["synthesize","render"],"Speaker voice assignments saved; TTS and final render queued.")
    return _job_detail(job_id)


def _requeue_edited_job(job_id:str,stages:list[str],message:str):
    job=db.one("SELECT status,options_json FROM jobs WHERE id=?",(job_id,))
    if job["status"] in {"interrupted","failed","cancelled"}:
        # A downstream edit is an explicit retry and retains successful upstream artifacts.
        pass
    for stage in stages:
        db.execute("UPDATE stages SET status='pending',progress=0,error=NULL WHERE job_id=? AND name=?",(job_id,stage))
    if "subtitle_processing" in stages:
        options=json.loads(job["options_json"])
        options["subtitle_review_approved"]=False
        db.execute("UPDATE jobs SET options_json=? WHERE id=?",(json.dumps(options),job_id))
    db.execute("UPDATE jobs SET status='queued',stage='queued',progress=0,updated_at=?,error=NULL,cancel_requested=0 WHERE id=?",(now(),job_id))
    db.log(job_id,"info",message)
    manager.enqueue(job_id)


@app.get("/api/v1/jobs/{job_id}/artifacts/video")
def download_video(job_id:str):
    job=db.one("SELECT id,status FROM jobs WHERE id=?",(job_id,))
    if not job:
        raise HTTPException(404,"Job not found")
    path=settings.data_dir / "output" / f"{job_id}.mp4"
    if not job["status"].startswith("completed") or not path.is_file():
        raise HTTPException(404,"The output MP4 is not ready yet.")
    return FileResponse(path,media_type="video/mp4",filename=f"offline-dub-{job_id[:8]}.mp4")


@app.get("/api/v1/jobs/{job_id}/artifacts/audio")
def download_audio(job_id:str):
    if not db.one("SELECT id FROM jobs WHERE id=?",(job_id,)):
        raise HTTPException(404,"Job not found")
    path=settings.jobs_dir / job_id / "mixed.wav"
    if not path.is_file():
        raise HTTPException(404,"The mixed audio is not ready yet.")
    return FileResponse(path,media_type="audio/wav",filename=f"offline-dub-{job_id[:8]}-audio.wav")


@app.get("/api/v1/jobs/{job_id}/artifacts/original")
def original_video(job_id:str):
    row=db.one("SELECT input_path FROM jobs WHERE id=?",(job_id,))
    if not row:
        raise HTTPException(404,"Job not found")
    path=Path(row["input_path"])
    if not path.is_file():
        raise HTTPException(404,"The original video is no longer available.")
    return FileResponse(path,media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream")


@app.get("/api/v1/jobs/{job_id}/preview/{name}")
def preview(job_id:str,name:str):
    if not db.one("SELECT id FROM jobs WHERE id=?",(job_id,)):
        raise HTTPException(404,"Job not found")
    if name not in {"subtitle-original.png","subtitle-mask.png","subtitle-repaired.png","english-subtitle.png"}:
        raise HTTPException(404,"Preview not found")
    path=settings.jobs_dir / job_id / "preview" / name
    if not path.is_file():
        raise HTTPException(404,"Preview is not ready")
    return FileResponse(path,media_type="image/png")


@app.get('/api/v1/jobs/{job_id}/preview-frame')
def preview_frame(job_id:str,time:float=0):
    row=db.one('SELECT input_path FROM jobs WHERE id=?',(job_id,))
    if not row:
        raise HTTPException(404,'Job not found')
    info=probe_media(Path(row['input_path']))
    if not math.isfinite(time) or time<0 or time>=info['duration']:
        raise HTTPException(422,'Preview time must be within the source video.')
    frame=subprocess.run([settings.ffmpeg,'-v','error','-ss',str(time),'-i',row['input_path'],
        '-frames:v','1','-f','image2pipe','-c:v','png','pipe:1'],capture_output=True,timeout=30)
    if frame.returncode or not frame.stdout:
        raise HTTPException(422,'Could not decode the requested source frame.')
    return Response(frame.stdout,media_type='image/png')


@app.get("/api/v1/jobs/{job_id}/logs")
def job_logs(job_id:str):
    if not db.one("SELECT id FROM jobs WHERE id=?",(job_id,)):
        raise HTTPException(404,"Job not found")
    return {"logs":db.query("SELECT timestamp,level,message FROM logs WHERE job_id=? ORDER BY id",(job_id,))}


STATIC_DIR=Path(__file__).resolve().parents[2] / "frontend" / "dist"
if STATIC_DIR.is_dir():
    @app.get("/{path:path}",include_in_schema=False)
    def frontend(path:str):
        candidate=(STATIC_DIR / path).resolve()
        try:
            candidate.relative_to(STATIC_DIR.resolve())
        except ValueError:
            raise HTTPException(404,"Not found")
        return FileResponse(candidate if candidate.is_file() else STATIC_DIR / "index.html")
