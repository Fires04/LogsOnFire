"""SSH's exec channel only ever transports a single command string that the
remote shell interprets — there is no argv-array form like a local
subprocess. These tests pin down that every path we interpolate into such a
command is shell-quoted so shell metacharacters become inert literal text,
never a second command.
"""
from __future__ import annotations

import shlex

from app.providers.ssh import _quote


def _build_tail_command(path: str) -> str:
    return f"tail -F -n 0 -- {_quote(path)}"


def _build_read_tail_command(path: str, n_lines: int) -> str:
    return f"tail -n {int(n_lines)} -- {_quote(path)}"


def test_semicolon_injection_is_neutralized():
    malicious = "/var/log/app.log; rm -rf /"
    command = _build_tail_command(malicious)
    # The whole malicious string must appear as ONE shell-quoted token.
    assert command == f"tail -F -n 0 -- {shlex.quote(malicious)}"
    # shlex parsing the resulting command back must yield exactly one path arg,
    # i.e. the ';' never terminates the tail command.
    parsed = shlex.split(command)
    assert parsed == ["tail", "-F", "-n", "0", "--", malicious]


def test_command_substitution_is_neutralized():
    malicious = "/var/log/$(id).log"
    command = _build_tail_command(malicious)
    parsed = shlex.split(command)
    assert parsed[-1] == malicious


def test_backtick_injection_is_neutralized():
    malicious = "/var/log/`whoami`.log"
    command = _build_read_tail_command(malicious, 50)
    parsed = shlex.split(command)
    assert parsed == ["tail", "-n", "50", "--", malicious]


def test_path_with_spaces_and_quotes_round_trips():
    tricky = "/var/log/my app's log.log"
    command = _build_tail_command(tricky)
    parsed = shlex.split(command)
    assert parsed[-1] == tricky


def test_n_lines_is_always_coerced_to_int_not_interpolated_raw():
    # int(...) is applied before interpolation, so even if a caller passed a
    # non-numeric string through by mistake, it would raise here rather than
    # ever reaching the remote command string.
    import pytest

    with pytest.raises(ValueError):
        _build_read_tail_command("/var/log/app.log", "50; rm -rf /")  # type: ignore[arg-type]
