from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, ConfigDict, model_validator


class TemporalMask(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra='forbid')
    start_time: float = Field(ge=0)
    end_time: float = Field(gt=0)
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(ge=2)
    height: int = Field(ge=2)

    @model_validator(mode='after')
    def ordered(self):
        if self.end_time <= self.start_time:
            raise ValueError('Mask end_time must exceed start_time')
        return self


class TranslationSettings(BaseModel):
    glossary: dict[str, str] = Field(default_factory=dict, max_length=200)

    @model_validator(mode='after')
    def bounded_terms(self):
        if any(not k.strip() or not v.strip() or len(k)>100 or len(v)>200 for k,v in self.glossary.items()):
            raise ValueError('Glossary terms must be nonempty and bounded to 100/200 characters')
        return self


class JobOptions(BaseModel):
    source_language: Literal["zh", "en"] = "zh"
    target_language: Literal["en", "zh"] = "en"
    profile: Literal["cpu-lite", "balanced"] = "balanced"
    subtitle_mode: Literal["none", "fast", "balanced"] = "fast"
    subtitle_regions: list[tuple[int, int, int, int]] = Field(default_factory=list)
    temporal_masks: list[TemporalMask] = Field(default_factory=list, max_length=1000)
    translation_glossary: dict[str, str] = Field(default_factory=dict)
    max_speech_speed: float = Field(default=1.25, ge=1, le=1.3)
    dialogue_gain_db: float = Field(default=-1.0, ge=-18, le=6)
    background_gain_db: float = Field(default=-10.0, ge=-30, le=6)
    voice_assignments: dict[str, str] = Field(default_factory=lambda: {"speaker_1": "af_heart"})
    manual_speaker_assignment: bool = True
    subtitle_font_size: int = Field(default=44, ge=18, le=96)
    subtitle_margin_v: int = Field(default=44, ge=0, le=300)
    resume_from: str | None = None
    subtitle_review_approved: bool = False
    transcript_review_required: bool = False
    transcript_review_approved: bool = False

    @model_validator(mode='after')
    def glossary_valid(self):
        TranslationSettings(glossary=self.translation_glossary)
        return self


class SegmentEdit(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    id: str
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    source_text: str
    translated_text: str
    speaker_id: str = "speaker_1"
    short_translation: str | None = Field(default=None, max_length=2000)
    translation_provenance: dict = Field(default_factory=dict)


class SpeakerEdit(BaseModel):
    voice_id: str = Field(min_length=1, max_length=48)


class CreateJobResponse(BaseModel):
    id: str
    status: str
    created_at: str
