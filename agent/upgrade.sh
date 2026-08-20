#!/usr/bin/env bash
# Upgrades an already-installed LogsOnFire agent to whatever the configured
# server is currently running:
#   curl -fsSL https://<your-server>/agent/upgrade.sh | sudo bash
#
# Unlike install.sh, this doesn't provision a new identity — it reads
# server_url from the existing /etc/logsonfire-agent/config.toml, so no
# token/name re-entry is needed. Since agent/agentcore versions are now
# derived from the git commit that built the server (see Dockerfile), a
# plain `pip install --upgrade` correctly detects and installs a newer
# build whenever the server has moved to a newer commit — no
# --force-reinstall needed anymore (that was only ever a workaround for
# hand-maintained semver not changing between builds).
set -euo pipefail

CONFIG_PATH="/etc/logsonfire-agent/config.toml"
if [[ ! -f "$CONFIG_PATH" ]]; then
  echo "No existing agent config found at $CONFIG_PATH — use install.sh for a first-time install instead." >&2
  exit 1
fi

SERVER_URL=$(grep -oP '(?<=^server_url = ")[^"]*' "$CONFIG_PATH" || true)
if [[ -z "$SERVER_URL" ]]; then
  echo "Could not read server_url from $CONFIG_PATH" >&2
  exit 1
fi

case "$SERVER_URL" in
  wss://*) DOWNLOAD_URL="https://${SERVER_URL#wss://}" ;;
  ws://*)  DOWNLOAD_URL="http://${SERVER_URL#ws://}" ;;
  *)       echo "server_url in $CONFIG_PATH must start with ws:// or wss://" >&2; exit 1 ;;
esac
DOWNLOAD_URL="${DOWNLOAD_URL%/}"

MANIFEST=$(curl -fsSL "${DOWNLOAD_URL}/agent/MANIFEST")
AGENTCORE_WHEEL=$(echo "$MANIFEST" | grep '^logsonfire_agentcore-' | head -1)
AGENT_WHEEL=$(echo "$MANIFEST" | grep '^logsonfire_agent-' | head -1)
if [[ -z "$AGENTCORE_WHEEL" || -z "$AGENT_WHEEL" ]]; then
  echo "could not find agent wheels in ${DOWNLOAD_URL}/agent/MANIFEST" >&2
  exit 1
fi

BEFORE=$(python3 -m pip show logsonfire-agent 2>/dev/null | grep -oP '(?<=^Version: ).*' || echo "not installed")

python3 -m pip install --break-system-packages --upgrade \
  "logsonfire-agentcore @ ${DOWNLOAD_URL}/agent/${AGENTCORE_WHEEL}" \
  "logsonfire-agent @ ${DOWNLOAD_URL}/agent/${AGENT_WHEEL}"

AFTER=$(python3 -m pip show logsonfire-agent 2>/dev/null | grep -oP '(?<=^Version: ).*')

if [[ "$BEFORE" == "$AFTER" ]]; then
  echo "Already up to date (${AFTER})."
else
  echo "Upgraded ${BEFORE} -> ${AFTER}."
  systemctl restart logsonfire-agent
  echo "logsonfire-agent restarted."
fi

echo "Check status with: systemctl status logsonfire-agent"
