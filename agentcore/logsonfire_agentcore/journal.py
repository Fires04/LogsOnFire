"""Shared helpers for the "journal" log source mode — tailing a systemd
unit's journal (or the whole journal) via `journalctl`, instead of a text
file. LocalFileProvider dispatches to these when a log source's resolved
path starts with JOURNAL_PREFIX, so nothing in dispatch.py needs to know
journal sources aren't real files.

Note: JOURNAL_PREFIX/make_journal_path/journal_unit_from_path are
deliberately duplicated (not imported) from the server's
backend/app/core/journal_paths.py — this package has zero dependency on the
backend, by design (it runs on a monitored host, not the server).
"""
from __future__ import annotations

JOURNAL_PREFIX = "journal://"
ALL_UNITS_SENTINEL = "*"

# Groups that give a non-root user full read access to the system journal
# (see journald.conf(5) / systemd-tmpfiles's journal ACLs). Debian/Ubuntu use
# "systemd-journal" for the journal file group; "adm" is the traditional
# catch-all log-reading group some distros also grant.
JOURNAL_PRIVILEGED_GROUPS = {"systemd-journal", "adm"}


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


def journalctl_args(unit: str, *, follow: bool, n_lines: int | None) -> list[str]:
    """Build journalctl's argument list (excluding the program name itself)
    — always a plain arg list, run via create_subprocess_exec (no shell)."""
    args = ["--no-pager", "--output=short-iso"]
    if unit:
        args += ["--unit", unit]
    if follow:
        args += ["--follow", "--lines=0"]
    elif n_lines is not None:
        args += [f"--lines={int(n_lines)}"]
    return args


def journal_access_warning(*, is_root: bool, groups: set[str]) -> str | None:
    """journalctl silently limits itself to whatever the *current* user can
    read when it isn't root: with no special group membership that's often
    just that user's own `--user` logs (frequently nothing at all), not the
    system journal the user actually asked for. Rather than let that show up
    as a confusing "0 lines, no error", surface it as an explicit warning.
    """
    if is_root:
        return None
    if groups & JOURNAL_PRIVILEGED_GROUPS:
        return None
    return (
        "The agent is not running as root and not a member of the 'systemd-journal' or 'adm' "
        "group — journalctl may only be able to show logs readable by this user, which can mean "
        "an empty or incomplete result. Add the agent's user to 'systemd-journal' (or run it as "
        "root) for full access to the system journal."
    )
