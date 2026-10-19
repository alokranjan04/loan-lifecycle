# ── Stage 1: deps ────────────────────────────────────────────────────────────
FROM python:3.11-slim AS deps

WORKDIR /app

# system deps for qdrant-client / numpy
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY prototype/web/requirements.txt requirements-web.txt
COPY prototype/loanagent/requirements.txt requirements-agent.txt 2>/dev/null || true

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements-web.txt

# ── Stage 2: runtime ─────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

WORKDIR /app

# non-root user
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser

# copy installed packages from deps stage
COPY --from=deps /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

# copy application
COPY prototype/ ./prototype/

# output directory (writable by app)
RUN mkdir -p /app/prototype/output /app/prototype/data/applications \
    && chown -R appuser:appgroup /app

USER appuser

# Cloud Run injects $PORT; default 8080
ENV PORT=8080 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/prototype

EXPOSE 8080

CMD ["sh", "-c", "uvicorn web.app:app --host 0.0.0.0 --port $PORT --workers 1"]
