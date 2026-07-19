"""Tests for redacted JSONL diagnostic logging."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sf6viewer.infrastructure.logging import JsonlLogSink, redact, safe_exception_fields


def test_redact_removes_nested_mixed_case_secrets_in_lists_and_mappings() -> None:
    value = {
        "Cookie": "cookie-value",
        "nested": {
            "ToKeN": "token-value",
            "items": [{"Authorization": "Bearer secret"}, {"safe": 7}],
        },
        "safe_list": ["visible", {"csrf": "csrf-value"}, {"storage_state": "state-value"}],
        "NoNcE": "nonce-value",
    }

    assert redact(value) == {
        "Cookie": "[REDACTED]",
        "nested": {
            "ToKeN": "[REDACTED]",
            "items": [{"Authorization": "[REDACTED]"}, {"safe": 7}],
        },
        "safe_list": ["visible", {"csrf": "[REDACTED]"}, {"storage_state": "[REDACTED]"}],
        "NoNcE": "[REDACTED]",
    }


def test_safe_exception_fields_never_includes_exception_text_or_path() -> None:
    exception = RuntimeError("token=secret at C:/private/evidence.html")

    fields = safe_exception_fields(exception, "diag_01J00000000000000000000000")

    assert fields == {
        "exception_type": "RuntimeError",
        "diagnostic_id": "diag_01J00000000000000000000000",
    }
    assert "secret" not in json.dumps(fields)
    assert "evidence.html" not in json.dumps(fields)


def test_jsonl_sink_writes_redacted_valid_json_lines(tmp_path: Path) -> None:
    now = datetime(2026, 7, 19, 9, 30, tzinfo=UTC)
    sink = JsonlLogSink(tmp_path, clock=lambda: now)

    path = sink.write({"event": "login", "nested": {"PASSWORD": "super-secret"}})

    assert path == tmp_path / "sf6viewer-20260719.jsonl"
    line = path.read_text(encoding="utf-8")
    assert json.loads(line) == {
        "event": "login",
        "nested": {"PASSWORD": "[REDACTED]"},
    }
    assert "super-secret" not in line


def test_jsonl_sink_rotates_to_a_numeric_suffix_before_another_oversized_write(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 7, 19, tzinfo=UTC)
    sink = JsonlLogSink(tmp_path, max_bytes=1, clock=lambda: now)

    first = sink.write({"event": "one"})
    second = sink.write({"event": "two"})

    assert first.name == "sf6viewer-20260719.jsonl"
    assert second.name == "sf6viewer-20260719.1.jsonl"
    assert json.loads(first.read_text(encoding="utf-8")) == {"event": "one"}
    assert json.loads(second.read_text(encoding="utf-8")) == {"event": "two"}


def test_jsonl_sink_exposes_secure_defaults(tmp_path: Path) -> None:
    sink = JsonlLogSink(tmp_path)

    assert sink.max_bytes == 10 * 1024 * 1024
    assert sink.retention_days == 14


def test_jsonl_sink_prunes_only_matching_logs_older_than_retention(tmp_path: Path) -> None:
    now = datetime(2026, 7, 19, tzinfo=UTC)
    old_day = (now - timedelta(days=15)).strftime("%Y%m%d")
    old_log = tmp_path / f"sf6viewer-{old_day}.jsonl"
    old_rotated_log = tmp_path / f"sf6viewer-{old_day}.1.jsonl"
    zero_suffix = tmp_path / f"sf6viewer-{old_day}.0.jsonl"
    leading_zero_suffix = tmp_path / f"sf6viewer-{old_day}.01.jsonl"
    unrelated = tmp_path / "notes.jsonl"
    malformed_name = tmp_path / "sf6viewer-20261340.jsonl"
    lookalike = tmp_path / f"sf6viewer-{old_day}.1.jsonl.bak"
    for path in (
        old_log,
        old_rotated_log,
        zero_suffix,
        leading_zero_suffix,
        unrelated,
        malformed_name,
        lookalike,
    ):
        path.write_text("keep or prune\n", encoding="utf-8")

    JsonlLogSink(tmp_path, clock=lambda: now).prune()

    assert not old_log.exists()
    assert not old_rotated_log.exists()
    assert zero_suffix.exists()
    assert leading_zero_suffix.exists()
    assert unrelated.exists()
    assert malformed_name.exists()
    assert lookalike.exists()
