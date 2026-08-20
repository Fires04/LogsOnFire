"""Serves the one-time, pre-filled install script created by
POST /api/agents/{id}/install-link (app/agents/install_links.py). Separate
from the static `/agent/install.sh` (served as a plain file, see main.py's
spa_fallback) — this path is dynamic per request and always single-use.
"""
from __future__ import annotations

import logging
import shlex
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from app.agents.install_links import get_install_link_store

router = APIRouter(prefix="/agent", tags=["agent-install"])
logger = logging.getLogger("logsonfire.agent_install")

STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "static"
INSTALL_SH_TEMPLATE = STATIC_DIR / "agent" / "install.sh"

EXPIRED_MESSAGE = (
    "#!/bin/sh\n"
    'echo "This install link has already been used or has expired — generate a new one from the Agents page." >&2\n'
    "exit 1\n"
)


@router.get("/install/{code}")
async def download_install_script(code: str) -> PlainTextResponse:
    link = get_install_link_store().consume(code)
    if link is None:
        return PlainTextResponse(EXPIRED_MESSAGE, status_code=410, media_type="text/x-shellscript")

    if not INSTALL_SH_TEMPLATE.is_file():
        logger.error("install-link requested but %s is missing (frontend/agent assets not built?)", INSTALL_SH_TEMPLATE)
        return PlainTextResponse(
            '#!/bin/sh\necho "install.sh template not found on the server" >&2\nexit 1\n',
            status_code=500,
            media_type="text/x-shellscript",
        )

    template = INSTALL_SH_TEMPLATE.read_text()
    # shlex.quote: server_url/token become the *contents* of a shell script
    # this endpoint hands back for `sudo bash` to execute — the same
    # shell-injection discipline this project has always applied to
    # anything interpolated into a command a shell will run.
    prelude = (
        f"export LOGSONFIRE_INSTALL_SERVER={shlex.quote(link.server_url)}\n"
        f"export LOGSONFIRE_INSTALL_TOKEN={shlex.quote(link.token)}\n"
    )
    # Insert after the shebang line (not before it) so the script still
    # runs correctly if someone chmod +x's and executes it directly instead
    # of piping to bash — a leading non-shebang line would just be a no-op
    # comment either way, but this keeps the file conventional.
    if template.startswith("#!"):
        first_newline = template.index("\n") + 1
        script = template[:first_newline] + prelude + template[first_newline:]
    else:
        script = prelude + template
    return PlainTextResponse(script, media_type="text/x-shellscript")
