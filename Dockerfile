# syntax=docker/dockerfile:1

# ── Build stage ─────────────────────────────────────────────────────────────
FROM python:3.11-slim AS build
WORKDIR /app

# system deps for building any wheels
RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential && \
    rm -rf /var/lib/apt/lists/*

# 1) Copy only the files needed to install dependencies
COPY pyproject.toml poetry.lock ./

# 2) Copy your package code so Poetry can see the "app" module
COPY app ./app
COPY alembic.ini ./
COPY migrations ./migrations
COPY scripts ./scripts

# 3) Install runtime deps only (no dev)
RUN pip install poetry && \
    poetry config virtualenvs.create false && \
    poetry install --no-interaction --no-ansi --only main

# ── Final stage ─────────────────────────────────────────────────────────────
FROM python:3.11-slim
WORKDIR /app

# create non-root user
RUN addgroup --system app && adduser --system --ingroup app app

# copy in installed Python packages and your app code
COPY --from=build /usr/local/lib/python3.11 /usr/local/lib/python3.11
COPY --from=build /app              /app

RUN chmod +x /app/scripts/entrypoint.sh

USER app
ENV PYTHONUNBUFFERED=1

# expose metrics & API ports
EXPOSE 8000 8002

# launch your orchestrator
ENTRYPOINT ["/app/scripts/entrypoint.sh"]
