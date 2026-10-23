import json
import time

from app.db import Database, now
from app.manager import JobManager


def test_sqlite_job_survives_a_database_reopen(tmp_path):
    path = tmp_path / "persistent.sqlite3"
    db = Database(path)
    db.init()
    timestamp = now()
    db.execute(
        "INSERT INTO jobs(id,input_path,display_name,status,stage,progress,created_at,updated_at,options_json) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        ("job-a", "/data/in.mp4", "in.mp4", "queued", "queued", 0, timestamp, timestamp,
         json.dumps({"source_language": "zh"})),
    )
    reopened = Database(path)
    assert reopened.job("job-a")["options"]["source_language"] == "zh"


def test_startup_marks_inflight_work_interrupted(tmp_path):
    db = Database(tmp_path / "recovery.sqlite3")
    db.init()
    timestamp = now()
    db.execute(
        "INSERT INTO jobs(id,input_path,display_name,status,stage,progress,created_at,updated_at,options_json) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        ("job-b", "/data/in.mp4", "in.mp4", "running", "transcribe", 32, timestamp, timestamp, "{}"),
    )
    db.execute(
        "INSERT INTO stages(job_id,name,status,progress) VALUES(?,?,?,?)",
        ("job-b", "transcribe", "running", 10),
    )
    manager = JobManager(db)
    manager.start()
    try:
        for _ in range(20):
            job = db.job("job-b")
            if job["status"] == "interrupted":
                break
            time.sleep(0.05)
        assert job["status"] == "interrupted"
        assert job["stages"][0]["status"] == "interrupted"
    finally:
        manager.stop()
