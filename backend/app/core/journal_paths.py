"""The "journal://<unit>" path convention used in the /ws/logs protocol to
refer to a systemd journal unit instead of a real file path. Pure string
convention, zero I/O — kept here (not in agentcore) because ws_logs.py needs
it server-side to build a deterministic path for "journal" mode log sources
without asking the agent. agentcore/logsonfire_agentcore/journal.py defines
the same tiny convention on the agent side (duplicated on purpose — the two
packages don't share code, agentcore has zero dependency on the backend).
"""
from __future__ import annotations

JOURNAL_PREFIX = "journal://"
ALL_UNITS_SENTINEL = "*"


def make_journal_path(unit: str) -> str:
    unit = unit.strip()
    if unit in ("", ALL_UNITS_SENTINEL):
        return JOURNAL_PREFIX
    return f"{JOURNAL_PREFIX}{unit}"


def journal_unit_from_path(path: str) -> str | None:
    """Returns the unit name (empty string means "the whole journal"), or
    None if `path` isn't a journal reference at all."""
    if not path.startswith(JOURNAL_PREFIX):
        return None
    return path[len(JOURNAL_PREFIX):]
