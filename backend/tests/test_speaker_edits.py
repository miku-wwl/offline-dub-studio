import importlib
import json

from app.config import Settings
from app.db import Database, now
from app.domain import SegmentEdit


def test_speaker_edit_keeps_timestamps_and_invalidates_generated_voices(tmp_path,monkeypatch):
    api=importlib.import_module("app.main")
    config=Settings(data_dir=tmp_path / "data",models_dir=tmp_path / "models")
    config.prepare()
    database=Database(config.db_path)
    database.init()
    monkeypatch.setattr(api,"settings",config)
    monkeypatch.setattr(api,"db",database)
    queued=[]
    monkeypatch.setattr(api.manager,"enqueue",queued.append)
    work=config.jobs_dir / "speaker-edit"
    work.mkdir()
    original={"id":"s1","start":1.25,"end":3.75,"source_text":"你好","translated_text":"Hello.","speaker_id":"speaker_1"}
    (work / "transcript.json").write_text(json.dumps({"segments":[original]}),encoding="utf-8")
    database.execute("INSERT INTO jobs(id,input_path,display_name,status,stage,created_at,updated_at,options_json) VALUES(?,?,?,?,?,?,?,?)",
                     (work.name,"fixture.mp4","fixture.mp4","awaiting_review","awaiting_review",now(),now(),"{}"))
    for stage in ["transcribe","translate","synthesize","subtitle_processing","render"]:
        database.execute("INSERT INTO stages(job_id,name,status,progress) VALUES(?,?,?,?)",(work.name,stage,"completed",100))
    edited=SegmentEdit(**{**original,"speaker_id":"speaker_2"})
    api.edit_transcript(work.name,[edited])
    saved=json.loads((work / "transcript.json").read_text(encoding="utf-8"))["segments"][0]
    assert (saved["start"],saved["end"])==(1.25,3.75)
    assert saved["speaker_id"]=="speaker_2"
    stages={row["name"]:row["status"] for row in database.job(work.name)["stages"]}
    assert stages=={"transcribe":"completed","translate":"completed","synthesize":"pending","subtitle_processing":"pending","render":"pending"}
    assert queued==[work.name]


def test_stage_retry_preserves_successful_separation_and_resets_review(tmp_path,monkeypatch):
    api=importlib.import_module("app.main")
    config=Settings(data_dir=tmp_path / "data",models_dir=tmp_path / "models")
    config.prepare()
    database=Database(config.db_path)
    database.init()
    monkeypatch.setattr(api,"settings",config)
    monkeypatch.setattr(api,"db",database)
    queued=[]
    monkeypatch.setattr(api.manager,"enqueue",queued.append)
    options={"transcript_review_required":True,"transcript_review_approved":True,"subtitle_review_approved":True}
    database.execute("INSERT INTO jobs(id,input_path,display_name,status,stage,created_at,updated_at,options_json) VALUES(?,?,?,?,?,?,?,?)",
                     ("retry","fixture.mp4","fixture.mp4","awaiting_review","awaiting_review",now(),now(),json.dumps(options)))
    for stage in api.STAGES:
        database.execute("INSERT INTO stages(job_id,name,status,progress) VALUES(?,?,?,?)",("retry",stage,"completed",100))
    api.retry_stage("retry",api.RetryStage(stage="transcribe"))
    job=database.job("retry")
    assert all(row["status"]==("completed" if row["name"] in ["inspect","extract","separate"] else "pending") for row in job["stages"])
    assert job["options"]["transcript_review_approved"] is False
    assert job["options"]["subtitle_review_approved"] is False
    assert queued==["retry"]
