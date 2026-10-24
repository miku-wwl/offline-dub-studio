import numpy as np
import soundfile as sf

from app.audio import SAMPLE_RATE, compose_timeline


def test_timeline_places_segments_and_reports_overlap(tmp_path):
    first = tmp_path / "first.wav"
    second = tmp_path / "second.wav"
    sf.write(first, np.full((int(SAMPLE_RATE * 0.8), 1), 0.25, dtype=np.float32), SAMPLE_RATE)
    sf.write(second, np.full((int(SAMPLE_RATE * 0.5), 1), 0.2, dtype=np.float32), SAMPLE_RATE)
    output = tmp_path / "dub.wav"
    report = compose_timeline(
        [
            {"id": "one", "start": 0.0, "end": 0.5},
            {"id": "two", "start": 0.4, "end": 0.8},
        ],
        {"one": first, "two": second},
        1.0,
        output,
    )
    audio, rate = sf.read(output, always_2d=True)
    assert rate == SAMPLE_RATE
    assert audio.shape == (SAMPLE_RATE, 2)
    assert report["overlap_count"] == 1
    assert any("longer than its original dialogue slot" in warning for warning in report["warnings"])


def test_timeline_reports_tail_loss_and_cleans_scratch_files(tmp_path):
    voice=tmp_path / "voice.wav"
    sf.write(voice,np.full((SAMPLE_RATE,1),.4,dtype=np.float32),SAMPLE_RATE)
    output=tmp_path / "dub.wav"
    report=compose_timeline([{"id":"last","start":.5,"end":.8}],{"last":voice},1,output)
    assert report["segments"][0]["truncated_seconds"]==.5
    assert report["segments"][0]["overflow_seconds"]==.7
    assert any("cannot fit" in warning for warning in report["warnings"])
    assert not list(tmp_path.glob("timeline-*.wav"))
    audio,_=sf.read(output)
    assert np.max(np.abs(audio[:SAMPLE_RATE//2]))==0
    assert np.max(np.abs(audio[SAMPLE_RATE//2:]))>.39


def test_timeline_checkpoint_cancels_without_leaking_scratch(tmp_path):
    import pytest
    def cancel():
        raise RuntimeError("cancelled at safe audio block")
    with pytest.raises(RuntimeError,match="cancelled"):
        compose_timeline([],{},10,tmp_path / "dub.wav",cancel)
    assert not list(tmp_path.glob("timeline-*.wav"))
