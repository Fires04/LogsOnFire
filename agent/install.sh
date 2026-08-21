#!/usr/bin/env bash
# Installs the LogsOnFire agent on a monitored host:
#   curl -fsSL https://<your-server>/agent/install.sh | sudo bash -s -- \
#       --server wss://<your-server> --token <token-from-the-Agents-page>
#
# --server/--token can also come from LOGSONFIRE_INSTALL_SERVER/
# LOGSONFIRE_INSTALL_TOKEN env vars instead of CLI args — that's what the
# Agents page's one-time install-link uses (GET /agent/install/<code>,
# see api/routes/agent_install.py), so the real bearer token never has to
# appear in this shell's history or in `ps` output while the command runs;
# only a meaningless, already-consumed one-time code does.
#
# Requires: python3 >= 3.11 (pip is auto-installed via apt/dnf/yum/apk/
# pacman if missing). Creates a dedicated low-privilege
# 'logsonfire-agent' system user (in the 'systemd-journal'/'adm' groups so
# it can read the journal without running as root), installs the agent as a
# systemd service, and writes its config to /etc/logsonfire-agent/.
set -euo pipefail

SERVER_URL="${LOGSONFIRE_INSTALL_SERVER:-}"
TOKEN="${LOGSONFIRE_INSTALL_TOKEN:-}"
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

# Fail fast, before creating any user/files, on the two prerequisites pip
# install would otherwise fail on with a much less obvious error:
# python3 >= 3.11 (agentcore/agent's requires-python), and pip itself —
# many minimal distro images (notably Debian/Ubuntu's default cloud
# images) ship python3 without the pip module at all ("No module named
# pip"), since it's a separate package. Auto-install it via whatever
# package manager is actually present rather than just erroring, since
# that's the single most common reason this script fails on a fresh host.
if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required but was not found on this host. Install it first (e.g. 'apt install python3') and re-run." >&2
  exit 1
fi
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
  echo "python3 is too old ($(python3 --version 2>&1)) — logsonfire-agent needs Python 3.11 or newer." >&2
  exit 1
fi
if ! python3 -m pip --version >/dev/null 2>&1; then
  echo "python3's pip module is missing — attempting to install it via this host's package manager…" >&2
  if command -v apt-get >/dev/null 2>&1; then
    apt-get update -qq && apt-get install -y -qq python3-pip
  elif command -v dnf >/dev/null 2>&1; then
    dnf install -y -q python3-pip
  elif command -v yum >/dev/null 2>&1; then
    yum install -y -q python3-pip
  elif command -v apk >/dev/null 2>&1; then
    apk add --no-cache -q py3-pip
  elif command -v pacman >/dev/null 2>&1; then
    pacman -Sy --noconfirm --quiet python-pip
  else
    echo "Don't know how to install pip on this distro — install python3-pip (or your distro's equivalent) manually and re-run." >&2
    exit 1
  fi
  if ! python3 -m pip --version >/dev/null 2>&1; then
    echo "pip still isn't available after attempting to install it — install it manually and re-run." >&2
    exit 1
  fi
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

# Docker container log support ("docker" log source mode) needs the
# agent's user in the 'docker' group to reach the daemon socket — unlike
# the journal group above, that's roughly root-equivalent access (anyone
# in 'docker' can trivially root the host via a bind-mounted container),
# so this is opt-in and asked explicitly, never added automatically.
# LOGSONFIRE_INSTALL_ENABLE_DOCKER=yes|no skips the prompt for scripted/
# non-interactive installs; with no override and no controlling tty
# (piped through something other than an interactive shell) it defaults
# to "no" rather than hang waiting for input that will never come.
ENABLE_DOCKER="${LOGSONFIRE_INSTALL_ENABLE_DOCKER:-}"
if [[ -z "$ENABLE_DOCKER" ]] && (command -v docker >/dev/null 2>&1 || [[ -S /var/run/docker.sock ]]); then
  if [[ -e /dev/tty ]]; then
    read -r -p "Docker detected on this host — let the agent read container logs via 'docker logs'? This adds it to the 'docker' group, which is roughly root-equivalent access (think of it like sudo). [y/N] " ENABLE_DOCKER < /dev/tty || ENABLE_DOCKER="n"
  else
    ENABLE_DOCKER="n"
  fi
fi
case "${ENABLE_DOCKER,,}" in
  y|yes)
    usermod -aG docker logsonfire-agent
    echo "Added logsonfire-agent to the 'docker' group — container logs are available as a log source now."
    ;;
  *)
    echo "Skipped Docker group membership — container logs won't be readable yet. To enable it later:" >&2
    echo "  usermod -aG docker logsonfire-agent && systemctl restart logsonfire-agent" >&2
    ;;
esac

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
systemctl enable logsonfire-agent
# restart, not "enable --now": --now only *starts* the unit, which is a
# no-op if it's already active — re-running this script (new token after
# re-enrolling, a config fix, whatever) would then silently leave the old
# process running with the old config/binary loaded in memory, never
# picking up what was just written to config.toml. restart always ends
# up with the current config actually loaded, whether the unit was
# already running or not. Found by direct testing: a re-enrolled agent
# stayed unable to connect until manually restarted.
systemctl restart logsonfire-agent

echo "logsonfire-agent installed and started. Check status with:"
echo "  systemctl status logsonfire-agent"
echo "  journalctl -u logsonfire-agent -f"
