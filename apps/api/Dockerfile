FROM python:3.11-slim AS builder

WORKDIR /app

# Build deps for crypto, wheels
RUN apt-get update && apt-get install -y \
    build-essential \
    libssl-dev \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip once
RUN pip install --upgrade pip

# --- Install core package (needed by API) ---
COPY core/pyproject.toml core/pyproject.toml
COPY core/src core/src
RUN pip install --no-cache-dir --prefix=/install /app/core

# --- Install agent package (runtime adapters used by API) ---
COPY agent/pyproject.toml agent/pyproject.toml
COPY agent/src agent/src
RUN pip install --no-cache-dir --prefix=/install /app/agent

# --- Install API package ---
COPY apps/api/pyproject.toml api/pyproject.toml
COPY apps/api /app/api
RUN pip install --no-cache-dir --prefix=/install /app/api

# ---------- Runtime ----------
FROM python:3.11-slim AS runtime

ARG BUILD_VERSION=build-local
ARG BUILD_SHA=
ARG BUILD_BRANCH=
ARG BUILD_AT=
ARG BUILD_RUN_NUMBER=
ARG BUILD_RUN_ATTEMPT=
ARG BUILD_RUN_URL=
ARG BUILD_TITLE=

ENV PYTHONUNBUFFERED=1
ENV RUN_MIGRATIONS_ON_STARTUP=1
ENV BUILD_VERSION=${BUILD_VERSION}
ENV BUILD_SHA=${BUILD_SHA}
ENV BUILD_BRANCH=${BUILD_BRANCH}
ENV BUILD_AT=${BUILD_AT}
ENV BUILD_RUN_NUMBER=${BUILD_RUN_NUMBER}
ENV BUILD_RUN_ATTEMPT=${BUILD_RUN_ATTEMPT}
ENV BUILD_RUN_URL=${BUILD_RUN_URL}
ENV BUILD_TITLE=${BUILD_TITLE}
WORKDIR /app

# Runtime libs for crypto + repo execution tooling
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    git \
    openssh-client \
    libssl3 \
    libffi8 \
    && rm -rf /var/lib/apt/lists/*

# Installed python packages
COPY --from=builder /install /usr/local

# Optional: include source for debugging / migrations
COPY apps/api/app /app/app
COPY apps/api/alembic /app/api/alembic
COPY apps/api/alembic.ini /app/api/alembic.ini
COPY core /app/core
# Optional: include agent assets (e.g., prompts)
COPY agent /app/agent

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
