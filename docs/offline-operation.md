# Offline operation

## Prepare once while online

1. Start the application with the normal Compose network.
2. Initialize the chosen ASR pack, Argos Chinese-to-English, Kokoro English TTS, and Demucs.
3. Confirm every required pack reports **Ready** and inspect its stored manifest.
4. Stop the container and set offline mode in a project `.env` file:

```powershell
@'
OFFLINE_INFERENCE=true
OFFLINE_NETWORK=true
'@ | Set-Content -Encoding ascii .env
docker compose up -d --force-recreate
```

`OFFLINE_INFERENCE=true` sets Hugging Face/Transformers offline flags and prevents model initialization. `OFFLINE_NETWORK=true` installs an output firewall inside the application container, blocking all new outbound connections while allowing loopback health checks and replies to browser/API requests. The `.env` file is ignored by Git. Keep it in place for later restarts while operating offline.

## Verify

```powershell
Invoke-RestMethod http://localhost:7860/api/v1/health
Invoke-RestMethod http://localhost:7860/api/v1/diagnostics | ConvertTo-Json -Depth 5
```

The diagnostics response should say `offline_inference: true`; all model packs used by the selected profile should be ready. Check external access from inside the container with `docker compose exec dub-studio python -c "import urllib.request; urllib.request.urlopen('https://huggingface.co', timeout=5)"`; that request should fail while the localhost health request above succeeds. Docker image pulls and model downloads must happen before entering offline mode.

To restore online mode, remove `.env` and recreate the service: `Remove-Item .env; docker compose up -d --force-recreate`.
