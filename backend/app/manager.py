from __future__ import annotations

import json
import queue
import threading
import traceback

from .config import settings
from .db import Database, now
from .pipeline import JobCancelled, Pipeline


class JobManager:
    def __init__(self, db: Database):
        self.db=db
        self.queue: queue.Queue[str] = queue.Queue()
        self.thread: threading.Thread | None = None
        self.stopping=threading.Event()

    def start(self):
        self.stopping.clear()
        self.db.init()
        interrupted=self.db.query("SELECT id FROM jobs WHERE status IN ('running','cancelling')")
        for row in interrupted:
            self.db.execute("UPDATE jobs SET status='interrupted',stage='interrupted',updated_at=? WHERE id=?",(now(),row["id"]))
            self.db.execute("UPDATE stages SET status='interrupted',error='Process restarted during stage' WHERE job_id=? AND status='running'",(row["id"],))
            self.db.log(row["id"],"warning","Application restarted during conversion; resume is available.")
        self.thread=threading.Thread(target=self._run,name="dub-studio-worker",daemon=True)
        self.thread.start()
        for row in self.db.query("SELECT id FROM jobs WHERE status='queued' ORDER BY created_at"):
            self.queue.put(row["id"])

    def stop(self):
        self.stopping.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1)

    def enqueue(self,job_id:str):
        self.queue.put(job_id)

    def _run(self):
        while not self.stopping.is_set():
            try:
                job_id=self.queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self._execute(job_id)
            finally:
                self.queue.task_done()

    def _execute(self,job_id:str):
        job=self.db.job(job_id)
        if not job or job["status"]!="queued":
            return
        self.db.execute("UPDATE jobs SET status='running',updated_at=?,error=NULL,cancel_requested=0 WHERE id=?",(now(),job_id))
        self.db.log(job_id,"info","Conversion started. Local CPU providers only; no remote inference fallback.")
        try:
            pipeline=Pipeline(self.db,lambda: bool((self.db.one("SELECT cancel_requested FROM jobs WHERE id=?",(job_id,)) or {}).get("cancel_requested")))
            result=pipeline.run(job)
            if result.get("status") in {"awaiting_review","awaiting_transcript_review"}:
                status=result["status"]
                self.db.execute("UPDATE jobs SET status=?,stage=?,updated_at=? WHERE id=?",(status,status,now(),job_id))
                self.db.log(job_id,"info","Review transcript/speakers before TTS." if status=="awaiting_transcript_review" else "Review the subtitle mask and inpainting preview, then approve export.")
                return
            report_path=settings.jobs_dir / job_id / "subtitle-report.json"
            warnings=[]
            if report_path.exists():
                warnings=json.loads(report_path.read_text(encoding="utf-8")).get("warnings",[])
            warnings.extend(r["message"] for r in self.db.query("SELECT message FROM logs WHERE job_id=? AND level='warning'",(job_id,)))
            warnings=list(dict.fromkeys(warnings))
            status="completed_with_warnings" if warnings else "completed"
            self.db.execute("UPDATE jobs SET status=?,stage='completed',progress=100,updated_at=? WHERE id=?",(status,now(),job_id))
            for warning in warnings:
                self.db.log(job_id,"warning",warning)
            self.db.log(job_id,"info",f"Conversion {status}.")
        except JobCancelled as exc:
            self.db.execute("UPDATE jobs SET status='cancelled',stage='cancelled',updated_at=?,error=? WHERE id=?",(now(),str(exc),job_id))
            self.db.execute("UPDATE stages SET status='interrupted',error='Cancelled by user' WHERE job_id=? AND status='running'",(job_id,))
            self.db.log(job_id,"warning","Conversion cancelled at a safe stage boundary.")
        except Exception as exc:
            current=self.db.one("SELECT stage FROM jobs WHERE id=?",(job_id,))
            stage=(current or {}).get("stage","unknown")
            message=str(exc).replace("\n"," ")[:1600] or type(exc).__name__
            self.db.execute("UPDATE jobs SET status='failed',updated_at=?,error=? WHERE id=?",(now(),message,job_id))
            self.db.execute("UPDATE stages SET status='failed',finished_at=?,error=? WHERE job_id=? AND name=?",
                            (now(),message,job_id,stage))
            self.db.log(job_id,"error",f"Stage {stage} failed: {message}")
            # The trace stays in the container logs for maintainers; it is not returned by the API.
            print(f"Job {job_id} failed in {stage}: {traceback.format_exc()}",flush=True)
