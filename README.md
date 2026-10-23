# Offline Dub Studio

Local-first Chinese-to-English video dubbing. The application combines local CPU speech recognition, Argos translation, Kokoro English voices, an optional Demucs music-vocal split, editable speaker assignments, hard-subtitle review/inpainting, and English subtitle burn-in.

> The local CPU pipeline has completed an offline 35.9-second Mandarin fixture conversion, including ASR, Argos translation, Kokoro speech, Demucs stems, hard-subtitle processing, and burned English captions. This is sample-path evidence, not movie-quality acceptance. Automatic diarization, cinematic dialogue separation, and reliable subtitle reconstruction remain limited. No GHCR image has been published. See [implementation status](docs/IMPLEMENTATION_STATUS.md) and [acceptance report](docs/ACCEPTANCE_REPORT.md). The runtime image is several GB because it includes CPU PyTorch and FFmpeg.

## Quick start on Windows 11

Docker Desktop with its Linux/WSL2 engine is the only required host application.

```powershell
Set-Location D:/workshop/oct/offline-dub-studio
docker compose build
docker compose up -d
Start-Process http://localhost:7860
```

In **Model readiness**, initialize the selected ASR pack, Argos Chinese-to-English, Kokoro voices, and Demucs. Model files persist in `./models`; jobs, uploads, and exports persist in `./data`. Place large authorized MP4 files in `./data/inbox`, then import them from the browser.

The Compose port is bound to `127.0.0.1`. The default conversion profile is CPU-only. After all model packs finish initializing, strict offline operation is available by setting `OFFLINE_INFERENCE=true` and `OFFLINE_NETWORK=true` in a project-root `.env` file and recreating the container:

```powershell
@'
OFFLINE_INFERENCE=true
OFFLINE_NETWORK=true
'@ | Set-Content -Encoding ascii .env
docker compose up -d
```

The container output firewall blocks external traffic while the published localhost port remains available. Revert the two settings to `false` only if you need to download or update model packs. Argos includes MiniSBD 0.9.5 as a transitive AGPL-3.0 dependency; the app replaces its sentence-splitting adapter at runtime and does not load MiniSBD models. Review [model licenses](docs/model-licenses.md) before redistributing an image.

## Processing workflow

1. Upload a short MP4 or select a file in the mounted inbox.
2. Choose CPU Lite or Balanced, and choose Fast, Balanced, or no hard-subtitle removal.
3. Start the job and inspect the source/OCR mask/inpainting/English subtitle preview.
4. Inspect the preview and detected mask, adjust regions if needed, rebuild the preview, and approve export.
5. Review the final audio and video, edit transcript/speaker voices if needed, then download the MP4.

Demucs separates music vocals rather than cinematic dialogue. The output bed can lose effects, and the vocal stem can retain music. Automatic speaker diarization is not enabled: the transcript defaults to `speaker_1`; users can assign IDs and distinct stable voices manually. OpenCV inpainting is a baseline and can damage detail or miss text. These are reviewable limitations, not quality guarantees.

## 60-second sample from an authorized movie

Copy the movie into `D:/workshop/oct/offline-dub-studio/data/inbox/movie.mp4`. In PowerShell, replace the filename and start time as needed:

```powershell
docker compose exec dub-studio ffmpeg -y -ss 00:10:00 -i /data/inbox/movie.mp4 -t 60 -map 0:v:0 -map 0:a:0 -c:v libx264 -preset veryfast -crf 21 -c:a aac /data/inbox/movie-sample-60s.mp4
```

Refresh the inbox in the browser and import `movie-sample-60s.mp4`. Run the sample first; inspect recognition, translation, voices, retained sound, subtitle repair, and sync before processing the full movie. Once accepted, select `movie.mp4` from the inbox and repeat the workflow. A long movie can take hours on CPU; jobs and intermediate outputs are persistent.

## Local development and checks

Python 3.12, Node.js 22, and Docker are used in the container build. Local test commands are documented in [testing](docs/testing.md). Model initialization requires first-time internet access; after initialization, the app can run with all container egress blocked while local browser access remains available.

See [installation](docs/installation.md), [model management](docs/model-management.md), [offline operation](docs/offline-operation.md), [troubleshooting](docs/troubleshooting.md), [limitations](docs/limitations.md), [licenses](docs/model-licenses.md), and [release process](docs/release.md).
