# syntax=docker/dockerfile:1

# ---- Stage 1: build the frontend (React + Vite) ----
FROM node:20-alpine AS frontend-build
WORKDIR /fe
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- Stage 2: python runtime ----
FROM python:3.13-slim AS runtime
WORKDIR /app

# `grep` powers the live "grep bar" filter feature (app/tailing/grep.py) —
# make sure it's present regardless of what the base image ships by default.
RUN apt-get update \
    && apt-get install -y --no-install-recommends grep \
    && rm -rf /var/lib/apt/lists/*

COPY backend/ ./
RUN pip install --no-cache-dir .

# Built frontend assets are served directly by FastAPI (app/main.py mounts
# this directory) — no separate frontend server/container.
COPY --from=frontend-build /fe/dist ./app/static

ENV DB_PATH=/data/logsonfire.db \
    PYTHONUNBUFFERED=1

VOLUME ["/data"]
EXPOSE 8000

CMD ["python", "-m", "app.entrypoint"]
