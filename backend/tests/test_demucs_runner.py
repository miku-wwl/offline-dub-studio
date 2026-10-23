import numpy as np
import soundfile as sf
import torch

from app.demucs_runner import _save_wave


def test_demucs_wave_writer_saves_stereo_pcm(tmp_path):
    path = tmp_path / "stems.wav"
    source = torch.zeros((2, 1600), dtype=torch.float32)
    source[0, 0] = 0.25
    source[1, 1] = -0.25

    _save_wave(path, source, 16000)

    saved, rate = sf.read(path, dtype="float32", always_2d=True)
    assert rate == 16000
    assert saved.shape == (1600, 2)
    assert np.isclose(saved[0, 0], 0.25, atol=1 / 32768)
    assert np.isclose(saved[1, 1], -0.25, atol=1 / 32768)
