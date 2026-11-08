# Research Tracker (paper_universe) — one container serving UI + API on port 8000.
# Model weights are downloaded and verified at build time, so the container runs offline-ready.

# ---------- 1) frontend build ----------
FROM node:24-bookworm-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------- 2) runtime ----------
FROM python:3.13-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

# Download the pinned embedding model into /app/models before copying code, so code changes reuse this layer.
ARG EMBED_MODEL=sentence-transformers/all-MiniLM-L6-v2
ARG EMBED_REVISION=1110a243fdf4706b3f48f1d95db1a4f5529b4d41
RUN python -c "from sentence_transformers import SentenceTransformer as S; S('${EMBED_MODEL}', revision='${EMBED_REVISION}', cache_folder='/app/models', device='cpu')"

COPY backend/ backend/
COPY config.example.yaml .env.example ./

# Verify the model the app is configured for loads from the image alone (no network) and gives sane
# keywords/embeddings; fails if settings point to a model/revision that was not baked in above.
RUN cd backend && HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python -m app.keywords

COPY --from=frontend /app/frontend/dist frontend/dist

# Image version reported by /api/model (CI passes sha-<commit>); last so it never busts the cache above.
ARG APP_VERSION=dev
ENV APP_VERSION=${APP_VERSION}

# Runtime state lives in volumes; run as an unprivileged user.
RUN useradd --create-home --uid 1000 app && mkdir -p data logs notes && chown -R app:app data logs notes
USER app
VOLUME ["/app/data", "/app/notes", "/app/logs"]
ENV HF_HUB_OFFLINE=1
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/status', timeout=4)"
CMD ["python", "-m", "uvicorn", "app.main:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8000"]
