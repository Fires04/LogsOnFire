# syntax=docker/dockerfile:1

# ---- Stage 1: build the frontend (React + Vite) ----
FROM node:20-alpine AS frontend-build
WORKDIR /fe
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- Stage 2: build the agent/agentcore wheels the server will host for
# `agent/install.sh` to download onto monitored hosts. --no-deps: we only
# want wheels for our own two packages here — their third-party
# dependencies (websockets etc.) resolve from PyPI normally when
# install.sh runs `pip install` on the target host. Wheel filenames must
# carry a real PEP 440 version (a plain "-latest-" alias isn't a valid
# wheel filename and pip/uv reject it), so a MANIFEST listing the real
# built filenames ships alongside them — install.sh reads it rather than
# hardcoding a version that would go stale on every version bump.
FROM python:3.13-slim AS agent-build
WORKDIR /build
COPY agentcore/ ./agentcore/
COPY agent/ ./agent/
RUN pip wheel --no-cache-dir --no-deps -w /out ./agentcore ./agent \
    && (cd /out && ls *.whl > MANIFEST)

# ---- Stage 3: python runtime ----
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

# Agent distribution: served at /agent/* by the same FastAPI static
# fallback (app/main.py's spa_fallback route serves any real file under
# app/static by its relative path) — this is what agent/install.sh
# downloads from `${SERVER_URL}/agent/...`, reading MANIFEST first to learn
# the real (versioned) wheel filenames.
RUN mkdir -p ./app/static/agent
COPY --from=agent-build /out/ ./app/static/agent/
COPY agent/logsonfire-agent.service ./app/static/agent/logsonfire-agent.service
COPY agent/install.sh ./app/static/agent/install.sh

ENV DB_PATH=/data/logsonfire.db \
    PYTHONUNBUFFERED=1

VOLUME ["/data"]
EXPOSE 8000

CMD ["python", "-m", "app.entrypoint"]
