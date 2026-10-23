# Acceptance report

Validation date: 2026-10-24 (Pacific/Auckland). The fixture conversion is an actual local CPU run with container egress blocked; it does not establish movie-quality performance.

```text
PROJECT=offline-dub-studio

PHASE_1_STATUS=PASS
PHASE_2_STATUS=PASS
PHASE_3_STATUS=PARTIAL
PHASE_4_STATUS=PARTIAL
PHASE_5_STATUS=PARTIAL
PHASE_6_STATUS=PARTIAL

DOCKER_BUILD_STATUS=PASS
FRONTEND_BUILD_STATUS=PASS
BACKEND_TEST_STATUS=PASS (17 passed)
FRONTEND_TEST_STATUS=PASS (1 passed)
BROWSER_E2E_STATUS=PASS (2 passed)
REAL_LOCAL_ASR_STATUS=PASS
REAL_LOCAL_TRANSLATION_STATUS=PASS
REAL_LOCAL_TTS_STATUS=PASS
AUDIO_SEPARATION_STATUS=PARTIAL (Demucs music-vocal split; not cinematic dialogue isolation)
SPEAKER_DIARIZATION_STATUS=PARTIAL (manual assignment only)
HARD_SUBTITLE_REMOVAL_STATUS=PARTIAL (OpenCV baseline processed; visible quality limitations)
SUBTITLE_BURN_IN_STATUS=PASS
FULL_PIPELINE_STATUS=PASS (35.934-second offline fixture job completed)
CPU_ONLY_STATUS=PASS
OFFLINE_INFERENCE_STATUS=PASS (ASR, Argos, Kokoro, Demucs, and API conversion with blocked egress)
JOB_RECOVERY_STATUS=PASS (completed job and output survived container restart)
GHCR_RELEASE_STATUS=NOT_RUN

REPOSITORY_URL=https://github.com/miku-wwl/offline-dub-studio
FINAL_COMMIT_SHA=see final delivery report
DOCKER_IMAGE=ghcr.io/miku-wwl/offline-dub-studio:local (local only; no GHCR publication)
TEST_COUNT=20 (17 backend + 1 frontend unit + 2 browser E2E)
KNOWN_LIMITATIONS=No automatic diarization; Demucs is not film-dialogue separation; OpenCV inpainting can smear image detail; fixture is read speech with a tone bed; MiniSBD 0.9.5 remains as an AGPL-3.0 transitive dependency and needs compliance review before redistribution; audio quality not human-listened
USER_ACTION_REQUIRED=Provide an authorized 30–60-second movie clip; inspect and accept sample voices, retained ambience, inpainting, sync, and audio level before full-film processing
OVERALL_STATUS=PARTIAL
```

## Implemented and verified

- Docker-first FastAPI/React application with SQLite jobs, persistent intermediate stages, upload/inbox import, cancellation/resume routes, model readiness, preview approval, and artifact download.
- CPU-local Faster-Whisper, Argos Translate, Kokoro, and Demucs adapters; no remote inference fallback. Argos sentence splitting is replaced at runtime with local punctuation-based splitting so translation does not trigger MiniSBD model downloads.
- OCR, subtitle-region review, OpenCV inpainting, editable ASS generation, and burned English captions.
- Container-level outbound firewall controlled by `OFFLINE_NETWORK`; Compose port remains available on `127.0.0.1:7860`.
- CI workflows, pinned runtime dependencies, model manifests, documentation, and a Docker production image built locally.

## Commands and results

- `docker build --pull=false --target runtime --tag ghcr.io/miku-wwl/offline-dub-studio:local .` — passed.
- `docker compose up -d --force-recreate dub-studio`; `Invoke-RestMethod http://127.0.0.1:7860/healthz` — passed.
- `docker exec --user 10001:10001 offline-dub-studio python /data/fixtures/offline_smoke.py` — real ASR, Argos, Kokoro, and Demucs completed in offline mode.
- Imported `fleurs-mandarin-36s-cc-by-test.mp4` through `/api/v1/media/import`; created job `b65032d4-253f-48d3-b424-aa4616886398`; reviewed its preview; approved test export; job completed.
- Output: `data/output/b65032d4-253f-48d3-b424-aa4616886398.mp4`, 341,405 bytes, 35.934 seconds, H.264/AAC. The downloaded API artifact had the same SHA-256 as the stored file.
- `pytest -q backend/tests` — 17 passed, one deprecation warning. Ruff CI selection — passed.
- `npm test` — 1 passed; `npm run typecheck` — passed; `npm run build` — passed; `LIVE_APP_URL=http://127.0.0.1:7860 npm run test:e2e` — 2 passed.
- `npm audit --registry=https://registry.npmjs.org --omit=dev` — 0 vulnerabilities.
- Job status and output persisted after `docker compose restart dub-studio`; offline OUTPUT firewall remained active.

## Remaining acceptance

- Phase 3 needs an ungated automatic diarization provider or an accepted user-gated model workflow.
- Phase 4 needs more diverse real subtitles and human assessment of masking/reconstruction, timing, and text detection.
- Phase 5 needs browser-driven end-to-end conversion through upload/configure/review/export, not only dashboard smoke plus API conversion.
- Phase 6 needs a clean-machine build and release review. No GHCR login, image push, tag, or publication was performed. The Argos transitive MiniSBD package remains AGPL-3.0; source and license obligations must be resolved before redistribution.
- User movie acceptance remains `PENDING_USER_MEDIA`.

## Run the application

```powershell
Set-Location D:/workshop/oct/offline-dub-studio
docker compose build
docker compose up -d
Start-Process http://localhost:7860
```

In **Model readiness**, initialize the selected ASR model, Argos Chinese-to-English, Kokoro English voices, and Demucs while online. Models persist under `./models`; jobs and exports persist under `./data`.

After initialization, use this project-root `.env` to enforce strict offline operation:

```powershell
@'
OFFLINE_INFERENCE=true
OFFLINE_NETWORK=true
'@ | Set-Content -Encoding ascii .env
docker compose up -d --force-recreate
```

Verify `offline_inference: true` in `/api/v1/diagnostics`, and confirm `http://localhost:7860/healthz` remains available.

## Import an authorized movie and run a 60-second sample

Copy an MP4 you are authorized to process into `D:/workshop/oct/offline-dub-studio/data/inbox/movie.mp4`. Extract a sample around a representative scene; substitute the timecode:

```powershell
docker compose exec dub-studio ffmpeg -y -ss 00:10:00 -i /data/inbox/movie.mp4 -t 60 -map 0:v:0 -map 0:a:0 -c:v libx264 -preset veryfast -crf 21 -c:a aac /data/inbox/movie-sample-60s.mp4
```

In the browser, refresh the inbox, import `movie-sample-60s.mp4`, choose Chinese → English and CPU Lite for the first run, choose a subtitle-removal mode, and start the job. Inspect the transcript, voices, audio bed, mask, repaired still, English caption, and sync. Approve export only after review, then play and listen to the downloadable MP4. If the sample is acceptable, select `movie.mp4` in the inbox and repeat the same workflow for the full film. Full-length CPU conversion may take hours; keep the container running and retain the persistent `data` and `models` folders.
