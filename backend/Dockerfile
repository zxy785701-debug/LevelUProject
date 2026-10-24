# Build context: backend/ (not the repository root).
# Cloud hosting service port must match EXPOSE and the Uvicorn port below.
FROM python:3.13-slim-bookworm AS builder

WORKDIR /build

# crcmod and other native dependencies may need a compiler. Keep it out of runtime.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.lock ./
RUN python -m venv /opt/venv \
    && /opt/venv/bin/python -m pip install --no-cache-dir --disable-pip-version-check -r requirements.lock \
    && /opt/venv/bin/python -m pip check

FROM python:3.13-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH="/opt/venv/bin:$PATH" \
    TZ=Asia/Shanghai

# ONNX/Chroma native libraries, HTTPS trust, and Asia/Shanghai timezone data.
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        ca-certificates libgomp1 libstdc++6 tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 levelup \
    && useradd --uid 10001 --gid levelup --create-home --shell /usr/sbin/nologin levelup

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY app/ ./app/
COPY migrations/ ./migrations/
COPY alembic.ini ./

# Writable scratch space only; cloud container files are not durable storage.
RUN mkdir -p /app/knowledge-data \
    && chown levelup:levelup /app/knowledge-data

USER 10001:10001
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/v1/health', timeout=3).close()"]

# Run migrations once before releasing traffic: python -m app.migrate
# A single foreground process receives termination signals directly.
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
