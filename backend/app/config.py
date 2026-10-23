from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def effective_cpu_count() -> int:
    count = os.cpu_count() or 1
    process_count = getattr(os, "process_cpu_count", None)
    if callable(process_count):
        count = process_count() or count
    # Python 3.12's os.cpu_count() ignores Docker CPU quota. Respect cgroup v2 when set.
    try:
        quota, period = Path("/sys/fs/cgroup/cpu.max").read_text(encoding="ascii").split()[:2]
        if quota != "max":
            count = min(count, max(1, (int(quota) + int(period) - 1) // int(period)))
    except (OSError, ValueError, ZeroDivisionError):
        pass
    return max(1, count)


@dataclass(frozen=True)
class Settings:
    host: str = os.getenv("APP_HOST", "127.0.0.1")
    port: int = int(os.getenv("APP_PORT", "7860"))
    data_dir: Path = Path(os.getenv("DATA_DIR", "/data"))
    models_dir: Path = Path(os.getenv("MODELS_DIR", "/models"))
    max_upload_bytes: int = int(os.getenv("MAX_UPLOAD_BYTES", str(20 * 1024**3)))
    max_inbox_bytes: int = int(os.getenv("MAX_INBOX_BYTES", str(100 * 1024**3)))
    max_duration_seconds: int = int(os.getenv("MAX_DURATION_SECONDS", str(12 * 60 * 60)))
    ffmpeg: str = os.getenv("FFMPEG", "ffmpeg")
    ffprobe: str = os.getenv("FFPROBE", "ffprobe")
    tesseract: str = os.getenv("TESSERACT", "tesseract")
    offline: bool = os.getenv("OFFLINE_INFERENCE", "false").lower() == "true"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "studio.sqlite3"

    @property
    def inbox_dir(self) -> Path:
        return self.data_dir / "inbox"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"

    def prepare(self) -> None:
        for path in (self.data_dir, self.models_dir, self.inbox_dir, self.uploads_dir, self.jobs_dir,
                     self.data_dir / "output"):
            path.mkdir(parents=True, exist_ok=True)


settings = Settings()
