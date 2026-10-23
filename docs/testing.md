# Testing

## Automated checks

The backend tests cover timeline placement/overlap warnings, ASS escaping/timestamps, SQLite persistence, media probe validation, upload/inbox safety, job-stage restart recovery, and API status/validation. Frontend tests cover dashboard rendering; Playwright opens the UI in Chromium with API fixtures. Those fixture-driven browser checks do not prove a real full conversion.

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

The Docker CI job separately builds the production image and checks `/healthz`. Release CI runs the checks before publishing a tag to GHCR.

CI also runs `ruff` on the backend and audits the exact installed Python package versions from `backend/requirements.lock.txt`. The PyTorch CPU wheels carry a `+cpu` local suffix that the PyPI advisory resolver does not recognize, so their corresponding upstream base versions are audited in `backend/requirements-torch-audit.txt`. Argos Translate is pinned to upstream commit `17ed1a9b055c5ba1b51d76b683bbb0c64e2a4a88`. The application injects a local punctuation-based sentence splitter into the pinned Argos translation object; this keeps sentence chunking independent of model downloads. It does not call MiniSBD or download MiniSBD models. Argos still declares MiniSBD 0.9.5 as a transitive dependency, so the AGPL-3.0 package remains in the image and any future redistribution needs a license/source-compliance review. The spaCy `en_core_web_sm` model is hash-pinned from its official release wheel and baked into the image for offline Kokoro initialization. `pip-audit` skips the Argos commit and spaCy model wheel because neither exact build is published on PyPI; the scan prints those skip reasons while auditing PyPI packages and PyTorch versions.

`av==18.1.0` is intentionally pinned because Faster-Whisper 1.2.1 passes `metadata_errors` to `av.open`, and PyAV 19 removed that parameter. The audio decoder regression test ensures this API path remains exercised.

Demucs input continues through its FFmpeg-based audio reader. Its stem writer uses the app's SoundFile adapter because the pinned Torchaudio 2.11 writer routes through optional TorchCodec; a stereo PCM regression test covers the adapter.

## Real inference and media acceptance

This checkout has a locally generated 35.93-second integration fixture made from three Google FLEURS `cmn_hans_cn` dev recordings, a low-level tone bed, and burned-in Chinese text. The source recordings are licensed CC BY 4.0; the test used revision `70bb2e84b976b7e960aa89f1c648e09c59f894dd`. See the [FLEURS dataset card](https://huggingface.co/datasets/google/fleurs) and [CC BY 4.0 terms](https://creativecommons.org/licenses/by/4.0/). The source archive and generated MP4 live under ignored `data/fixtures` and `data/inbox`; they are not included in Git or the Docker build context.

The real local CPU run recognized three timestamped Chinese segments, translated them with Argos, synthesized them with Kokoro, separated stems with Demucs, detected and inpainted the burned subtitle region, and rendered an MP4 with mixed audio and burned English captions. The fixture has a static background and repeated read speech; it verifies the local inference path, not film-quality speaker recognition, dialogue separation, or subtitle reconstruction. Movie acceptance stays `PENDING_USER_MEDIA` until an authorized user clip is supplied.
