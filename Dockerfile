# syntax=docker/dockerfile:1

FROM python:3.11-slim AS build
WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential && \
    rm -rf /var/lib/apt/lists/*

# Copy lockfiles and your source ahead of install so Poetry can see your package
COPY pyproject.toml poetry.lock /app/
COPY . /app

# install deps (runtime only)
RUN pip install poetry && \
    poetry config virtualenvs.create false && \
    poetry install --no-interaction --no-ansi --only main

COPY . /app

FROM python:3.11-slim
WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app
USER app

COPY --from=build /usr/local/lib/python3.11 /usr/local/lib/python3.11
COPY --from=build /app              /app

ENV PYTHONUNBUFFERED=1
EXPOSE 8000 8002

ENTRYPOINT ["python", "-m", "app.orchestrator"]