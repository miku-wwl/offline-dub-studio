import json
from types import SimpleNamespace

import numpy as np
import pytest
import soundfile as sf

from app import media


def test_probe_requires_a_video_stream(monkeypatch, tmp_path):
    monkeypatch.setattr(media, "run", lambda args, **kwargs: SimpleNamespace(stdout=json.dumps({"streams": []})))
    with pytest.raises(media.MediaError, match="does not contain a video"):
        media.probe_media(tmp_path / "bad.mp4")


def test_probe_reports_streams_and_uses_argument_vector(monkeypatch, tmp_path):
    source = tmp_path / "quoted ; name.mp4"
    source.write_bytes(b"placeholder")
    fixture = {
        "streams": [
            {"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080,
             "avg_frame_rate": "24000/1001", "duration": "8.0"},
            {"codec_type": "audio", "codec_name": "aac"},
            {"codec_type": "subtitle", "codec_name": "mov_text"},
        ],
        "format": {"duration": "8.0"},
    }
    captured = {}
    def fake_run(args, **kwargs):
        captured["args"] = args
        return SimpleNamespace(stdout=json.dumps(fixture))
    monkeypatch.setattr(media, "run", fake_run)
    result = media.probe_media(source)
    assert result["duration"] == 8
    assert result["has_audio"] is True
    assert len(result["subtitle_streams"]) == 1
    assert str(source) in captured["args"]
    assert isinstance(captured["args"], list)


def test_faster_whisper_audio_decoder_accepts_pinned_pyav_api(tmp_path):
    from faster_whisper.audio import decode_audio

    source = tmp_path / "short-tone.wav"
    sample = np.zeros(16000, dtype=np.float32)
    sf.write(source, sample, 16000)

    decoded = decode_audio(str(source), sampling_rate=16000)

    assert decoded.shape == (16000,)
    assert decoded.dtype == np.float32
