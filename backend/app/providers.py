from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from .config import effective_cpu_count, settings


VOICE_CHOICES = [
    {"id":"af_heart","label":"Heart · American English"},
    {"id":"af_bella","label":"Bella · American English"},
    {"id":"af_nicole","label":"Nicole · American English"},
    {"id":"am_adam","label":"Adam · American English"},
    {"id":"am_michael","label":"Michael · American English"},
]
VALID_VOICES = {item["id"] for item in VOICE_CHOICES}


class _LocalPunctuationSentencizer:
    """Split Argos input at visible punctuation without loading another model."""

    def split_sentences(self, text: str) -> list[str]:
        sentences = []
        start = 0
        for index, char in enumerate(text):
            boundary = char in "。！？!?"
            if char == ".":
                boundary = index + 1 == len(text) or text[index + 1].isspace()
            if boundary:
                sentence = text[start : index + 1].strip()
                if sentence:
                    sentences.append(sentence)
                start = index + 1
        tail = text[start:].strip()
        if tail:
            sentences.append(tail)
        return sentences or ([text] if text else [])


def configure_local_argos_splitter(translation: Any) -> None:
    """Replace Argos's lazy external sentence detector with local punctuation splitting."""
    underlying = getattr(translation, "underlying", None)
    if underlying is not None and hasattr(underlying, "sentencizer"):
        underlying.sentencizer = _LocalPunctuationSentencizer()


class ProviderUnavailable(RuntimeError):
    pass


def _set_model_paths() -> None:
    os.environ["HF_HOME"] = str(settings.models_dir / "huggingface")
    os.environ["HUGGINGFACE_HUB_CACHE"] = str(settings.models_dir / "huggingface" / "hub")
    os.environ["TORCH_HOME"] = str(settings.models_dir / "torch")
    os.environ["ARGOS_PACKAGES_DIR"] = str(settings.models_dir / "argos")
    os.environ["ARGOS_DEVICE_TYPE"] = "cpu"
    os.environ["ARGOS_CHUNK_TYPE"] = "ARGOSTRANSLATE"
    if settings.offline:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"


class ASRProvider:
    def transcribe(self, audio_path: Path, model_id: str, source_language: str) -> dict:
        _set_model_paths()
        model_dir = settings.models_dir / "asr" / ("tiny" if model_id == "asr-tiny" else "small")
        if not (model_dir / "model.bin").is_file():
            raise ProviderUnavailable(f"Initialize {model_id} from Model readiness before processing.")
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise ProviderUnavailable("Faster-Whisper is missing from the application image.") from exc
        model = WhisperModel(str(model_dir), device="cpu", compute_type="int8", cpu_threads=effective_cpu_count())
        lang = "zh" if source_language == "zh" else "en"
        segments, info = model.transcribe(str(audio_path), language=lang, beam_size=5,
                                           vad_filter=True, condition_on_previous_text=True)
        rows = []
        for idx, seg in enumerate(segments):
            text = seg.text.strip()
            if not text:
                continue
            avg_logprob = float(getattr(seg, "avg_logprob", -1.0))
            rows.append({"id":f"seg-{idx+1:05d}","start":max(0.0,float(seg.start)),
                         "end":max(float(seg.end),float(seg.start)+0.05),"source_text":text,
                         "translated_text":"","speaker_id":"speaker_1",
                         "asr_quality":round(float(np.exp(min(0.0,avg_logprob))),4)})
        return {"segments":rows,"language":getattr(info,"language",lang),
                "language_probability":float(getattr(info,"language_probability",0.0)),
                "provider":"faster-whisper","model":model_id,"compute":"cpu-int8"}


class TranslationProvider:
    def translate(self, segments: list[dict], source: str, target: str) -> dict:
        if source == target:
            for seg in segments:
                seg["translated_text"] = seg["source_text"]
            return {"provider":"identity","translated":len(segments)}
        try:
            import argostranslate.translate as translate
        except ImportError as exc:
            raise ProviderUnavailable("Argos Translate is missing from the application image.") from exc
        from_code, to_code = ("zh", "en") if (source,target)==("zh","en") else ("en","zh")
        languages = {lang.code: lang for lang in translate.get_installed_languages()}
        source_language, target_language = languages.get(from_code), languages.get(to_code)
        installed = source_language.get_translation(target_language) if source_language and target_language else None
        if installed is None:
            raise ProviderUnavailable(f"Initialize the local {from_code} to {to_code} Argos package first.")
        configure_local_argos_splitter(installed)
        count = 0
        for seg in segments:
            text = seg["source_text"]
            if not any("\u3400" <= c <= "\u9fff" for c in text):
                seg["translated_text"] = text
            else:
                # Each ASR chunk retains its own ID and original interval.
                seg["translated_text"] = installed.translate(text)
                count += 1
        return {"provider":"argos-translate","from":from_code,"to":to_code,"translated":count}


class TTSProvider:
    def __init__(self):
        self._pipeline = None

    def _get_pipeline(self):
        _set_model_paths()
        if self._pipeline is None:
            try:
                from kokoro import KPipeline
                import torch
            except ImportError as exc:
                raise ProviderUnavailable("Kokoro is missing from the application image.") from exc
            torch.set_num_threads(effective_cpu_count())
            # KPipeline calls Hugging Face without a revision parameter. Model initialization
            # pins the snapshot and sets the cached main ref to that reviewed commit.
            self._pipeline = KPipeline(lang_code="a", repo_id="hexgrad/Kokoro-82M", device="cpu")
        return self._pipeline

    def synthesize(self, text: str, voice_id: str, output: Path) -> dict[str, Any]:
        if voice_id not in VALID_VOICES:
            raise ValueError(f"Unsupported Kokoro voice: {voice_id}")
        chunks = []
        for _graphemes, _phonemes, audio in self._get_pipeline()(text, voice=voice_id):
            if audio is not None:
                chunks.append(np.asarray(audio, dtype=np.float32).reshape(-1))
        if not chunks:
            raise RuntimeError("Kokoro returned no waveform for a non-empty translation")
        waveform = np.concatenate(chunks)
        sf.write(output, waveform, 24000, subtype="PCM_16")
        return {"voice_id":voice_id,"sample_rate":24000,"duration":len(waveform)/24000,
                "provider":"kokoro","model_revision":"f3ff3571791e39611d31c381e3a41a3af07b4987"}
