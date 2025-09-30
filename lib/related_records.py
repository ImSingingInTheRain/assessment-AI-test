"""Utilities for referencing stored questionnaire submissions as related records."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from lib.questionnaire_utils import RECORD_NAME_KEY

PROJECT_ROOT = Path(__file__).resolve().parents[1]

RELATED_RECORD_SOURCES: Dict[str, str] = {
    "system_registration": "Registered systems",
    "assessment": "Assessment submissions",
}

SOURCE_DIRECTORIES: Dict[str, Path] = {
    "system_registration": PROJECT_ROOT / "system_registration" / "submissions",
    "assessment": PROJECT_ROOT / "assessment" / "submissions",
}


def related_record_source_label(source: str) -> str:
    """Return a human-friendly label for a related record ``source``."""

    return RELATED_RECORD_SOURCES.get(source, source or "Unknown source")


def _parse_timestamp(value: Any) -> Tuple[str, float]:
    """Normalise an ISO timestamp string, returning text and a sort key."""

    if isinstance(value, str) and value.strip():
        raw = value.strip()
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return raw, 0.0
        return parsed.isoformat(), parsed.timestamp()
    return "", 0.0


def _iter_submission_files(directory: Path) -> Iterable[Path]:
    """Yield submission files stored inside ``directory`` in a stable order."""

    if not directory.exists():
        return []
    return sorted(directory.glob("*.json"))


def load_related_record_options(source: str) -> List[Tuple[str, str]]:
    """Return ``(value, label)`` pairs for submissions from ``source``.

    The function de-duplicates submissions by identifier, preferring the most
    recent entry based on the ``submitted_at`` timestamp when available.
    """

    directory = SOURCE_DIRECTORIES.get(source)
    if directory is None:
        return []

    records: Dict[str, Tuple[str, str, float]] = {}

    for submission_file in _iter_submission_files(directory):
        try:
            with submission_file.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue

        submission_id = str(payload.get("id") or submission_file.stem)
        timestamp_text, sort_key = _parse_timestamp(payload.get("submitted_at"))
        record_name = payload.get(RECORD_NAME_KEY)
        if isinstance(record_name, str):
            record_name = record_name.strip()
        else:
            record_name = ""

        label_parts = []
        if record_name:
            label_parts.append(record_name)
        label_parts.append(submission_id)
        if timestamp_text:
            label_parts.append(timestamp_text)
        label = " · ".join(part for part in label_parts if part)

        existing = records.get(submission_id)
        if existing is None or sort_key > existing[2]:
            records[submission_id] = (submission_id, label, sort_key)

    entries = list(records.values())
    entries.sort(key=lambda item: (-item[2], item[0]))

    return [(identifier, label) for identifier, label, _ in entries]


__all__ = [
    "RELATED_RECORD_SOURCES",
    "SOURCE_DIRECTORIES",
    "load_related_record_options",
    "related_record_source_label",
]
