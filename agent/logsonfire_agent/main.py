"""Entrypoint: `logsonfire-agent` — loads config, runs the reconnecting
WebSocket client forever. Installed as a systemd service
(logsonfire-agent.service) on each monitored host.
"""
from __future__ import annotations

import asyncio
import logging
import sys

from logsonfire_agent.config import load_config
from logsonfire_agent.wsclient import run

logger = logging.getLogger("logsonfire_agent")


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )


def main() -> None:
    _configure_logging()
    try:
        config = load_config()
    except RuntimeError as exc:
        logger.critical("%s", exc)
        sys.exit(1)

    logger.info("logsonfire-agent starting, server=%s", config.server_url)
    try:
        asyncio.run(run(config))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
