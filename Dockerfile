# syntax=docker/dockerfile:1

# ---- Stage 1: build the frontend (React + Vite) ----
FROM node:20-alpine AS frontend-build
WORKDIR /fe
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- Stage 2: derive a build version from the current git commit — every
# build gets a distinct version automatically, so the server<->agent
# version-mismatch check (app/core/version.py) can never go stale from
# someone forgetting to hand-bump a semver number (see CLAUDE.md — that
# happened for real once already, before this existed). All three packages
# built from this same commit (backend, agentcore, agent) get stamped with
# the identical version below, which is exactly the property the mismatch
# check needs: it fires precisely when an agent hasn't been reinstalled
# since a newer commit was deployed to the server.
FROM python:3.13-slim AS gitinfo
WORKDIR /src
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
COPY .git ./.git
# "0.0.0+g<hash>" is a valid PEP 440 local version segment (letters/digits/
# periods only — no hyphens allowed there, unlike a git describe --dirty
# suffix would produce).
RUN echo -n "0.0.0+g$(git rev-parse --short=12 HEAD)" > /version.txt

# ---- Stage 3: build the agent/agentcore wheels the server will host for
# `agent/install.sh` to download onto monitored hosts. --no-deps: we only
# want wheels for our own two packages here — their third-party
# dependencies (websockets etc.) resolve from PyPI normally when
# install.sh runs `pip install` on the target host. Wheel filenames carry
# the git-derived version (see gitinfo above), so a MANIFEST listing the
# real built filenames ships alongside them — install.sh reads it rather
# than hardcoding a filename that would go stale on every build.
FROM python:3.13-slim AS agent-build
WORKDIR /build
COPY --from=gitinfo /version.txt /version.txt
COPY agentcore/ ./agentcore/
COPY agent/ ./agent/
RUN VERSION=$(cat /version.txt) \
    && sed -i "s/^version = .*/version = \"${VERSION}\"/" agentcore/pyproject.toml agent/pyproject.toml \
    && pip wheel --no-cache-dir --no-deps -w /out ./agentcore ./agent \
    && (cd /out && ls *.whl > MANIFEST)

# ---- Stage 4: python runtime ----
FROM python:3.13-slim AS runtime
WORKDIR /app

# `grep` powers the live "grep bar" filter feature (app/tailing/grep.py) —
# make sure it's present regardless of what the base image ships by default.
RUN apt-get update \
    && apt-get install -y --no-install-recommends grep \
    && rm -rf /var/lib/apt/lists/*

COPY --from=gitinfo /version.txt /version.txt
COPY backend/ ./
RUN sed -i "s/^version = .*/version = \"$(cat /version.txt)\"/" pyproject.toml \
    && pip install --no-cache-dir .

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
