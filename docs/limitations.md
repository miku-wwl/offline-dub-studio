# Known limitations

- No complete end-to-end model-backed conversion is claimed until it is run and inspected on real media.
- `faster-whisper-small` and `tiny` run on CPU `int8`; recognition quality and speed vary substantially by source audio.
- Argos translates each recognized segment individually. It does not carry scene-long context or a glossary across a movie.
- Kokoro produces English voices. English-to-Chinese TTS is not implemented, so the public job API currently accepts only Chinese-to-English jobs.
- Automatic speaker diarization is not implemented. Transcript segments initially use `speaker_1`; users manually assign/merge stable IDs and select different Kokoro voices.
- Demucs is archived upstream and splits musical vocals from accompaniment. It is not a film-dialogue separator; effects may be lost and residual original voices may remain.
- Faster English TTS may exceed Mandarin cue duration. Audio is accelerated by no more than 1.2x; longer speech is preserved and can overlap following speech. The editor exposes the timing for correction.
- Tesseract now examines every frame independently, using white-caption preprocessing in the lower region or manually edited search rectangles. It retains exact frame intervals. Coloured/stylized text, signs, credits, and low-confidence glyphs can still be missed or confused. A detected mask is evidence of OCR, not proof that a region is dialogue text.
- OpenCV Telea/Navier-Stokes inpainting is a baseline. It cannot reconstruct obscured imagery and may smear edges. Historical OCR boxes are never accumulated into a global mask. A scene change cannot inherit a previous frame's boxes; erroneous text recognition within the new scene is still possible.
- Search rectangles are editable in the existing preview workflow. Masks are saved in `ocr-trace.json` as timestamped intervals. Review previews show the first masked frame, which cannot represent every scene. Inspect the final MP4 across the full sample.
- Masked jobs use a lossless FFV1 intermediate followed by the final H.264 encode. Inactive frames are pixel-identical before burn-in. This avoids two lossy encodes but can use substantial disk space. No detections means no repair intermediate or full-frame repair pass.
- Timeline mixing uses one-second audio buffers and a float scratch WAV. It records each segment's generated end, overflow, collision, and truncated tail; it does not fix every timing problem automatically. Review any tail-loss warning before accepting an export.
- Demucs still loads long audio into memory and its subprocess cannot be cancelled until it exits. FFmpeg extraction/render cancellation is also checked at stage boundaries. OCR and timeline composition have frequent cancellation checkpoints. Resume reuses completed stages with existing artifacts; it does not resume halfway through Demucs/OCR/render or prove cache integrity against malicious file tampering.
- Original import snapshots, source/stem WAVs, a float timeline scratch file, repaired frames, and encoded exports all consume disk. Stereo 44.1 kHz PCM alone uses about 1.27 GB per two hours; float 24 kHz stereo uses about 1.38 GB. FFV1 size depends heavily on footage and can dominate storage. Disk exhaustion remains a long-video risk.
- Two-hour processing is not accepted. Extrapolating a 60-second CPU sample does not establish sustained memory, disk, timing, or subjective quality. The 60-second human quality gate must pass first.
- This release does not provide a user-configurable quality/GPU mode, pyannote, voice cloning, PaddleOCR, Paddle inpainting, or a subtitle-removal neural model.
- No registry release or clean-machine offline acceptance has occurred yet.
