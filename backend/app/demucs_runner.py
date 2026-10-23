"""Run Demucs with a SoundFile writer for current Torchaudio compatibility."""

from __future__ import annotations

import soundfile as sf


def _save_wave(path, wav, sample_rate, encoding="PCM_S", bits_per_sample=16, **_kwargs):
    if encoding == "PCM_F":
        subtype = "FLOAT" if bits_per_sample <= 32 else "DOUBLE"
    else:
        subtype = {16: "PCM_16", 24: "PCM_24", 32: "PCM_32"}[bits_per_sample]
    samples = wav.detach().cpu().numpy().T
    sf.write(str(path), samples, sample_rate, format="WAV", subtype=subtype)


def main() -> int | None:
    import demucs.audio

    # Demucs calls this module-level Torchaudio function for its generated stems.
    demucs.audio.ta.save = _save_wave
    from demucs.separate import main as demucs_main

    return demucs_main()


if __name__ == "__main__":
    raise SystemExit(main())
