# syntax=docker/dockerfile:1

# ---- Stage 1: build the frontend (React + Vite) ----
FROM node:20-alpine AS frontend-build
WORKDIR /fe
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- Stage 2: derive build versions from git — every build gets a
# distinct, auto-incrementing version with no manual bump needed (see
# CLAUDE.md — someone forgetting to hand-bump a semver number happened for
# real once already, before this existed).
#
# Scheme: "<major from the nearest vN git tag>.<commits since that tag>
# +g<commit hash>" — e.g. tag v1 + 7 commits since = "1.7+ge1be41b". The
# second number auto-increments on every commit; the major jump (e.g.
# 1.x -> 2.0) is a deliberate, purely manual action:
#     git tag v2 && git push origin v2
#
# Two *independent* versions come out of this, not one shared by all three
# packages: /version.txt (the server — backend + frontend, counts every
# commit) and /agent_version.txt (agent + agentcore, counts only commits
# that touch the agent/ or agentcore/ paths). Agent code changes far less
# often than the backend/frontend do, so a server-side-only commit (a CSS
# tweak, a backend bugfix with no agent/agentcore involvement) must not
# make every already-current agent look out of date and demand a
# reinstall — see app/core/version.py for how the server compares an
# agent's self-reported version against /agent_version.txt, not its own.
FROM python:3.13-slim AS gitinfo
WORKDIR /src
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
COPY .git ./.git
RUN TAG=$(git describe --tags --abbrev=0 2>/dev/null || echo "v0") \
    && BASE=${TAG#v} \
    && COUNT=$(git rev-list --count "${TAG}..HEAD" 2>/dev/null || git rev-list --count HEAD) \
    && HASH=$(git rev-parse --short=12 HEAD) \
    && echo -n "${BASE}.${COUNT}+g${HASH}" > /version.txt \
    && AGENT_COUNT=$(git rev-list --count "${TAG}..HEAD" -- agent agentcore 2>/dev/null || echo 0) \
    && AGENT_COMMIT=$(git log -1 --format=%H -- agent agentcore 2>/dev/null) \
    && AGENT_COMMIT=${AGENT_COMMIT:-$(git rev-parse HEAD)} \
    && AGENT_HASH=$(git rev-parse --short=12 "${AGENT_COMMIT}") \
    && echo -n "${BASE}.${AGENT_COUNT}+g${AGENT_HASH}" > /agent_version.txt

# ---- Stage 3: build the agent/agentcore wheels the server will host for
# `agent/install.sh`/`agent/upgrade.sh` to download onto monitored hosts.
# --no-deps: we only want wheels for our own two packages here — their
# third-party dependencies (websockets etc.) resolve from PyPI normally
# when install.sh runs `pip install` on the target host. Wheel filenames
# carry the git-derived version (see gitinfo above), so a MANIFEST listing
# the real built filenames ships alongside them — install.sh/upgrade.sh
# read it rather than hardcoding a filename that would go stale every build.
FROM python:3.13-slim AS agent-build
WORKDIR /build
COPY --from=gitinfo /agent_version.txt /agent_version.txt
COPY agentcore/ ./agentcore/
COPY agent/ ./agent/
RUN VERSION=$(cat /agent_version.txt) \
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
# app/static by its relative path) — this is what agent/install.sh and
# agent/upgrade.sh download from `${SERVER_URL}/agent/...`, reading
# MANIFEST first to learn the real (versioned) wheel filenames.
RUN mkdir -p ./app/static/agent
COPY --from=agent-build /out/ ./app/static/agent/
COPY --from=gitinfo /agent_version.txt ./app/static/agent/VERSION
COPY agent/logsonfire-agent.service ./app/static/agent/logsonfire-agent.service
COPY agent/install.sh ./app/static/agent/install.sh
COPY agent/upgrade.sh ./app/static/agent/upgrade.sh

ENV DB_PATH=/data/logsonfire.db \
    PYTHONUNBUFFERED=1

VOLUME ["/data"]
EXPOSE 8000

CMD ["python", "-m", "app.entrypoint"]
