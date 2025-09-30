"""Tests for the related record helper utilities."""

from __future__ import annotations

import importlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest


def _write_submission(path: Path, identifier: str, submitted_at: datetime | None) -> None:
    payload = {
        "id": identifier,
        "questionnaire_key": "test",
        "answers": {},
    }
    if submitted_at is not None:
        payload["submitted_at"] = submitted_at.isoformat()
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle)


def test_load_related_record_options_returns_sorted_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = tmp_path / "system_registration" / "submissions"
    directory.mkdir(parents=True)

    newer_time = datetime(2024, 5, 1, tzinfo=timezone.utc)
    older_time = datetime(2023, 1, 1, tzinfo=timezone.utc)

    _write_submission(directory / "first.json", "abc", older_time)
    _write_submission(directory / "second.json", "xyz", newer_time)
    # Duplicate ID with a newer timestamp should replace the older entry
    _write_submission(directory / "duplicate.json", "abc", newer_time)

    related_records = importlib.import_module("lib.related_records")
    monkeypatch.setattr(
        related_records,
        "SOURCE_DIRECTORIES",
        {"system_registration": directory},
        raising=False,
    )

    options = related_records.load_related_record_options("system_registration")

    assert options == [
        ("abc", f"abc · {newer_time.isoformat()}"),
        ("xyz", f"xyz · {newer_time.isoformat()}"),
    ]


def test_related_record_source_label_has_fallback() -> None:
    related_records = importlib.import_module("lib.related_records")
    assert (
        related_records.related_record_source_label("system_registration")
        == related_records.RELATED_RECORD_SOURCES["system_registration"]
    )
    assert related_records.related_record_source_label("unknown-source") == "unknown-source"
    assert related_records.related_record_source_label("") == "Unknown source"
