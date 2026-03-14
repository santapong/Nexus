# ── Dev stage (used by docker-compose with volume mounts) ──
FROM python:3.12-slim AS dev

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --no-cache-dir -e ".[dev]" 2>/dev/null || true

COPY . .
RUN pip install --no-cache-dir -e ".[dev]"

EXPOSE 8000
CMD ["uvicorn", "nexus.app:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# ── Production stage (no dev deps, smaller image) ──
FROM python:3.12-slim AS prod

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY nexus/ ./nexus/
COPY alembic/ ./alembic/
COPY alembic.ini ./

RUN pip install --no-cache-dir "." \
    && rm -rf /root/.cache/pip

RUN useradd --create-home appuser
USER appuser

EXPOSE 8000
CMD ["uvicorn", "nexus.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
