FROM python:3.12-slim AS base

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# System deps for psycopg[binary] wheels build fallback / healthcheck curl.
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system app && useradd --system --gid app --no-create-home app

# ---- dev: what docker-compose.yml actually runs locally ---------------------
# Bind-mounts the source tree and reloads on change (see docker-compose.yml's
# `volumes:` for backend) — stays root because the mounted files are
# host-owned, not container-owned, and a non-root container user buys nothing
# there while adding a real risk of permission errors against them.
FROM base AS dev

COPY requirements.txt requirements-dev.txt ./
RUN pip install -r requirements-dev.txt

COPY . .

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# ---- production: standalone image, no bind mount, no dev/test deps ---------
FROM base AS production

COPY requirements.txt ./
RUN pip install -r requirements.txt

# Only what the running app and its migrations need — no tests/, scripts/ is
# kept (the seed script is occasionally useful against a fresh prod DB too),
# and no requirements-dev.txt (no pytest/ruff/httpx in the shipped image).
COPY app ./app
COPY alembic.ini ./
COPY migrations ./migrations
COPY scripts ./scripts

RUN chown -R app:app /app
USER app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
