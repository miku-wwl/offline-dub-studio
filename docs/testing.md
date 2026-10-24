# Testing

## Phase 2.6 quality workflow

Phase 2.5 results below are historical. Phase 2.6 uses a new job and ignored `data/acceptance/phase-2.6/`, preserving the original source, input clip, all previous evidence and completed job records. See [PHASE26_QUALITY_REPORT.md](PHASE26_QUALITY_REPORT.md) for measured final results and comparison limits.

Current local Phase 2.6 results: **70 backend tests passed** (one Starlette/httpx deprecation warning), Ruff passed, **one frontend unit test passed**, typecheck/build passed, **three fixture browser tests passed / two production-private tests skipped**. Python installed-graph and official-registry npm vulnerability checks passed with the documented upstream-build audit gaps. Production/test image builds passed before the subsequent Docker Desktop socket failure. Final private-output browser/restart checks and the post-export collector remain pending; CI results must be tied to the delivered commit, not the Phase 2.5 run.

Independent native pre-export evidence (`preexport-validation.json`, `preexport-audio-report.json`) verifies all 1,500 repaired frames, zero changed unmasked pixels, 277 unchanged inactive frames, all 146 protected entries and the original source hash. Actual dialogue/background WAVs are stereo 48 kHz without PCM clipping; 25 fitted voices are non-silent at 48 kHz. This scope deliberately excludes final MP4/AAC validation, which is pending export.

The new regressions cover finite/bounded explicit mask intervals, actual outlined Chinese recognition on white backgrounds, subtitle appearance/disappearance, a moving object, negative/positive tracking caches, scene resets, active masks crossing a cut, exact unmasked pixels in the lossless strip, project glossary snapshots, corrupted glossary markers, translation override provenance, source-edit invalidation, duration budgets, bounded fitting, 24→48 kHz resampling, actual FFmpeg 48 kHz stereo export, limiter sample alignment, and acceptance-report preservation/collision helpers. Existing tests remain enabled.

```powershell
docker build --pull=false --target runtime --tag ghcr.io/miku-wwl/offline-dub-studio:local .
docker compose up -d --force-recreate --no-deps dub-studio
docker build --pull=false --target test --tag ghcr.io/miku-wwl/offline-dub-studio:phase26-test .
docker run --rm --network none --env DATA_DIR=/tmp/p26-tests --env MODELS_DIR=/tmp/p26-models ghcr.io/miku-wwl/offline-dub-studio:phase26-test
docker run --rm --entrypoint python ghcr.io/miku-wwl/offline-dub-studio:phase26-test scripts/audit_dependencies.py
docker exec offline-dub-studio python -m pip check
Set-Location frontend
npm test
npm run typecheck
npm run build
$env:LIVE_APP_URL='http://127.0.0.1:7860'
$env:LIVE_ACCEPTANCE_JOB_ID='dc04452a-410e-425f-b950-afe1a7a86895'
npm run test:e2e
npm audit --registry=https://registry.npmjs.org --audit-level=high
```

Project terminology: `GET/PUT /api/v1/project/translation` with `{"glossary":{"旗手":"flag bearer"}}`. New jobs snapshot the current glossary, with per-job `translation_glossary` taking precedence. Editing project settings does not mutate a running job's snapshot. `PUT /jobs/{id}/transcript` accepts optional `short_translation`; this selected version is spoken and captioned. Original Argos text, source edits, full/short overrides and local-editor provenance remain recorded, with human approval separate. A source-only edit invalidates translation and later stages, removes a stale manual lock and resets transcript approval. English/speaker edits invalidate generated speech and later affected artifacts.

Explicit masks: `PUT /api/v1/jobs/{id}/temporal-masks` with `{"masks":[{"start_time":20,"end_time":21,"x":650,"y":970,"width":650,"height":80}]}`. Coordinates must fit the actual input and intervals are half-open, finite and within duration. These are forced masks, independent of OCR. The existing `/subtitle-regions` endpoint remains a search constraint. `GET /jobs/{id}/preview-frame?time=20` returns the actual source PNG for selection. Both mask edits invalidate the subtitle/render stages and require a new preview approval.

Stage receipts record dependency fingerprints and immutable output hashes. Editable reviewed transcripts have an independent raw-ASR copy; changed source, text, voice, duration budget, style, masks or algorithm version invalidate relevant work. Subtitle OCR additionally checks source SHA/ROI/version; repair reuse checks source, intervals, mode, version and output SHA. No corrupted/replaced repair cache is accepted by the regression.

The Phase 2.6 collector performs no inference and is run only after the actual API job completes:

```powershell
docker run --rm --network none --entrypoint python --volume 'D:\workshop\oct\offline-dub-studio:/workspace:ro' --volume 'D:\workshop\oct\offline-dub-studio\data:/data' --env PYTHONPATH=/workspace/backend ghcr.io/miku-wwl/offline-dub-studio:local /workspace/scripts/compare_quality.py --job-id dc04452a-410e-425f-b950-afe1a7a86895 --evidence /data/acceptance/phase-2.6 --source /workspace/test.webm --clip /data/inbox/test-60s.mp4 --previous /data/acceptance/phase-2.5/dubbed-60s.mp4 --expected-source-sha256 bb779354520eb5edd040910d970c41471235ad1f2b49e5d3d73abd3e9f1fc4d4
```

It checks all protected Phase 2.5 hashes, the source/snapshot, complete output decode, codecs/rate/channels/fps/duration/DTS, non-silent and consistently assigned voices, audio levels and detailed timing. It reconstructs each pre-burn frame from the original plus the lossless strip and compares every unmasked pixel. Actual source/old/new frames at 20/42/54 seconds and readable comparison crops are exported. OCR cannot establish natural reconstruction; human review remains required. CI intentionally excludes private video/models; local private-output E2E and recovery checks must be recorded separately.

## Automated checks

The backend tests cover owned upload/snapshot cleanup, invalid/unsupported/interrupted inbox preservation, unchanged import hashes, collision-safe publication, temporal Chinese OCR across scene changes and moving objects, pixel-identical inactive frames, ASS/SRT timing and wrapping, bounded audio mixing and truncation diagnostics, OpenMP isolation, empty-ASR failures, speaker edits, review gates, cancellation, and cached stage recovery. Frontend tests cover dashboard rendering; Playwright opens the UI in Chromium with API fixtures. Those fixture-driven browser checks do not prove a real full conversion.

```powershell
docker compose build
docker compose --profile test run --build --rm --no-deps dub-studio-tests
docker compose --profile test run --rm --no-deps dub-studio-tests python -m ruff check --select E4,E7,E9,F backend/app backend/tests
Set-Location frontend
npm ci
npm test
npm run typecheck
npx playwright install chromium
npm run test:e2e
```

The Docker CI job builds the production image, checks `/healthz`, keeps the container running for the live browser check, and cleans up in an `always()` step. No release tag or image publication is part of Phase 2.5.

CI also runs `ruff` on the backend and audits the exact installed Python package versions from `backend/requirements.lock.txt`. The PyTorch CPU wheels carry a `+cpu` local suffix that the PyPI advisory resolver does not recognize, so their corresponding upstream base versions are audited in `backend/requirements-torch-audit.txt`. Argos Translate is pinned to upstream commit `17ed1a9b055c5ba1b51d76b683bbb0c64e2a4a88`. The application injects a local punctuation-based sentence splitter into the pinned Argos translation object; this keeps sentence chunking independent of model downloads. It does not call MiniSBD or download MiniSBD models. Argos still declares MiniSBD 0.9.5 as a transitive dependency, so the AGPL-3.0 package remains in the image and any future redistribution needs a license/source-compliance review. The spaCy `en_core_web_sm` model is hash-pinned from its official release wheel and baked into the image for offline Kokoro initialization. `pip-audit` skips the Argos commit and spaCy model wheel because neither exact build is published on PyPI; the scan prints those skip reasons while auditing PyPI packages and PyTorch versions.

`av==18.1.0` is intentionally pinned because Faster-Whisper 1.2.1 passes `metadata_errors` to `av.open`, and PyAV 19 removed that parameter. The audio decoder regression test ensures this API path remains exercised.

Demucs input continues through its FFmpeg-based audio reader. Its stem writer uses the app's SoundFile adapter because the pinned Torchaudio 2.11 writer routes through optional TorchCodec; a stereo PCM regression test covers the adapter.

## Real inference and media acceptance

This checkout has a locally generated 35.93-second integration fixture made from three Google FLEURS `cmn_hans_cn` dev recordings, a low-level tone bed, and burned-in Chinese text. The source recordings are licensed CC BY 4.0; the test used revision `70bb2e84b976b7e960aa89f1c648e09c59f894dd`. See the [FLEURS dataset card](https://huggingface.co/datasets/google/fleurs) and [CC BY 4.0 terms](https://creativecommons.org/licenses/by/4.0/). The source archive and generated MP4 live under ignored `data/fixtures` and `data/inbox`; they are not included in Git or the Docker build context.

The real local CPU run recognized three timestamped Chinese segments, translated them with Argos, synthesized them with Kokoro, separated stems with Demucs, detected and inpainted the burned subtitle region, and rendered an MP4 with mixed audio and burned English captions. The fixture has a static background and repeated read speech; it verifies the local inference path, not film-quality speaker recognition, dialogue separation, or subtitle reconstruction. This is historical fixture evidence. Phase 2.5 uses the supplied real `test.webm`; see [real-video acceptance](REAL_VIDEO_ACCEPTANCE.md). Its subjective quality remains `PENDING_HUMAN_REVIEW`.


## Phase 2.5 commands and evidence

The supplied real video is never a regression fixture. Only generated media are used in automated tests. `test.webm`, clips, stems, voices, outputs, and models are excluded from Git and the Docker build context.

```powershell
# Production build and startup, after model initialization.
docker build --pull=false --target runtime --tag ghcr.io/miku-wwl/offline-dub-studio:local .
docker compose up -d --force-recreate dub-studio
docker exec offline-dub-studio python -m pip check

# Build the test target with the same patched runtime dependencies.
docker build --pull=false --target test --tag ghcr.io/miku-wwl/offline-dub-studio:phase25-test .
docker run --rm --network none --env DATA_DIR=/tmp/p25-tests --env MODELS_DIR=/tmp/p25-models ghcr.io/miku-wwl/offline-dub-studio:phase25-test
# Auditing needs internet for advisory data; inference does not.
docker run --rm --entrypoint python ghcr.io/miku-wwl/offline-dub-studio:phase25-test scripts/audit_dependencies.py

Set-Location frontend
npm test
npm run typecheck
npm run build
$env:LIVE_APP_URL='http://127.0.0.1:7860'
$env:LIVE_ACCEPTANCE_JOB_ID='e47f9f3b-7236-4afe-8548-f1295d497e43'
npm run test:e2e
npm audit --registry=https://registry.npmjs.org --audit-level=high
```

Results on implementation commit `039dae17044254d4c8a20f3370c3ece166c393bc`: GitHub backend **46 passed** (one Starlette/httpx deprecation warning), Ruff and both Python audits passed; frontend unit **1 passed**, typecheck/build and npm audit passed. Local earlier Docker runs had 44 backend tests before the last two regressions; the final 46-test source suite was verified on GitHub. `filelock==4.2.1` replaces vulnerable 3.32.3; no vulnerability identifiers are suppressed. The two upstream direct builds (Argos and the spaCy language wheel) are explicitly reported as unavailable to the PyPI audit, while their immutable URLs/checksums remain pinned.

The final local UI unit/type/build checks passed; its fixture-driven browser tests were **2 passed / 2 skipped** without a running Docker service. GitHub's frontend job likewise runs two fixtures and skips the live-only checks; the production smoke job adds the live container dashboard check. Private video and models are never uploaded to CI, so its real-output playback test is intentionally skipped there.

[Implementation CI run 40060528459](https://github.com/miku-wwl/offline-dub-studio/actions/runs/40060528459) completed successfully on `039dae1`: backend, frontend, and production Docker smoke all passed. Production browser results were **3 passed / 1 skipped** (the private-video test). The following documentation commit's runner stalled over ten minutes in system dependency installation. The install now has bounded network retries/timeouts, a 60-second package-lock wait and a ten-minute step limit; failures still fail CI. The delivery response and ignored `delivery.json` identify the separately verified final CI run.

The first local real-output production-browser attempt reproduced the sparse-summary crash. The fix and sparse-response regression are committed, but the local real-output E2E rerun and actual completed-job restart lookup were blocked by Docker Desktop failing before its engine starts: `sailor-ingest.sock` cannot be renamed/accessed. Normal stop/start failed; official CLI forced exit succeeded, but restart reproduced the same socket failure. Automatic approval rejected deleting that runtime socket. With Docker stopped, socket-only directories were instead renamed and preserved. The first error cleared, but a fresh `docker-secrets-engine/engine.sock` still failed at startup. Preserved directory paths and exact attempts are in ignored `local-runtime-blocker.json`. No Docker reset or disk deletion was performed. Restore Docker Desktop, then rerun the command above and check the job download after `docker compose restart dub-studio`.

As independent media evidence, ignored `direct-playback.cjs` opened the actual final MP4 directly in Chromium, muted playback advanced beyond 0.5 s, duration was 60 s, dimensions 1920×1080, readyState 4 and media error null. It saved actual final-frame screenshots at 10 and 50 s. This proves private-file browser decoding; it does not assert production UI or post-restart API success and does not count as listening. The final delivery records these limits separately.

A generated two-second navy/tone fixture separately exercised the real API's queued cancel -> resume -> cancel lifecycle while the real-video job was busy. No inference stages executed for that fixture and its source hash was preserved. Restart/interrupted-stage and valid-cache recovery are regression-tested. Post-restart access to this real completed job remains pending the Docker Desktop recovery described above.

Jobs created from the browser now pause at `awaiting_transcript_review`. API clients opt in with `transcript_review_required=true`, save edits using `PUT /jobs/{id}/transcript` and `/speakers`, and continue using `POST /jobs/{id}/approve-transcript`. The existing subtitle preview and `approve-subtitles` gate remain separate. `POST /jobs/{id}/retry-stage` with `{"stage":"transcribe"}` invalidates that stage and its downstream stages while retaining successful earlier artifacts. Active jobs reject stage retries.

`performance.json` records high-resolution stage attempt times and cgroup peak memory where available. `scripts/validate_acceptance.py` collects the output, stems, voices, transcript, translation, voice assignments, ASS/SRT, previews, FFprobe data, loudness, and interval diagnostics. It verifies source/snapshot hashes, full output decode, monotonic DTS, dimensions/codecs/durations, non-silent synthesized tracks, consistent assigned voices, clipping, caption intervals, and every inactive frame in the lossless subtitle intermediate. It records timing collisions separately from media-integrity PASS. It does not listen or grant subjective approval.
