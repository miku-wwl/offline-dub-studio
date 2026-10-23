# Release process

The target is `ghcr.io/miku-wwl/offline-dub-studio:v1.0.0`. It is a target only; this checkout has not published that image.

GitHub Actions runs backend/frontend checks, Playwright browser checks, dependency scans, and a Docker build/health smoke test. A `v*` tag starts a release workflow; its checks must pass before buildx publishes to GHCR using the workflow's `packages: write` permission. No repository permissions or visibility are changed by local code.

Before cutting `v1.0.0`, require actual CPU inference with every model pack, a real 30–60 second authorized movie sample, manual speaker mapping, hard-subtitle mask review, burned subtitle output, sync inspection, and offline Docker operation with browser access. Update `docs/IMPLEMENTATION_STATUS.md` and `docs/ACCEPTANCE_REPORT.md` from that evidence. Do not tag a partial implementation as a passed release.
