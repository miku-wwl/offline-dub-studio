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
