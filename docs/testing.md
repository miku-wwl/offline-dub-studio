# Testing

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
npm run test:e2e
npm audit --registry=https://registry.npmjs.org --audit-level=high
```

Local results: 44 backend tests, 1 frontend unit test, 3 browser tests; typecheck/build, Ruff, `pip check`, and dependency audits passed. `filelock==4.2.1` replaces vulnerable 3.32.3; no vulnerability identifiers are suppressed. The two upstream direct builds (Argos and the spaCy language wheel) are explicitly reported as unavailable to the PyPI audit, while their immutable URLs/checksums remain pinned.

A generated two-second navy/tone fixture separately exercised the real API's queued cancel -> resume -> cancel lifecycle while the real-video job was busy. No inference stages executed for that fixture and its source hash was preserved. Restart/interrupted-stage and valid-cache recovery are also regression-tested. The real completed job is checked again after a container restart.

Jobs created from the browser now pause at `awaiting_transcript_review`. API clients opt in with `transcript_review_required=true`, save edits using `PUT /jobs/{id}/transcript` and `/speakers`, and continue using `POST /jobs/{id}/approve-transcript`. The existing subtitle preview and `approve-subtitles` gate remain separate. `POST /jobs/{id}/retry-stage` with `{"stage":"transcribe"}` invalidates that stage and its downstream stages while retaining successful earlier artifacts. Active jobs reject stage retries.

`performance.json` records high-resolution stage attempt times and cgroup peak memory where available. `scripts/validate_acceptance.py` collects the output, stems, voices, transcript, translation, voice assignments, ASS/SRT, previews, FFprobe data, loudness, and interval diagnostics. It verifies source/snapshot hashes, full output decode, monotonic DTS, dimensions/codecs/durations, non-silent synthesized tracks, consistent assigned voices, clipping, caption intervals, and every inactive frame in the lossless subtitle intermediate. It records timing collisions separately from media-integrity PASS. It does not listen or grant subjective approval.
