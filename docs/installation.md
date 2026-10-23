# Installation

## Windows 11 with Docker Desktop

Use Docker Desktop's Linux/WSL2 engine and PowerShell. The local checkout is required until a tested registry image has been published.

```powershell
Set-Location D:/workshop/oct/offline-dub-studio
docker compose build
docker compose up -d
docker compose ps
Start-Process http://localhost:7860
```

The first image build installs a Python 3.12 CPU runtime, FFmpeg/libass, Chinese Tesseract data, espeak-ng, and CPU PyTorch. The model packs are separate downloads. Expect the image to use several GB. `docker compose logs -f dub-studio` shows service diagnostics; errors returned in the browser are concise.

Persistent folders are created alongside the checkout:

- `./data/inbox`: place long videos here; import them through the UI.
- `./data/uploads`: uploaded media.
- `./data/jobs`: checkpoints, transcript, stems, logs, and previews.
- `./data/output`: finished MP4 files.
- `./models`: ASR, Kokoro, Argos, and Demucs data.

All are ignored by Git. Do not place tokens, private movie files, or model weights in tracked source folders.

## Container controls

```powershell
docker compose logs --tail 100 dub-studio
docker compose restart dub-studio
docker compose down
```

`docker compose down` preserves the bind-mounted `data` and `models` folders. Do not run `docker compose down -v` if you want to preserve data.

The app is published only on host loopback at port 7860. Compose reserves 8 CPU cores and 16 GB memory by default. Adjust those values in `docker-compose.yml` if Docker Desktop is configured with less memory or you want a smaller CPU limit.
