# Phase 2.6 real-video quality report

Date: 2026-10-25, Pacific/Auckland. Baseline: `e4f1d7a431688d496bae2623d00045c0f01d0ffd`.

**OVERALL_STATUS=PARTIAL.** This report distinguishes measured engineering results from pending human listening and visual approval. No full-film conversion, remote inference, new large model, GHCR publication or GitHub release was performed.

## Implementation

Outlined Chinese line detection now combines white glyphs, dark outlines, horizontal projections, short OCR anchors and per-frame presence checks. Scene boundaries reset tracking. Explicit masks use `{start_time,end_time,x,y,width,height}` and half-open frame intervals; they operate independently of OCR. Manual search rectangles remain OCR constraints. The browser can select a source time, draw a rectangle and save its time interval.

The CPU restoration path uses scene-local temporal references, optical flow and spatial fallback. Reference storage is a bounded subtitle-strip bank. Only the subtitle strip is encoded losslessly; final overlay preserves all unmasked pixels before the last H.264 encode. This is a reconstruction heuristic with visible failures, not a generative video restoration model.

A project glossary is saved through `/api/v1/project/translation`, snapshotted into each new job and editable per job. Argos protects glossary terms; if markers are corrupted, fallback translates every surrounding source span and inserts the exact terms. It records the fallback and leaves grammar pending review. Neighboring source context, manual English overrides, shorter variants and provenance are exposed in the editor. Argos remains segment based; it does not provide automatic scene-wide contextual rewriting.

Dialogue budgets use the next segment, available gaps and source interval overlap. Kokoro's native 24 kHz output is retained, outer low-energy padding is trimmed with 40 ms context, and bounded `atempo` (default cap 1.25×) precedes one resample to the 48 kHz timeline. Raw, trimmed and fitted files are retained. Energy thresholds cannot prove that every breath or unvoiced consonant is safe; human listening remains required. Overflow is reported, and a nontrivial final speech tail blocks export instead of silently dropping it.

Extraction, Demucs bed resampling, dialogue composition, mixing and final AAC use 48 kHz; the final output is stereo. The limiter compensates its latency. Dependency fingerprints and immutable output hashes prevent stale reuse after source, text, voice, glossary, speed, mask or rendering changes.

## Actual run and attribution

New job: `dc04452a-410e-425f-b950-afe1a7a86895`. It uses the same 60-second input, Balanced/CPU, Faster-Whisper Small int8, Argos zh→en, Kokoro and Demucs htdemucs. Each provider ran locally on the new job; upstream outputs were reused only during later downstream retries.

The new ASR produced **25 segments**, compared with 27 in Phase 2.5. Seven source corrections were grounded in visible Chinese captions. The engineering run saved 25 Codex-proposed English overrides and eight shorter variants through the normal API, preserving IDs and timestamps from the new ASR. These are reviewable editorial proposals, not human translation approval or proof of automatic Argos naturalness. Collision gains reflect both different segmentation and the translation/fitting workflow; this is not an isolated algorithm benchmark.

Actual glossary terms include `flag bearer`, `roller skating`, `non-Olympic` and `World Games`. The unedited glossary-assisted Argos output still contained awkward grammar. The three proposed speaker groups retain `am_adam`, `am_michael` and `af_heart`; presenter/off-camera identity and actual overlapping voices remain unverified.

## Visual comparison

Actual repaired frames at 20, 42 and 54 seconds have been inspected, alongside the original and preserved Phase 2.5 output. At 20 seconds the old output retained the entire Chinese line; at 42 and 54 seconds it retained large fragments. The new repaired frames have no legible Chinese dialogue glyphs in those three lines. Scene signage and the source watermark are intentionally outside the dialogue repair scope.

Reconstruction is still **PARTIAL**. At 20 seconds the hand/microphone has a local smear and the shirt has a horizontal seam. At 42 seconds the lower shirt and microphone are visibly stretched, with damaged background lettering and hand-edge blocks. At 54 seconds the lower shirt/microphone again has pronounced vertical streaking. Improved dialogue-text removal does not establish an overall visual-quality pass. These observations cover sampled stills, not all 1,500 frames or flicker in motion.

Local evidence: `data/acceptance/phase-2.6/comparisons/{20,42,54}/repair-review.png` contains the actual pre-burn repair. Final MP4 comparisons and final measured output results are pending export. Development `candidate-*.png` files are not final acceptance evidence.

## Measurements and current completion

The completed synthesis has 25 nonempty fitted tracks, zero collisions over 20 ms, zero unintended collisions over 100 ms, a maximum collision of 0.000 s and no end-of-video truncation. Phase 2.5 had nine collisions over 20 ms and a maximum of 1.085 s. Perceptual fluency, identity, residual Mandarin, music/effects preservation and lip sync require human review.

The new repair processed 1,500 frames: 1,223 masked and 277 inactive. Its lossless subtitle-strip intermediate is 148,910,513 bytes, versus the old 1,029,431,357-byte full-frame intermediate. The first subtitle attempt saved valid OCR but failed parsing rational `25/1` FPS after 444.340 s. A `Fraction` fix and rational-FPS regression were added; the downstream retry reused source/ROI/version-validated OCR and completed repair in 1,193.987 s. No real provider result was fabricated.

The job is currently at `awaiting_review`, after actual subtitle repair and before engineering export approval. A subsequent Docker Desktop start failed on the existing `sailor-ingest.sock` / `.stale` runtime files. The task explicitly requires approval before deleting Docker sockets or runtime state. Final export, final loudness/true peak, final decode/pixel collector, production browser playback and new completed-job restart checks remain pending recovery. A previous completed-job API/download check passed earlier during this phase; it does not establish current service availability.

## Automated validation

Backend: **70 passed**, one Starlette/httpx deprecation warning. Ruff passed. Frontend: one unit test, typecheck and build passed; three fixture browser tests passed with two production/private tests skipped. The final private production rerun is pending the running service and completed output. Installed-graph Python security audit found no known vulnerabilities; the pinned Argos upstream build and spaCy model wheel lack matching PyPI audit coverage and remain explicitly disclosed. npm audit against the official registry found zero vulnerabilities. Local production/test Docker builds passed before the current host runtime outage.

New regressions cover mask validation and exact boundaries, masks spanning a scene cut, CJK outlined detection, white-on-white captions, moving foreground, scene-local restoration, unchanged unmasked pixels, cache invalidation, project glossary snapshots/fallback/provenance, source-only retranslation, bounded fitting, overlap classification, 48 kHz stereo rendering, limiter latency and collector preservation checks.

## Preservation and remaining review

Original SHA-256: `bb779354520eb5edd040910d970c41471235ad1f2b49e5d3d73abd3e9f1fc4d4`.
Input/snapshot SHA-256: `7d7d5f6d279a174c2c829a94271c1c5d2a937f833d39a756c17b7d258bcc5e9f`.
Preserved Phase 2.5 MP4 SHA-256: `533dd7f1a0b14a65802907edc238b806f31d323f30ed103ccb7a9854abd1c58a`.
All new media and model files remain ignored by Git. A protected manifest records the previous evidence files and input clip for final revalidation.

Human audio/video review remains `PENDING_HUMAN_REVIEW`. Long-film readiness is `PARTIAL`: the bounded strip bank and mixing reduce memory/disk costs, but a 60-second sample, stage-boundary cancellation, visible reconstruction defects and unverified audio quality cannot establish two-hour readiness.
