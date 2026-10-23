from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.RLock()

    @contextmanager
    def connect(self):
        con = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA foreign_keys=ON")
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as con:
            con.executescript("""
            CREATE TABLE IF NOT EXISTS jobs (
              id TEXT PRIMARY KEY, input_path TEXT NOT NULL, display_name TEXT NOT NULL,
              status TEXT NOT NULL, stage TEXT NOT NULL DEFAULT 'queued', progress REAL NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL, options_json TEXT NOT NULL,
              error TEXT, cancel_requested INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS stages (
              job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE, name TEXT NOT NULL,
              status TEXT NOT NULL, progress REAL NOT NULL DEFAULT 0, started_at TEXT,
              finished_at TEXT, artifacts_json TEXT NOT NULL DEFAULT '{}', error TEXT,
              PRIMARY KEY(job_id, name)
            );
            CREATE TABLE IF NOT EXISTS logs (
              id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
              timestamp TEXT NOT NULL, level TEXT NOT NULL, message TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS speakers (
              job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE, speaker_id TEXT NOT NULL,
              voice_id TEXT NOT NULL, label TEXT NOT NULL DEFAULT '',
              PRIMARY KEY(job_id, speaker_id)
            );
            CREATE TABLE IF NOT EXISTS media (
              id TEXT PRIMARY KEY, path TEXT NOT NULL, display_name TEXT NOT NULL,
              bytes INTEGER NOT NULL, probe_json TEXT NOT NULL, created_at TEXT NOT NULL
            );
            """)

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        with self.lock, self.connect() as con:
            con.execute(sql, params)

    def query(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self.lock, self.connect() as con:
            return [dict(row) for row in con.execute(sql, params).fetchall()]

    def one(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def log(self, job_id: str, level: str, message: str) -> None:
        self.execute("INSERT INTO logs(job_id,timestamp,level,message) VALUES(?,?,?,?)",
                     (job_id, now(), level, message[:2000]))

    def job(self, job_id: str) -> dict[str, Any] | None:
        job = self.one("SELECT * FROM jobs WHERE id=?", (job_id,))
        if job:
            job["options"] = json.loads(job.pop("options_json"))
            job["stages"] = self.query("SELECT * FROM stages WHERE job_id=? ORDER BY rowid", (job_id,))
        return job
