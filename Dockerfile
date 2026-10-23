FROM node:22.15-alpine AS frontend-build
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/studio/backend \
    APP_HOST=0.0.0.0 \
    APP_PORT=7860 \
    DATA_DIR=/data \
    MODELS_DIR=/models \
    HF_HOME=/models/huggingface \
    HUGGINGFACE_HUB_CACHE=/models/huggingface/hub \
    TORCH_HOME=/models/torch \
    ARGOS_PACKAGES_DIR=/models/argos \
    ARGOS_DEVICE_TYPE=cpu \
    HF_HUB_DISABLE_TELEMETRY=1 \
    DO_NOT_TRACK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg tesseract-ocr tesseract-ocr-chi-sim espeak-ng fonts-liberation fonts-noto-cjk \
      libsndfile1 libgomp1 libglib2.0-0 ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && ffmpeg -hide_banner -filters 2>&1 | grep -q ' ass ' \
    && tesseract --list-langs 2>&1 | grep -q chi_sim

WORKDIR /opt/studio
COPY backend/requirements.lock.txt ./backend/requirements.lock.txt
RUN python -m pip install --no-cache-dir --upgrade pip==26.2.2
RUN python -m pip install --no-cache-dir torch==2.14.1 torchaudio==2.11.0 \
    --index-url https://download.pytorch.org/whl/cpu
RUN python -m pip install --no-cache-dir -r backend/requirements.lock.txt \
    && python -m pip check
COPY backend/ ./backend/
COPY scripts/ ./scripts/
COPY docs/ ./docs/
COPY README.md LICENSE ./
COPY docker-entrypoint.sh ./docker-entrypoint.sh
COPY --from=frontend-build /ui/dist ./frontend/dist

RUN apt-get update && apt-get install -y --no-install-recommends iptables gosu \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 10001 studio \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin studio \
    && mkdir -p /data/inbox /data/uploads /data/jobs /data/output /models \
    && chown -R 10001:10001 /opt/studio /data /models \
    && chmod 0755 /opt/studio/docker-entrypoint.sh

USER 0:0
ENTRYPOINT ["/opt/studio/docker-entrypoint.sh"]
EXPOSE 7860
VOLUME ["/models", "/data"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7860/healthz', timeout=3)" || exit 1
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]

FROM runtime AS test
ENTRYPOINT []
USER root
RUN python -m pip install --no-cache-dir pytest==9.1.1 httpx==0.28.1 ruff==0.17.2 pip-audit==2.10.1
COPY --chown=10001:10001 backend/tests/ ./backend/tests/
USER 10001:10001
CMD ["python", "-m", "pytest", "-q", "/opt/studio/backend/tests"]
