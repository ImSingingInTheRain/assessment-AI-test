"""Streamlit page listing system registration submissions."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import streamlit as st

from lib import questionnaire_utils

RECORD_NAME_KEY = getattr(questionnaire_utils, "RECORD_NAME_KEY", "record_name")

SUBMISSIONS_DIR = Path("system_registration/submissions")
DEFAULT_TABLE_COLUMNS = ("Submission ID", "Submitted at", "Questionnaire")


def _parse_timestamp(value: Any) -> Tuple[str, float]:
    """Return a normalised timestamp string and a sort key."""

    if isinstance(value, str) and value:
        text = value.strip()
        if text:
            try:
                dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError:
                return text, 0.0
            return dt.isoformat(), dt.timestamp()
    return "", 0.0


def _load_submission(path: Path) -> Dict[str, Any]:
    """Load a single system registration submission from ``path``."""

    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    answers = payload.get("answers", {})
    if not isinstance(answers, dict):
        answers = {}
    record: Dict[str, Any] = {
        "Submission ID": payload.get("id", path.stem),
        "Questionnaire": payload.get("questionnaire_key", ""),
    }
    timestamp, sort_key = _parse_timestamp(payload.get("submitted_at"))
    record["Submitted at"] = timestamp
    record["_sort_key"] = sort_key

    record_name = payload.get(RECORD_NAME_KEY)
    if isinstance(record_name, str) and record_name.strip():
        record["Record name"] = record_name.strip()

    for key, value in answers.items():
        record[str(key)] = value

    return record


def _load_submissions(directory: Path) -> List[Dict[str, Any]]:
    """Return unique submission records stored under ``directory``."""

    if not directory.exists():
        return []

    records: Dict[str, Dict[str, Any]] = {}
    for submission_file in sorted(directory.glob("*.json")):
        try:
            record = _load_submission(submission_file)
        except json.JSONDecodeError:
            st.warning(f"Skipping invalid submission file: {submission_file.name}")
            continue
        submission_id = str(record.get("Submission ID", submission_file.stem))
        if submission_id in records:
            existing_sort = records[submission_id].get("_sort_key", 0.0)
            if record.get("_sort_key", 0.0) > existing_sort:
                records[submission_id] = record
        else:
            records[submission_id] = record

    return sorted(records.values(), key=lambda item: item.get("_sort_key", 0.0), reverse=True)


def _table_columns(records: Iterable[Dict[str, Any]]) -> List[str]:
    """Return the ordered columns to use for the submissions table."""

    columns = list(DEFAULT_TABLE_COLUMNS)
    for record in records:
        for key in record:
            if key.startswith("_"):
                continue
            if key not in columns:
                columns.append(key)
    return columns


def _strip_private_keys(records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove helper keys (prefixed with ``_``) from the table rows."""

    cleaned: List[Dict[str, Any]] = []
    for record in records:
        cleaned.append({key: value for key, value in record.items() if not key.startswith("_")})
    return cleaned


st.set_page_config(page_title="Registered systems", page_icon="📋")
st.title("Registered systems")

st.write(
    "Browse the systems registered through the questionnaire. "
    "Duplicate submissions are grouped by their identifier, showing the most recent entry."
)

submissions = _load_submissions(SUBMISSIONS_DIR)

if not submissions:
    st.info("No system registration submissions found yet.")
else:
    columns = _table_columns(submissions)
    table_rows = _strip_private_keys(submissions)
    st.dataframe(
        table_rows,
        width="stretch",
        hide_index=True,
        column_order=columns,
    )

