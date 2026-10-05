# Production image for the FastAPI backend, Celery worker and Celery beat.
# Build context is the repo root:  docker build -f deploy/backend.Dockerfile .
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/cache/huggingface

WORKDIR /app

# libgomp1: needed by xgboost / torch on slim images
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgomp1 curl \
 && rm -rf /var/lib/apt/lists/*

# CPU-only torch first (the default wheel bundles ~3 GB of CUDA we don't need)
COPY backend/requirements.txt /tmp/requirements.txt
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu \
 && pip install -r /tmp/requirements.txt

# Run as a normal user (uid 1000 = the default 'ubuntu' user on the server,
# so the bind-mounted ./data folder is writable)
RUN useradd --uid 1000 --create-home app \
 && mkdir -p /cache/huggingface /app/data \
 && chown -R app:app /cache /app

COPY --chown=app:app backend ./backend
COPY --chown=app:app evals ./evals

USER app
EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD curl -fsS http://localhost:8001/health || exit 1

# Create tables / hypertable, then serve. (Worker and beat override this command.)
CMD ["sh", "-c", "python backend/scripts/init_db.py && exec uvicorn backend.main:app --host 0.0.0.0 --port 8001 --proxy-headers --forwarded-allow-ips=*"]
