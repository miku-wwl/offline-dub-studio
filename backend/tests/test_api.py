import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

from app.main import app, db
from app.config import settings
from app.db import now


def test_local_health_and_openapi_contract():
    with TestClient(app) as client:
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        schema = client.get("/openapi.json").json()
        assert "/api/v1/media/upload" in schema["paths"]
        assert "/api/v1/jobs/{job_id}/approve-subtitles" in schema["paths"]


def test_job_diagnostics_include_elapsed_times_and_original_video(tmp_path):
    job_id="api-elapsed-contract"
    source=tmp_path / "source.mp4"
    source.write_bytes(b"synthetic original bytes")
    timestamp=now()
    try:
        with TestClient(app) as client:
            db.execute("INSERT INTO jobs(id,input_path,display_name,status,stage,progress,created_at,updated_at,options_json) VALUES(?,?,?,?,?,?,?,?,?)",
                       (job_id,str(source),"source.mp4","running","inspect",1,timestamp,timestamp,"{}"))
            db.execute("INSERT INTO stages(job_id,name,status,progress,started_at) VALUES(?,?,?,?,?)",
                       (job_id,"inspect","running",10,timestamp))
            detail=client.get(f"/api/v1/jobs/{job_id}")
            assert detail.status_code==200
            assert detail.json()["elapsed_seconds"]>=0
            assert detail.json()["current_stage_elapsed_seconds"]>=0
            original=client.get(f"/api/v1/jobs/{job_id}/artifacts/original")
            assert original.status_code==200
            assert original.content==b"synthetic original bytes"
    finally:
        db.execute("DELETE FROM jobs WHERE id=?",(job_id,))


def test_import_rejects_path_traversal_before_filesystem_lookup():
    with TestClient(app) as client:
        response = client.post("/api/v1/media/import", json={"filename": "../outside.mp4"})
        assert response.status_code == 400


def test_reverse_translation_is_not_advertised_as_supported():
    with TestClient(app) as client:
        response = client.post("/api/v1/jobs", json={
            "asset_id": "missing",
            "options": {"source_language": "en", "target_language": "zh"},
        })
        assert response.status_code == 501
        assert "Chinese-to-English" in response.json()["detail"]


def test_job_requires_real_local_model_packs_before_queueing():
    with TestClient(app) as client:
        response=client.post("/api/v1/jobs",json={"asset_id":"missing","options":{"profile":"cpu-lite"}})
        assert response.status_code==409
        assert "asr-tiny" in response.json()["detail"]
        assert "tts-kokoro-en" in response.json()["detail"]


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg is not installed")
def test_upload_probes_an_actual_synthetic_video(tmp_path):
    source=tmp_path / "synthetic.mp4"
    subprocess.run([
        "ffmpeg","-y","-v","error","-f","lavfi","-i","color=c=navy:s=320x240:r=12",
        "-f","lavfi","-i","sine=frequency=440:sample_rate=44100","-t","1.5",
        "-c:v","libx264","-pix_fmt","yuv420p","-c:a","aac",str(source),
    ],check=True)
    with TestClient(app) as client:
        with source.open("rb") as data:
            response=client.post("/api/v1/media/upload",files={"file":("synthetic.mp4",data,"video/mp4")})
        assert response.status_code==201
        info=response.json()
        assert info["duration"]>=1.4
        assert info["width"]==320 and info["height"]==240
        assert info["has_audio"] is True
        assert (settings.uploads_dir / f"{info['id']}.mp4").exists()
