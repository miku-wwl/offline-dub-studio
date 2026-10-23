# Known limitations

- No complete end-to-end model-backed conversion is claimed until it is run and inspected on real media.
- `faster-whisper-small` and `tiny` run on CPU `int8`; recognition quality and speed vary substantially by source audio.
- Argos translates each recognized segment individually. It does not carry scene-long context or a glossary across a movie.
- Kokoro produces English voices. English-to-Chinese TTS is not implemented, so the public job API currently accepts only Chinese-to-English jobs.
- Automatic speaker diarization is not implemented. Transcript segments initially use `speaker_1`; users manually assign/merge stable IDs and select different Kokoro voices.
- Demucs is archived upstream and splits musical vocals from accompaniment. It is not a film-dialogue separator; effects may be lost and residual original voices may remain.
- Faster English TTS may exceed Mandarin cue duration. Audio is accelerated by no more than 1.2x; longer speech is preserved and can overlap following speech. The editor exposes the timing for correction.
- Tesseract samples Chinese text in the lower part of the frame. Signs, credits, karaoke text, stylized subtitles, and short-lived captions can be confused or missed.
- OpenCV Telea/Navier-Stokes inpainting is a baseline. It cannot reconstruct content hidden beneath hard subtitles and may blur/damage picture areas. It applies the merged detections over the entire video and does not model scene cuts.
- Subtitle-region review uses a representative frame; a single region list is applied throughout the video. Scene-specific region timelines are not implemented.
- This release does not provide a user-configurable quality/GPU mode, pyannote, voice cloning, PaddleOCR, Paddle inpainting, or a subtitle-removal neural model.
- No registry release or clean-machine offline acceptance has occurred yet.
