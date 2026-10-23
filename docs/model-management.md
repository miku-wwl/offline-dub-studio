# Model management

Model downloads are started from the browser's **Model readiness** panel. All providers use persistent storage under `/models`; inference adapters select CPU execution and fail with a visible readiness error when required weights are missing. There is no hosted inference fallback.

| Pack | Source and pinned revision | Approximate size | Use |
|---|---|---:|---|
| CPU Lite ASR | `Systran/faster-whisper-tiny`, `d90ca5fe260221311c53c58e660288d3deb8d356` | 75 MB | Mandarin ASR, CTranslate2 `int8` |
| Balanced ASR | `Systran/faster-whisper-small`, `536b0662742c02347bc0e980a01041f333bce120` | 500 MB | Mandarin ASR, CTranslate2 `int8` |
| Translation | Official Argos package `translate-zh_en` version `1.9` | 50–200 MB | Offline translation; installed package version and checksum are recorded after setup |
| English TTS | `hexgrad/Kokoro-82M`, `f3ff3571791e39611d31c381e3a41a3af07b4987` | 363 MB | Kokoro English voice packs, CPU inference |
| Separation | Demucs `htdemucs` pretrained checkpoint | 80–300 MB | Music-vocal source split, not film-dialogue separation |

Initialization requires internet access. ASR and Kokoro snapshots use fixed Hugging Face commit IDs; SHA-256 hashes for downloaded files are written in each pack's `pack-manifest.json`. Argos follows the official package index and records the selected package metadata and installed file hashes. Demucs checkpoints are downloaded by its CPU loader and hashed after warm-up.

Approximate sizes are upstream estimates and can vary with cache files. This image does not redistribute model weights. Model and package terms remain attached to the downloaded artifacts.

To inspect readiness, use the browser or:

```powershell
Invoke-RestMethod http://localhost:7860/api/v1/models | ConvertTo-Json -Depth 6
Invoke-RestMethod http://localhost:7860/api/v1/diagnostics | ConvertTo-Json -Depth 6
```
