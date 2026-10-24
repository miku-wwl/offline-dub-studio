# Implementation status

## Phase 2.6 — 2026-10-25

| Area | Status | Current evidence and limits |
|---|---|---|
| Outlined Chinese detection | PASS | Actual line boxes cover 20/42/54 s; scene-aware anchors and per-frame presence checks, 1,223 masked / 277 inactive frames. This is sampled recall evidence. |
| Explicit timed masks | PASS | Validated finite video-bounded intervals/coordinates; independent of OCR; exact boundaries and an interval crossing a scene cut covered by regression and browser form/drag fixtures. |
| Subtitle reconstruction | PARTIAL | The three actual repaired stills remove legible dialogue text; visible shirt/microphone/hand streaking and bands remain. |
| Glossary/editor | PASS | Configurable project settings, new-job snapshots, protected terms/fallback, context, full/short edits, provenance and cache invalidation covered. Argos grammar is still imperfect. |
| Translation quality | PARTIAL | Actual glossary-assisted Argos plus Codex-proposed English edits; no human translation approval or scene-wide contextual model. |
| Dialogue fitting | PASS | Actual 25-segment timeline: zero >20 ms collisions, max 0.000 s, zero tail truncation. Segmentation and editorial edits differ from Phase 2.5. Naturalness remains pending. |
| Speaker/background quality | PENDING_HUMAN_REVIEW | Stable proposed voice mapping and real Demucs stems do not prove speaker identity or cinematic background preservation. |
| 48 kHz output | PARTIAL | Implemented and tested actual generated 48 kHz stereo render; real fitted voices are 48 kHz. Private final MP4 is pending export. |
| Real 60-second pipeline | PARTIAL | All real local inference and repair completed; final export paused at review before host Docker socket startup failure. |
| Recovery | PARTIAL | Old completed job/API/download passed earlier after recreation; current Docker startup is blocked, and new completed-output restart check remains pending. No runtime state was deleted. |
| Automated validation | PASS | 70 backend tests, Ruff, one frontend unit test, typecheck/build, 3 fixture browser passes (2 production/private skips), Python/npm audits. |
| Long-film readiness | PARTIAL | Bounded strip bank and mixing reduce costs, but no full-film run, human approval or artifact-free restoration. |
| Publication | NOT_RUN | No GHCR publication or release; code/main CI delivery is tracked separately from private acceptance. |

See [the Phase 2.6 quality report](PHASE26_QUALITY_REPORT.md) for actual job IDs, preserved hashes, review provenance, failures/retries and remaining work. The following Phase 2.5 section is retained as historical evidence.

## Historical Phase 2.5

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
| Recovery/cancellation | PARTIAL | Interrupted-state/cache regressions and safe generated-fixture API cancel/resume/cancel pass. The real completed-job post-restart API check is blocked by a Docker Desktop startup/socket failure. Active Demucs/render cancellation remains at stage boundaries. |
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
- Implementation commit `039dae1` passed 46 backend tests, Ruff, Python audits, 1 frontend unit test, typecheck/build and npm audit on GitHub. The final private-output production UI rerun remains blocked by Docker Desktop; direct-file Chromium decoding passes independently. See testing for precise browser scope and recovery limits.

**OVERALL_STATUS=PARTIAL.** Automated mechanical acceptance does not replace listening or visual quality approval. No full-length movie was started.
