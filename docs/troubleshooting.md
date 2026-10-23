# Troubleshooting

## Browser says the local service is unavailable

Check `docker compose ps` for a healthy container and `docker compose logs --tail 100 dub-studio`. Confirm port 7860 is not in use and Docker Desktop has enough memory.

## Model initialization fails

Check Docker has internet access, free space under `./models`, and `OFFLINE_INFERENCE` is false. Retry the individual pack after the connection is restored. Partial files stay in the model cache; the manifest is written only after readiness verification.

## Conversion says a model is missing

Initialize the selected ASR profile and all required translation/TTS/separation packs. `Resume` restarts at the failed stage and reuses completed stage artifacts.

## FFmpeg cannot read the video

The app validates the actual streams with FFprobe. Re-export a supported H.264/AAC MP4 and make sure it has an audio stream. The UI limits upload size; placing large files in `./data/inbox` avoids the browser upload limit.

## Chinese subtitles remain or the picture looks damaged

The OCR is sampled and may miss stylized text, signs, or scene-dependent subtitle locations. Inspect the source/mask/repaired previews, drag a manual region over missed subtitles, and rebuild before approval. OpenCV inpainting cannot recover the original pixels underneath burned text.

## Background music or effects change

Demucs vocal/music separation is an approximation. The model is not trained as a film dialogue/effects separator; listen to the mixed-audio preview. Lower background gain if residual Mandarin is audible, or accept reduced music/effect preservation.

## Jobs show Interrupted

The job and completed stage records persist in SQLite. Select the job and choose `Resume`; successful artifacts are reused. If an artifact file was removed manually, the affected stage runs again or reports the missing prerequisite.
