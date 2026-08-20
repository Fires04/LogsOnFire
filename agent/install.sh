#!/usr/bin/env bash
# Installs the LogsOnFire agent on a monitored host:
#   curl -fsSL https://<your-server>/agent/install.sh | sudo bash -s -- \
#       --server wss://<your-server> --token <token-from-the-Agents-page>
#
# Requires: python3 >= 3.11, pip. Creates a dedicated low-privilege
# 'logsonfire-agent' system user (in the 'systemd-journal'/'adm' groups so
# it can read the journal without running as root), installs the agent as a
# systemd service, and writes its config to /etc/logsonfire-agent/.
set -euo pipefail

SERVER_URL=""
TOKEN=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --server) SERVER_URL="$2"; shift 2 ;;
    --token) TOKEN="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "$SERVER_URL" || -z "$TOKEN" ]]; then
  echo "usage: install.sh --server wss://your-server --token <token>" >&2
  exit 1
fi

# --server is the WebSocket URL the *agent* connects to at runtime
# (ws://|wss://) — everything this script itself downloads (wheels, the
# systemd unit) is plain HTTP(S), served by the same FastAPI process at the
# same host/port, so derive that URL by swapping the scheme rather than
# asking for it twice.
case "$SERVER_URL" in
  wss://*) DOWNLOAD_URL="https://${SERVER_URL#wss://}" ;;
  ws://*)  DOWNLOAD_URL="http://${SERVER_URL#ws://}" ;;
  *)       echo "--server must start with ws:// or wss://" >&2; exit 1 ;;
esac
DOWNLOAD_URL="${DOWNLOAD_URL%/}"

if ! id -u logsonfire-agent >/dev/null 2>&1; then
  useradd --system --no-create-home --shell /usr/sbin/nologin logsonfire-agent
fi
# Journal access without root — see agentcore/logsonfire_agentcore/journal.py's
# access-warning logic for why this matters (journalctl silently shows less
# otherwise, with no error).
usermod -aG systemd-journal logsonfire-agent 2>/dev/null || true
usermod -aG adm logsonfire-agent 2>/dev/null || true

# Wheel filenames carry a real version (logsonfire_agentcore-0.1.0-...whl) —
# a plain "-latest-" alias isn't a valid wheel filename, so read the actual
# names from MANIFEST (one filename per line, written at image build time)
# instead of hardcoding a version that would go stale on every bump.
MANIFEST=$(curl -fsSL "${DOWNLOAD_URL}/agent/MANIFEST")
AGENTCORE_WHEEL=$(echo "$MANIFEST" | grep '^logsonfire_agentcore-' | head -1)
AGENT_WHEEL=$(echo "$MANIFEST" | grep '^logsonfire_agent-' | head -1)
if [[ -z "$AGENTCORE_WHEEL" || -z "$AGENT_WHEEL" ]]; then
  echo "could not find agent wheels in ${DOWNLOAD_URL}/agent/MANIFEST" >&2
  exit 1
fi

python3 -m pip install --break-system-packages --upgrade \
  "logsonfire-agentcore @ ${DOWNLOAD_URL}/agent/${AGENTCORE_WHEEL}" \
  "logsonfire-agent @ ${DOWNLOAD_URL}/agent/${AGENT_WHEEL}"

# Where pip actually put the entrypoint varies by distro/Python install
# (Debian/Ubuntu with --break-system-packages puts it in /usr/local/bin,
# not /usr/bin) — resolve it for real via PATH rather than hardcoding a
# path in the shipped systemd unit, which would silently 203/EXEC on
# anything that doesn't match.
AGENT_BIN=$(command -v logsonfire-agent || true)
if [[ -z "$AGENT_BIN" ]]; then
  echo "logsonfire-agent installed but not found on PATH — check your pip install location" >&2
  exit 1
fi

mkdir -p /etc/logsonfire-agent
cat > /etc/logsonfire-agent/config.toml <<EOF
server_url = "${SERVER_URL}"
token = "${TOKEN}"
EOF
chmod 600 /etc/logsonfire-agent/config.toml
chown logsonfire-agent:logsonfire-agent /etc/logsonfire-agent/config.toml

SERVICE_TEMPLATE=$(mktemp)
trap 'rm -f "$SERVICE_TEMPLATE"' EXIT
install -m 644 "$(dirname "$0")/logsonfire-agent.service" "$SERVICE_TEMPLATE" 2>/dev/null || \
  curl -fsSL "${DOWNLOAD_URL}/agent/logsonfire-agent.service" -o "$SERVICE_TEMPLATE"
sed "s|^ExecStart=.*|ExecStart=${AGENT_BIN}|" "$SERVICE_TEMPLATE" > /etc/systemd/system/logsonfire-agent.service
chmod 644 /etc/systemd/system/logsonfire-agent.service

systemctl daemon-reload
systemctl enable --now logsonfire-agent

echo "logsonfire-agent installed and started. Check status with:"
echo "  systemctl status logsonfire-agent"
echo "  journalctl -u logsonfire-agent -f"
