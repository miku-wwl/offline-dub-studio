# Architecture

Offline Dub Studio is a local single-user application. FastAPI owns the SQLite job ledger and a persistent, single-job worker. A React/Vite browser UI talks only to the local API. FFmpeg handles media inspection, extraction, and final muxing; the processing engine has replaceable ASR, translation, speech, separation, and OCR adapters.

```text
Browser (localhost:7860)
  -> FastAPI: uploads, inbox imports, job control, model readiness, artifacts
  -> SQLite: jobs, stage checkpoints, logs, speaker assignments
  -> persistent worker: inspect -> extract -> separate -> ASR -> translation
       -> TTS/timeline -> subtitle detect/inpaint -> ASS burn-in/mux
  -> /data: source media, durable stage artifacts, results
  -> /models: local model and translation package cache
```

The worker records each stage before and after work. Completed stage artifacts are durable and are reused when downstream work is re-run. Process restarts change `running` jobs to `interrupted`; users can resume them. A cancellation request is checked between bounded media/model operations and before export.

## Provider choices and limits

- ASR: Faster-Whisper, CPU `int8`, with a downloadable `small` model as the balanced default.
- Translation: Argos Translate installed Chinese-to-English package; no network provider fallback.
- TTS: Kokoro 82M with English voice IDs; initialized into persistent storage and run on CPU.
- Separation: optional Demucs two-stem vocals separation. This is music-vocal separation, not a film-dialogue separator; the resulting instrumental stem can contain lost effects and the vocal stem can retain music. Demucs's upstream repository is archived. The UI and reports call this a separation estimate.
- Diarization: manual speaker assignment is the honest default. A gated pyannote model is not downloaded or enabled automatically. Speaker IDs and voice assignments are editable and durable.
- Subtitle detection: optional Tesseract Chinese OCR sampled over time with reviewable boxes, plus manually supplied regions. OpenCV inpainting is a baseline and can leave visible artifacts or erase scene details. Subtitles may also be hard to distinguish from signs or credits.
- Subtitle rendering: generated ASS is burned by FFmpeg/libass; original soft subtitle streams are excluded from the output.

Local inference adapters have no remote inference fallback. First-time model initialization requires internet access; later inference uses the mounted model cache. A full movie quality result requires user-provided media and human review.

## Security and storage

The Compose port is published on `127.0.0.1` only. User paths are never passed through a shell: subprocess calls use argument arrays. Uploads are size-limited, written under UUID filenames, and accepted only after FFprobe confirms a video stream. Inbox imports resolve direct children of `/data/inbox`. Model downloads use fixed provider identities; users cannot submit download URLs.

`/data` contains inbox, uploads, working stages, and outputs. `/models` contains model snapshots and Argos packages. Neither directory is part of the source tree or Docker build context.
