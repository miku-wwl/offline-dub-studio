# Implementation status

Validated on 2026-10-24 in the local Windows/Docker Desktop workspace. `PASS` means the stated acceptance behavior ran; it does not claim movie-quality output.

| Phase | Status | Evidence and remaining work |
|---|---|---|
| 1. Foundation and Docker | PASS | Production image built locally; Compose health check and localhost API passed. Inbox import, job processing, container restart, and persisted job/output lookup passed. |
| 2. Speech translation and audio | PASS | A 35.934-second Mandarin fixture ran on CPU with actual Faster-Whisper, Argos, Kokoro, and Demucs inference while container egress was blocked. H.264/AAC MP4 was exported and downloaded. Movie dialogue suppression and sound-bed quality are not established by this read-speech fixture. |
| 3. Speakers | PARTIAL | Manual speaker IDs and persistent voice selections are implemented. Automatic diarization and overlap detection are not integrated; no pyannote access terms were accepted. |
| 4. Subtitle processing | PARTIAL | OCR located and OpenCV processed the fixture's hardcoded text, review previews were inspected, and English captions were burned into the export. The OpenCV baseline visibly smears detail and has not been accepted on movie footage. |
| 5. Web application | PARTIAL | Dashboard/browser E2E, API job creation, review gate, approval, and artifact download passed. The full Upload → Configure → Process → Preview → Download sequence has not been exercised end-to-end solely through browser actions. |
| 6. Packaging and release | PARTIAL | Local CPU image, Compose setup, pinned packages, model manifests, offline firewall, tests, and release workflow are present. No GHCR image or `v1.0.0` release was published. MiniSBD remains an AGPL-3.0 Argos transitive dependency; redistribution needs a compliance review. |

## Verified evidence

- Local image: `ghcr.io/miku-wwl/offline-dub-studio:local`; build command: `docker build --pull=false --target runtime --tag ghcr.io/miku-wwl/offline-dub-studio:local .`.
- Local service: `docker compose up -d --force-recreate dub-studio`; `/healthz` and `/api/v1/health` returned `status=ok`.
- Browser: `LIVE_APP_URL=http://127.0.0.1:7860 npm run test:e2e` — 2 passed while `OFFLINE_NETWORK=true`.
- Backend: mounted current source into the pinned Python 3.12 test image and ran `pytest -q backend/tests` — 17 passed, one Starlette/httpx deprecation warning. CI Ruff selection passed.
- Frontend: `npm test` — 1 passed; typecheck and production build passed; Playwright — 2 passed; `npm audit --registry=https://registry.npmjs.org --omit=dev` found 0 vulnerabilities.
- Offline provider smoke (`data/fixtures/offline_smoke.py`): tiny ASR recognized `西班牙人開始了長達3個世紀的殖民時期`; Argos translated it to `The Spanish began three centuries of colonization.`; Kokoro generated 3.425 seconds of English audio; Demucs produced both `vocals.wav` and `no_vocals.wav`.
- Offline API conversion: job `b65032d4-253f-48d3-b424-aa4616886398`, using `data/inbox/fleurs-mandarin-36s-cc-by-test.mp4`; reached subtitle review, was approved for QA, and completed. Output is `data/output/b65032d4-253f-48d3-b424-aa4616886398.mp4` (35.934 s, H.264 640×360 at 15 fps, AAC). API download SHA-256 matched the file: `FFF26E7541824C6B8877E7FF6875E0B556509A90A0ACB92D223F7116461DBDCE`.
- Job and output remained available after `docker compose restart dub-studio`. The firewall still showed `OUTPUT DROP`, loopback allow, and established-connection allow; localhost health stayed available.
- Fixture provenance and its CC BY 4.0 source archive are recorded in [testing](testing.md). Generated media and downloaded weights remain ignored by Git.

## Known limits

- No automatic diarization, film-dialogue isolation, voice cloning, or reliable overlapping-speaker assignment.
- Demucs separates music/vocal content and does not reliably isolate movie dialogue; the output bed can lose ambience and effects.
- OCR/OpenCV inpainting is a fast baseline. The inspected still has a residual smear near the lower edge.
- Audio measurement on the sample export was mean `-39.1 dB`, peak `-16.4 dB`; this is not a human listening assessment.
- The fixture has read speech, a tone bed, and static imagery. Movie acceptance remains `PENDING_USER_MEDIA`.
- The GitHub release workflow exists, but no registry login, tag, image push, or GHCR release was performed. MiniSBD's AGPL-3.0 transitive dependency needs source/license review before image redistribution.
