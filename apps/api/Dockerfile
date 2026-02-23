# ---------- Builder ----------
FROM python:3.11-slim AS builder

WORKDIR /app

# Install build deps for crypto
RUN apt-get update && apt-get install -y \
    build-essential \
    libssl-dev \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy only dependency files first (better caching)
COPY apps/api/pyproject.toml /app/pyproject.toml

# Install dependencies
RUN pip install --upgrade pip
RUN pip install --prefix=/install .

# ---------- Runtime ----------
FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1
WORKDIR /app

# Runtime libs for crypto
RUN apt-get update && apt-get install -y \
    libssl3 \
    libffi8 \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages
COPY --from=builder /install /usr/local

# Copy app source
COPY apps/api/app /app/app
COPY core /app/core

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
