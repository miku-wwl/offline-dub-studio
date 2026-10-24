import json

import pytest

from app.config import Settings
from app.db import Database, now
from app.pipeline import JobCancelled, Pipeline, STAGES
from app.domain import JobOptions


@pytest.fixture
def staged_job(tmp_path,monkeypatch):
    import app.pipeline as module
    config=Settings(data_dir=tmp_path / "data",models_dir=tmp_path / "models")
    config.prepare()
    monkeypatch.setattr(module,"settings",config)
    db=Database(config.db_path)
    db.init()
    db.execute("INSERT INTO jobs(id,input_path,display_name,status,stage,created_at,updated_at,options_json) VALUES(?,?,?,?,?,?,?,?)",
               ("review","fixture.mp4","fixture.mp4","queued","queued",now(),now(),json.dumps({"transcript_review_required":True})))
    return config,db


def test_review_gate_and_resume_reuse_valid_cached_stages(staged_job,monkeypatch):
    config,db=staged_job
    calls=[]
    def stage(name):
        def execute(self,state):
            calls.append(name)
            artifact=state["work"] / f"{name}.json"
            artifact.write_text(json.dumps({"segments":[],"duration":1}),encoding="utf-8")
            return {"inspection" if name=="inspect" else "transcript" if name in {"transcribe","translate"} else name:str(artifact)}
        return execute
    for name in STAGES:
        monkeypatch.setattr(Pipeline,f"_stage_{name}",stage(name))
    pipeline=Pipeline(db,lambda:False)
    assert pipeline.run(db.job("review"))["status"]=="awaiting_transcript_review"
    assert calls==STAGES[:5]
    calls.clear()
    db.execute("UPDATE jobs SET options_json=? WHERE id='review'",(json.dumps({"transcript_review_required":True,"transcript_review_approved":True}),))
    assert pipeline.run(db.job("review"))["status"]=="awaiting_review"
    assert calls==["synthesize","subtitle_processing"]
    calls.clear()
    db.execute("UPDATE jobs SET options_json=? WHERE id='review'",(json.dumps({"transcript_review_required":True,"transcript_review_approved":True,"subtitle_review_approved":True}),))
    assert pipeline.run(db.job("review"))["status"]=="completed"
    assert calls==["render"]


def test_cancelled_generated_job_stops_before_touching_cached_stages(staged_job):
    _config,db=staged_job
    with pytest.raises(JobCancelled):
        Pipeline(db,lambda:True).run(db.job("review"))
    assert db.query("SELECT * FROM stages")==[]


def test_missing_cached_artifact_is_regenerated(staged_job,monkeypatch):
    config,db=staged_job
    absent=config.jobs_dir / "review" / "missing.json"
    db.execute("INSERT INTO stages(job_id,name,status,artifacts_json) VALUES(?,?,?,?)",
               ("review","inspect","completed",json.dumps({"inspection":str(absent)})))
    def stop_after_inspection(self,state):
        assert not absent.exists()
        raise RuntimeError("inspection was rerun")
    monkeypatch.setattr(Pipeline,"_stage_inspect",stop_after_inspection)
    with pytest.raises(RuntimeError,match="inspection was rerun"):
        Pipeline(db,lambda:False).run(db.job("review"))


def test_repair_cache_requires_matching_source_regions_and_output_hash(staged_job,monkeypatch):
    import app.pipeline as module
    config,db=staged_job
    work=config.jobs_dir / "review"
    work.mkdir()
    source=work / "source.mp4"
    repaired=work / "repaired.mkv"
    source.write_bytes(b"immutable test input")
    repaired.write_bytes(b"already validated generated intermediate")
    boxes=[{"start":0,"end":1,"start_frame":0,"end_frame":10,"boxes":[[20,75,40,10]]}]
    report={"mode":"balanced","width":160,"height":90,"fps":10,"frames_processed":10,
            "masked_frames":10,"unmasked_frames":0,"regions":boxes,"mask_applied":True,
            "output_video":str(repaired),"technique":"test-only","source_sha256":module._file_digest(source),
            "repair_sha256":module._file_digest(repaired),'quality_version':module.VERSION,'patch_roi':None}
    (work / "subtitle-report.json").write_text(json.dumps(report),encoding="utf-8")
    monkeypatch.setattr(module,"detect_boxes",lambda *_args:(boxes,[]))
    def no_repair(*_args):
        raise RuntimeError("repair executed")
    monkeypatch.setattr(module,"redact_video",no_repair)
    pipeline=Pipeline(db,lambda:False)
    state={"work":work,"source":source,"options":JobOptions(subtitle_mode="balanced"),"probe":{"height":90,'fps':'25/1'},"segments":[]}
    pipeline._stage_subtitle_processing(state)
    saved=json.loads((work / "subtitle-report.json").read_text(encoding="utf-8"))
    assert saved["repair_cache_reused"] is True
    repaired.write_bytes(b"modified cached file")
    with pytest.raises(RuntimeError,match="repair executed"):
        pipeline._stage_subtitle_processing(state)
