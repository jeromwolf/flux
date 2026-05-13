# Flux API container (FastAPI + SQLAlchemy 2.x async).
# Used by docker-compose's `api` service; not required for local dev.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# System deps for asyncpg/cryptography
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic

RUN pip install --no-cache-dir '.[api]'

EXPOSE 8000

# Apply migrations, then start uvicorn.
CMD ["sh", "-c", "alembic upgrade head && uvicorn flux.api.app:app --host 0.0.0.0 --port 8000"]
