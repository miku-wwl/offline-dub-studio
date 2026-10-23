from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class JobOptions(BaseModel):
    source_language: Literal["zh", "en"] = "zh"
    target_language: Literal["en", "zh"] = "en"
    profile: Literal["cpu-lite", "balanced"] = "balanced"
    subtitle_mode: Literal["none", "fast", "balanced"] = "fast"
    subtitle_regions: list[tuple[int, int, int, int]] = Field(default_factory=list)
    dialogue_gain_db: float = Field(default=-1.0, ge=-18, le=6)
    background_gain_db: float = Field(default=-10.0, ge=-30, le=6)
    voice_assignments: dict[str, str] = Field(default_factory=lambda: {"speaker_1": "af_heart"})
    manual_speaker_assignment: bool = True
    subtitle_font_size: int = Field(default=44, ge=18, le=96)
    subtitle_margin_v: int = Field(default=44, ge=0, le=300)
    resume_from: str | None = None
    subtitle_review_approved: bool = False


class SegmentEdit(BaseModel):
    id: str
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    source_text: str
    translated_text: str
    speaker_id: str = "speaker_1"


class SpeakerEdit(BaseModel):
    voice_id: str = Field(min_length=1, max_length=48)


class CreateJobResponse(BaseModel):
    id: str
    status: str
    created_at: str
