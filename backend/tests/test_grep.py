from __future__ import annotations

import pytest

from app.tailing.grep import GrepExpressionError, parse_grep_expression, run_grep

SAMPLE_LINES = [
    "2026-08-09 10:00:00 INFO starting up",
    "2026-08-09 10:00:01 DEBUG connecting to db",
    "2026-08-09 10:00:02 ERROR connection refused",
    "2026-08-09 10:00:03 INFO retrying",
    "2026-08-09 10:00:04 ERROR timeout",
    "2026-08-09 10:00:05 INFO recovered",
]


def test_parse_simple_pattern():
    flags, pattern = parse_grep_expression("error")
    assert flags == []
    assert pattern == "error"


def test_parse_strips_leading_grep_word():
    flags, pattern = parse_grep_expression("grep -i error")
    assert ("-i", None) in flags
    assert pattern == "error"


def test_parse_context_flag_with_separate_value():
    flags, pattern = parse_grep_expression("-C 3 error")
    assert ("-C", "3") in flags
    assert pattern == "error"


def test_parse_context_flag_attached_value():
    flags, pattern = parse_grep_expression("-A3 error")
    assert ("-A", "3") in flags
    assert pattern == "error"


def test_parse_combined_short_flags():
    flags, pattern = parse_grep_expression("-in error")
    assert flags == [("-in", None)]
    assert pattern == "error"


def test_parse_rejects_disallowed_flag():
    with pytest.raises(GrepExpressionError):
        parse_grep_expression("-P error")  # PCRE mode disallowed


def test_parse_rejects_read_patterns_from_file_flag():
    with pytest.raises(GrepExpressionError):
        parse_grep_expression("-f /etc/passwd")


def test_parse_rejects_non_numeric_context_value():
    with pytest.raises(GrepExpressionError):
        parse_grep_expression("-C abc error")


def test_parse_rejects_shell_metacharacters_as_extra_args():
    with pytest.raises(GrepExpressionError):
        parse_grep_expression("error; rm -rf /")


def test_parse_empty_expression_rejected():
    with pytest.raises(GrepExpressionError):
        parse_grep_expression("   ")


async def test_run_grep_finds_matches_with_line_numbers():
    results, error = await run_grep(SAMPLE_LINES, "ERROR")
    assert error is None
    matched_texts = [r.text for r in results if r.is_match]
    assert len(matched_texts) == 2
    assert all("ERROR" in t for t in matched_texts)
    assert all(r.line_no is not None for r in results)


async def test_run_grep_case_insensitive():
    results, error = await run_grep(SAMPLE_LINES, "-i error")
    assert error is None
    assert len([r for r in results if r.is_match]) == 2


async def test_run_grep_with_context_includes_separator_and_context_lines():
    results, error = await run_grep(SAMPLE_LINES, "-C 1 ERROR")
    assert error is None
    matches = [r for r in results if r.is_match]
    context = [r for r in results if not r.is_match and not r.is_separator]
    assert len(matches) == 2
    assert len(context) > 0


async def test_run_grep_no_matches_is_not_an_error():
    results, error = await run_grep(SAMPLE_LINES, "nope-not-here")
    assert error is None
    assert results == []


async def test_run_grep_invalid_regex_reported_as_error_not_crash():
    results, error = await run_grep(SAMPLE_LINES, "-E [")
    assert results == []
    assert error is not None


async def test_run_grep_shell_injection_attempt_is_treated_as_literal_pattern():
    lines = ["safe line", "not $(id) matched"]
    results, error = await run_grep(lines, "$(id)")
    assert error is None
    assert len(results) == 1
    assert "$(id)" in results[0].text
