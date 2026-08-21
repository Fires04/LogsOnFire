"""Tests for the "journal" log source mode (journalctl-backed, not a real
file). Runs against the real `journalctl` binary — this dev/CI host has
systemd, so this is genuine coverage rather than a mock.
"""
from __future__ import annotations

import asyncio
import shutil
import uuid

import pytest

from logsonfire_agentcore.base import LogSourceSpec
from logsonfire_agentcore.journal import journal_access_warning, journal_unit_from_path, journalctl_args, make_journal_path
from logsonfire_agentcore.local import LocalFileProvider

pytestmark = pytest.mark.skipif(shutil.which("journalctl") is None, reason="journalctl not available on this host")


def test_make_journal_path_whole_journal_sentinel():
    assert make_journal_path("*") == "journal://"
    assert make_journal_path("") == "journal://"
    assert make_journal_path("  ") == "journal://"


def test_make_journal_path_unit():
    assert make_journal_path("nginx.service") == "journal://nginx.service"


def test_journal_unit_from_path_round_trips():
    assert journal_unit_from_path("journal://nginx.service") == "nginx.service"
    assert journal_unit_from_path("journal://") == ""
    assert journal_unit_from_path("/var/log/app.log") is None


def test_journalctl_args_follow_uses_zero_lines():
    args = journalctl_args("nginx.service", follow=True, n_lines=None)
    assert "--follow" in args
    assert "--lines=0" in args
    assert "--unit" in args and "nginx.service" in args


def test_journalctl_args_no_unit_omits_unit_flag():
    args = journalctl_args("", follow=False, n_lines=50)
    assert "--unit" not in args
    assert "--lines=50" in args


def test_journal_access_warning_none_for_root():
    assert journal_access_warning(is_root=True, groups=set()) is None


def test_journal_access_warning_none_for_privileged_group():
    assert journal_access_warning(is_root=False, groups={"users", "systemd-journal"}) is None
    assert journal_access_warning(is_root=False, groups={"adm"}) is None


def test_journal_access_warning_present_for_unprivileged_user():
    warning = journal_access_warning(is_root=False, groups={"users"})
    assert warning is not None
    assert "systemd-journal" in warning


async def test_resolve_sources_journal_mode_returns_synthetic_entry():
    provider = LocalFileProvider()
    spec = LogSourceSpec(mode="journal", path_or_pattern="*")
    files, truncated = await provider.resolve_sources(spec)
    assert not truncated
    assert len(files) == 1
    assert files[0].path == "journal://"
    # warning is either None (root/privileged test runner) or a real string —
    # either way, resolving must not blow up doing the access check.
    assert files[0].warning is None or isinstance(files[0].warning, str)


async def test_read_tail_whole_journal_returns_real_lines():
    provider = LocalFileProvider()
    lines = await provider.read_tail("journal://", 5)
    assert 0 < len(lines) <= 5
    assert all(isinstance(line, str) for line in lines)


async def test_tail_whole_journal_yields_live_lines():
    provider = LocalFileProvider()
    gen = provider.tail("journal://")
    try:
        async with asyncio.timeout(10):
            line = await gen.__anext__()
        assert isinstance(line, str)
        assert line != ""
    finally:
        await gen.aclose()


@pytest.mark.skipif(shutil.which("logger") is None, reason="logger (util-linux) not available on this host")
async def test_tail_whole_journal_delivers_a_new_line_promptly():
    """Regression: journalctl fully block-buffers its own stdout when it
    isn't a tty (always true for a subprocess pipe), so without forcing line
    buffering, a freshly-logged line can sit unflushed for a long time (or
    indefinitely, on a quiet system) instead of arriving as "live tail"
    implies. This writes a uniquely-tagged line via `logger` and requires it
    to show up within a tight deadline — on an unbuffered/un-flushed pipe
    this reliably times out; relying on ambient journal traffic to
    coincidentally flush the buffer (as an earlier version of this test
    effectively did) made that regression easy to miss.
    """
    marker = f"logsonfire-test-{uuid.uuid4().hex[:12]}"
    provider = LocalFileProvider()
    gen = provider.tail("journal://")
    try:
        # `tail()` is an async generator — nothing runs (no journalctl
        # subprocess exists yet) until it's actually iterated. Prime it
        # first so the marker below is injected *after* journalctl is
        # already following, not before it even started.
        async with asyncio.timeout(15):
            await gen.__anext__()

        proc = await asyncio.create_subprocess_exec("logger", "-t", "logsonfire-pytest", marker)
        await proc.wait()

        async with asyncio.timeout(5):
            while True:
                line = await gen.__anext__()
                if marker in line:
                    break
    finally:
        await gen.aclose()


@pytest.mark.skipif(shutil.which("systemctl") is None, reason="systemctl not available on this host")
async def test_list_journal_units_returns_real_units():
    """Powers the unit picker in the log source form — checked against the
    real systemctl on this host rather than mocked, same policy as the rest
    of this file. Doesn't assert on any specific unit name (that varies by
    host), just that it's a real, sane-looking list."""
    provider = LocalFileProvider()
    units = await provider.list_journal_units()
    assert isinstance(units, list)
    assert all(u.endswith(".service") for u in units)
    # No duplicates — a unit can appear more than once in raw
    # `systemctl list-units` output (e.g. once loaded, once as a template
    # instance) and the picker shouldn't offer the same name twice.
    assert len(units) == len(set(units))
