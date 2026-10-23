# Model and dependency licenses

Licenses are tracked separately for application code, dependencies, and downloaded weights. This image does not copy third-party source into this repository or bundle downloaded model files. Users should review model-provider terms for their intended use before initializing a pack.

| Component | Code/package license | Model/data license or access note |
|---|---|---|
| Offline Dub Studio | MIT (repository) | Does not include weights |
| FastAPI and Starlette | MIT / BSD-3-Clause | Pinned Python packages; security-audited in CI |
| Faster-Whisper | MIT | Hugging Face `Systran/faster-whisper-{tiny,small}` cards say MIT; revisions are pinned in `models.py` |
| Argos Translate | MIT/CC0 dual license | Pinned upstream source commit; its Chinese-English language package has separate metadata/license and installed file hashes are recorded locally |
| Hugging Face Hub / Transformers | Apache-2.0 / Apache-2.0 | Pinned Python packages; model weights remain separately licensed |
| MiniSBD | AGPL-3.0 | Argos currently installs MiniSBD 0.9.5 as a transitive dependency. The app replaces Argos's sentence splitter before translation, so MiniSBD is not invoked and its models are not downloaded. Any future redistribution of the image requires a license/source-compliance review; this project has not published an image |
| Argos Translate | MIT | Pinned to upstream commit `17ed1a9b055c5ba1b51d76b683bbb0c64e2a4a88`; the app injects a local punctuation splitter and never invokes MiniSBD's model adapter |
| spaCy English pipeline model | MIT | `en_core_web_sm` 3.8.0 is hash-pinned for Kokoro English phonemization and installed in the image |
| Kokoro | Package is distributed separately | `hexgrad/Kokoro-82M` model card says Apache-2.0; revision is pinned |
| Demucs | MIT code; upstream repository is archived | Pretrained checkpoint provenance/terms are not independently established by this repo. Check upstream checkpoint notice and source data before commercial redistribution/use; this project does not redistribute it |
| Tesseract | Apache-2.0 | `chi_sim` trained data follows upstream language-data terms |
| FFmpeg | LGPL/GPL depending on build options | Debian binary build configuration is supplied by the distribution; check exact linked codec/filter configuration |
| PyTorch | BSD-style | CPU wheel is from official PyTorch index |
| python-multipart | Apache-2.0 | Used only for streaming browser uploads |

No gated model is accessed automatically. pyannote Community-1 is not downloaded because its Hugging Face access requires user-side terms/permissions; this version uses clearly labeled manual speaker assignment instead.
