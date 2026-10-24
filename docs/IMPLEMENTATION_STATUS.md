# Implementation status

Validated on 2026-10-24 in the Windows/Docker Desktop workspace. Phase 2.5 uses the actual supplied `test.webm`; earlier FLEURS fixture results are historical. `PASS` applies to the specifically measured behavior.

| Area | Status | Evidence and remaining work |
|---|---|---|
| Safe media import | PASS | Regression coverage for invalid/unsupported/interrupted import, no overwrite, insufficient snapshot space, independent valid snapshot and unchanged SHA-256. Real source and import snapshot were preserved. |
| Temporal subtitle masks | PASS | Exact frame intervals; manual regions constrain OCR search; absent frames bypass repair. Synthetic scene/moving-object test and 459 real inactive-frame pixel comparisons passed. |
| Local speech pipeline | PASS | Actual Balanced 60-second job ran Small ASR, Argos, Kokoro and Demucs on CPU. No mocked providers or remote inference fallback. |
| Speakers | PARTIAL | Three manually proposed groups with stable distinct English voices. Automatic diarization, off-camera identity and original overlap remain unverified. |
| English dub timing | PARTIAL | Nine collisions over 20 ms, maximum 1.085 s. Zero end-of-video tail truncation; no silently discarded overlong cue. Naturalness and lip sync need listening/video review. |
| Cinematic audio preservation | PENDING_HUMAN_REVIEW | Actual stems and mixed audio exported, clipping/loudness measured. Demucs is a music-vocal separator and does not establish film-dialogue isolation or perceptual music/effects preservation. |
| Hard subtitle restoration | PARTIAL | Actual Chinese captions processed, timed masks and repair previews exported. Conservative OCR leaves glyphs; OpenCV can smear detail. |
| English captions | PASS | ASS/SRT, ordered intervals, wrapping/escaping, readable margin above source band and actual burn-in. Translation accuracy remains human reviewed. |
| Web workflow | PARTIAL | Real API import→review→approve→export→download completed. Browser regressions cover transcript/speaker review and production output playback. The complete model-backed conversion was not initiated entirely with browser actions. |
| Recovery/cancellation | PASS | Persisted stages/outputs, interrupted-state/cache regressions; separate safe generated fixture for actual API queued cancel/resume/cancel. Active Demucs/render cancellation remains at stage boundaries. |
| Security dependencies | PASS | filelock 4.2.1; pip check and vulnerability audit without ignored IDs. Two pinned direct upstream builds lack PyPI audit coverage and are disclosed. |
| Long-video readiness | PARTIAL | Bounded audio mixing, ROI repair and validated caches help, but Demucs memory, FFV1 disk, stage-boundary cancellation and sample quality still gate two-hour acceptance. |
| Release/distribution | NOT_RUN | Local image only. No GHCR push, GitHub release, model-term acceptance or full-film execution. MiniSBD transitive licensing remains documented. |

## Evidence

- Job: `e47f9f3b-7236-4afe-8548-f1295d497e43`, `completed_with_warnings`.
- Input: actual source seconds 10–70, converted to 60.000 s H.264/AAC 1920×1080 at 25 fps.
- Output: `data/acceptance/phase-2.5/dubbed-60s.mp4`, 18,261,468 bytes, SHA-256 `533dd7f1a0b14a65802907edc238b806f31d323f30ed103ccb7a9854abd1c58a`.
- Source SHA-256 remains `bb779354520eb5edd040910d970c41471235ad1f2b49e5d3d73abd3e9f1fc4d4`.
- Evidence directory contains full source/stem/TTS/mixed audio, transcript and visual corrections, speaker proposals, ASS/SRT, mask/repaired/English stills, FFprobe/decode/timestamp/quality reports, each stage attempt, Docker stats, offline firewall proof and audit logs. Media and model weights are excluded from Git/build context.
- Full automated commands/results are maintained in [testing](testing.md), and the [real-video report](REAL_VIDEO_ACCEPTANCE.md) records actual failures, measured costs, limitations and human review checklist. The final remote commit/run identity is provided in the delivery response and ignored `delivery.json`.

**OVERALL_STATUS=PARTIAL.** Automated mechanical acceptance does not replace listening or visual quality approval. No full-length movie was started.
