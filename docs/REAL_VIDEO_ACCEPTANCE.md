# Phase 2.5 real-video acceptance

Date: 2026-10-24, Pacific/Auckland. Baseline: `1b873652f9f608afb34f10d461c8ddfe156217f7`.

## Source and preservation

The actual user-supplied `D:/workshop/oct/offline-dub-studio/test.webm` was used. It was not moved, modified, overwritten, deleted, downloaded again, or committed. SHA-256 before and after processing:

`bb779354520eb5edd040910d970c41471235ad1f2b49e5d3d73abd3e9f1fc4d4`

FFprobe measured 95.748 seconds, 18,347,212 bytes, VP9 1920×1080 at 25/1 fps, Opus stereo at 48 kHz, and no embedded subtitle stream. The container metadata labels the audio `eng`; this was not used to infer the spoken language. Actual local recognition produced Chinese text, and sampled frames visibly contain Chinese captions.

The continuous source interval **10.000–70.000 seconds** was selected. It contains the presenter, a male interview subject, a female interview subject, scene changes, and hardcoded Chinese dialogue captions. Questions spoken off camera cannot be assigned conclusively from pictures. Exact audible speaker count, voice identity, music/effect content, residual Mandarin, and overlapping original speech require human listening.

The conversion command was executed with the original project mounted read-only and the generated destination under ignored `data`:

```powershell
docker run --rm --entrypoint ffmpeg --volume 'D:\workshop\oct\offline-dub-studio:/source:ro' --volume 'D:\workshop\oct\offline-dub-studio\data:/data' ghcr.io/miku-wwl/offline-dub-studio:local -n -v warning -ss 10 -i /source/test.webm -t 60 -map 0:v:0 -map 0:a:0 -vf setpts=PTS-STARTPTS -af asetpts=PTS-STARTPTS -c:v libx264 -threads 8 -preset veryfast -crf 18 -pix_fmt yuv420p -r 25 -c:a aac -b:a 192k -movflags +faststart /data/inbox/test-60s.mp4
```

The clip is exactly 60.000 seconds, H.264/AAC, 1920×1080, 25 fps, with both streams starting at zero. Clip and independent imported-snapshot SHA-256:

`7d7d5f6d279a174c2c829a94271c1c5d2a937f833d39a756c17b7d258bcc5e9f`

## Actual application lifecycle

Job: `e47f9f3b-7236-4afe-8548-f1295d497e43`. Profile: **Balanced**, CPU only, Faster-Whisper Small int8, local Argos zh→en 1.9, Kokoro 82M, Demucs htdemucs, and Balanced OpenCV subtitle processing. The model revisions/checksums remain in local `models/*/pack-manifest.json` files.

The clip was imported using `POST /api/v1/media/import`, then processed using the normal FastAPI job queue. It paused for transcript review, accepted timestamp-preserving source/speaker edits, generated actual local English voices, paused again for subtitle preview review, and used the normal approval/export/download routes. No ASR, translation, TTS, or separation provider was mocked for this run.

Initial machine output and visual source corrections are kept separately in `data/acceptance/phase-2.5/transcript-machine-before-review.json`, `segment-review.json`, and `transcript-visual-review.jpg`. Seven corrections were grounded in visible Chinese captions; Argos was then rerun on those corrected source segments. All 27 original segment IDs/start/end times were preserved.

Proposed manual mapping: `speaker_1 → am_adam`, `speaker_2 → am_michael`, `speaker_3 → af_heart`. The first group includes the presenter and off-camera questions as a proposal. This is not automatic diarization or verified identity. Human speaker review remains pending.

## Failures reproduced and corrected

- Inbox validation used to unlink the caller's source. Registration now never deletes a supplied path. Upload/import staging has explicit ownership, exclusive temporary files, atomic collision-safe publication, and cleanup only for unregistered app-owned copies. Imports create independent snapshots and reject insufficient copy space without touching originals.
- Historical OCR boxes used to become a permanent full-video mask. Every detection now has exact frame bounds. Inactive frames bypass inpainting; no detections bypass repair encoding entirely. Manual rectangles constrain OCR search. Lossless FFV1 precedes the final H.264 encode.
- During this work, an initially global `OMP_THREAD_LIMIT=1` made CTranslate2 return an empty transcript when asked for eight threads. A controlled ten-second real-audio reproduction returned no text with that mismatch and Chinese text without it. The limit now applies only during OCR, ASR respects any explicit lower limit, and empty recognition fails with actionable diagnostics. Only recognition and downstream stages were retried; extraction/separation were reused. `asr-thread-capped.json`, `asr-thread-normal.json`, and `asr-thread-fixed.json` retain the real evidence.
- The first subtitle preview incorrectly masked a one-frame background blob. That preview was rejected and preserved under `initial-ocr-preview`. Boundary/oversized blobs and isolated detections are now filtered. The actual OCR trace was retained, its private-source hash was verified against the preserved inbox clip, and that provenance was added before reusing the detections. `ocr-raw-first-attempt.json` preserves the original trace. The retry uses hash/ROI-checked cached OCR and inpaints only the relevant image crop.
- The initial CI failed on three `filelock==3.32.3` advisories. Runtime constraints and the lock now pin 4.2.1, consistent with the [upstream advisory](https://github.com/tox-dev/filelock/security/advisories/GHSA-v4x8-3wr5-3wq8). No vulnerability IDs are ignored. The Docker smoke workflow also now retains its container until the browser check finishes.
- Production-browser testing exposed a separate history-selection crash: the jobs list contains summaries, but the page treated a summary as a complete job before its detail request finished. The API types now distinguish summaries, and the page waits for matching details. The browser regression returns the real sparse summary shape.
- English captions initially intersected the source subtitle band. The final layout uses an effective ASS bottom margin of 127 pixels (requested 40), placing English above that band. This layout-only retry reused the hash-verified repair intermediate.

## Measured media and audio results

The final job state is `completed_with_warnings`. The output is **60.000 seconds, H.264/AAC, 1920×1080, 25 fps**, 18,261,468 bytes. SHA-256 of the stored output, API download, and acceptance copy:

`533dd7f1a0b14a65802907edc238b806f31d323f30ed103ccb7a9854abd1c58a`

Open `D:/workshop/oct/offline-dub-studio/data/acceptance/phase-2.5/dubbed-60s.mp4` on Windows. The required evidence list is complete (`missing_artifacts: []`).

| Check | Result | Scope |
|---|---|---|
| Source/snapshot preservation | PASS | Original hash unchanged; clip and private import snapshot hashes match. |
| Complete output decode and timestamps | PASS | FFmpeg `-xerror` decode, monotonic packet DTS, matching audio/video duration and expected codecs/dimensions/fps. |
| Temporal-mask safety | PASS | 459 inactive frames compared against the decoded source; zero changed in the lossless repair intermediate. 1,041 of 1,500 frames have active masks. Final H.264 encoding and English burn-in naturally change output pixels. |
| Real local providers | PASS | Small ASR, Argos, Kokoro and Demucs actually ran; 27 Chinese segments and English TTS tracks. |
| Stable assigned voices | PASS | Each proposed speaker ID retained its selected voice. Identity correctness and automatic diarization remain unverified. |
| Audio levels | PASS | Mixed PCM: zero clipped samples; final output: -22.0 LUFS integrated, -3.8 dBFS true peak. |
| Timing and English dub | PARTIAL | Nine collisions exceed 20 ms; maximum 1.085 s. Raw overlap count is 13, including small fit-rounding overlaps. No end-of-video tail loss (0.0 s). Longer speech was preserved with warnings. |
| English captions | PASS | ASS/SRT exist; 27 ordered cues, valid intervals, wrapping/escaping and visible final burn-in. Linguistic accuracy still requires review. |
| Chinese subtitle restoration | PARTIAL | Actual text was masked and repaired, but inspected previews retain missed glyphs and visible smearing. |
| Background, residual Mandarin, naturalness and lip sync | PENDING_HUMAN_REVIEW | Signal measurements and muted playback cannot establish perceptual quality. |

Silence spans for each source/stem/TTS/mixed track are listed at a -55 dBFS threshold in `audio-quality-report.json`. Leading/trailing TTS padding is measured. There is no all-silent TTS track; these measurements cannot identify every missing word, sound effect, or perceptually unexplained gap.

## Actual processing cost and long-video readiness

`performance.json` preserves **all attempts**, including rejected results and cached retries:

| Stage/attempt | Seconds |
|---|---:|
| Inspect | 0.231 |
| Extract | 0.980 |
| Demucs | 135.525 |
| ASR initial empty result (rejected) | 55.533 |
| Translation of empty result (rejected) | 0.016 |
| ASR after thread correction | 23.993 |
| Translation | 7.574 |
| Translation after visual source corrections | 1.761 |
| TTS and timeline composition | 64.521 |
| First OCR/repair (preview rejected) | 984.421 |
| Filtered ROI repair (OCR cache reused) | 389.868 |
| Caption-layout refresh (repair cache reused) | 25.835 |
| Final render | 85.814 |
| **All stage attempts** | **1,776.072** |

Creation at 00:16:32 UTC to completion at 01:28:38 UTC was **4,326 seconds**, including engineering, builds, review pauses, and retries. The sum of the latest selected stage entries is 338.660 seconds and **includes caches**; it is not a cold end-to-end benchmark. The corrected implementation has not been timed as one fresh uninterrupted run.

Peak observed cgroup memory was **2,526,797,824 bytes** (including page cache). 401 Docker samples recorded CPU up to **796.27%**, where 100% means one logical core; their simple unweighted mean was 159.81%, including idle/review time. Samples are diagnostic, not a complete time-weighted utilization profile.

At evidence collection the job directory occupied 1,092,256,224 bytes across 53 files, including the **1,029,431,357-byte FFV1 repair intermediate**. The acceptance folder used approximately 132.6 MB before the final documentation/browser logs. The 60-second input is 22,543,691 bytes; final MP4 is 18,261,468 bytes; the dialogue/mixed 24 kHz stereo PCM files are approximately 5.76 MB each; each original 44.1 kHz stereo stem is approximately 10.59 MB. These copies intentionally consume extra acceptance disk space.

One-second timeline buffers replace whole-video NumPy buffers. ROI inpainting reduces CPU work, a lossless intermediate prevents two lossy encodes, and source/ROI/hash-checked caches preserve successful work during layout retries. Demucs still loads long audio; extraction, Demucs and render have stage-boundary cancellation. FFV1 storage remains a major risk: linear size extrapolation alone would be about **123.5 GB for two hours** on similar footage, before snapshots, WAVs and exports. This is a storage warning, not a full-film benchmark. Import checks free space for the snapshot, but there is no reliable admission estimate for every later stage. Long-video readiness is **PARTIAL** and the human sample gate remains closed.

## Evidence and repeatable validation

All real media and evidence are under ignored `data/acceptance/phase-2.5/`; model weights remain under ignored `models/`. `run.json` records the job and options, `job.json` the API state, `performance.json` each stage attempt, and `docker-stats.jsonl` sampled container CPU/memory. `security-audit.log` contains the audit result. Only code, tests, and documentation are committed.

The collector is executed with no network access, mounting source read-only:

```powershell
docker run --rm --network none --entrypoint python --volume 'D:\workshop\oct\offline-dub-studio:/workspace:ro' --volume 'D:\workshop\oct\offline-dub-studio\data:/data' --env PYTHONPATH=/workspace/backend ghcr.io/miku-wwl/offline-dub-studio:local /workspace/scripts/validate_acceptance.py --source /workspace/test.webm --clip /data/inbox/test-60s.mp4 --job-id e47f9f3b-7236-4afe-8548-f1295d497e43 --evidence /data/acceptance/phase-2.5 --expected-source-sha256 bb779354520eb5edd040910d970c41471235ad1f2b49e5d3d73abd3e9f1fc4d4
```

The collector verifies source/snapshot hashes, codecs, dimensions, 25 fps, duration consistency, monotonic packet DTS, complete error-free output decode, non-silent generated voices, stable voice IDs, clipping/loudness, subtitle intervals/line lengths, and all inactive frames in the lossless intermediate. It exports the required stems, separate English voice tracks, combined dialogue, mixed audio, transcript, translation, assignments, ASS/SRT, mask/repaired/English previews, and FFprobe/quality reports. The report distinguishes mechanical media integrity from timing and subjective quality.

## Human quality gate

All subjective checks remain **PENDING_HUMAN_REVIEW**. Open the final `dubbed-60s.mp4`, compare the source and stems, and assess voice naturalness, identity mapping, translation, remaining Mandarin, retained music/effects/ambience, timing/lip sync, and subtitle repair. Automated muted browser playback does not count as listening. Native Windows Media Player playback has not been asserted from FFmpeg/browser evidence.

Demucs is a music-vocal separator. OpenCV is a restoration baseline and cannot reconstruct obscured imagery. Conservative OCR can leave Chinese glyphs behind or miss stylized text. The current dub contains reported timing collisions and has not passed subjective synchronization acceptance. No full-length movie was started; long-video acceptance remains gated on the sample's human review.
