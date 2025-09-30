"""Streamlit page listing assessment questionnaire submissions."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
import sys
from typing import Any, Dict, Iterable, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st

from lib import questionnaire_utils
from lib.ui_theme import apply_app_theme, page_header

RECORD_NAME_KEY = getattr(questionnaire_utils, "RECORD_NAME_KEY", "record_name")

SUBMISSIONS_DIR = Path("assessment/submissions")
DEFAULT_TABLE_COLUMNS = ("Submission ID", "Submitted at", "Questionnaire")
SUBMISSION_ID_PARAM = "submission_id"


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
    """Load a single assessment submission from ``path``."""

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
    record["_raw_payload"] = payload
    record["_path"] = path

    record_name = payload.get(RECORD_NAME_KEY)
    if isinstance(record_name, str) and record_name.strip():
        record["Record name"] = record_name.strip()

    for key, value in answers.items():
        record[str(key)] = value

    return record


def _load_submissions(directory: Path) -> List[Dict[str, Any]]:
    """Return unique assessment submission records stored under ``directory``."""

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


def _format_option(record: Optional[Dict[str, Any]]) -> str:
    """Return a human-friendly label for the submission selection."""

    if not record:
        return "— Select a submission —"
    submission_id = str(record.get("Submission ID", ""))
    record_name = str(record.get("Record name", "")).strip()
    timestamp = str(record.get("Submitted at", "")).strip()
    parts = [part for part in (record_name or None, submission_id or None, timestamp or None) if part]
    return " · ".join(parts) if parts else submission_id or "Submission"


def _get_query_param(name: str) -> Optional[str]:
    """Return a query parameter value for ``name`` when available."""

    try:
        value = st.query_params.get(name)
    except AttributeError:
        params = st.experimental_get_query_params()
        value = params.get(name)
    if isinstance(value, list):
        return value[0] if value else None
    if isinstance(value, str):
        return value
    return None


def _set_query_param(name: str, value: Optional[str]) -> None:
    """Store ``value`` for ``name`` in the query string."""

    try:
        if hasattr(st, "query_params"):
            params = dict(st.query_params)
            if value is None:
                params.pop(name, None)
            else:
                params[name] = value
            st.query_params.clear()
            for key, val in params.items():
                st.query_params[key] = val
        else:
            params = st.experimental_get_query_params()
            if value is None:
                params.pop(name, None)
            else:
                params[name] = value
            st.experimental_set_query_params(**params)
    except Exception:  # pylint: disable=broad-except
        # Setting query parameters is a convenience. Ignore failures silently.
        pass


def _rerun() -> None:
    """Trigger a Streamlit rerun using the available API."""

    try:
        st.experimental_rerun()
    except AttributeError:
        st.rerun()


apply_app_theme(page_title="Assessment submissions", page_icon="📝")
page_header(
    "Assessment submissions",
    "Browse the assessment responses submitted through the questionnaire. Duplicate submissions are grouped by their identifier, showing the most recent entry.",
    icon="📝",
)

submissions = _load_submissions(SUBMISSIONS_DIR)

if not submissions:
    st.info("No assessment submissions found yet.")
else:
    unique_questionnaires = {
        str(record.get("Questionnaire", ""))
        for record in submissions
        if str(record.get("Questionnaire", ""))
    }
    most_recent = submissions[0].get("Submitted at", "—")
    col1, col2, col3 = st.columns(3)
    col1.metric("Total submissions", len(submissions))
    col2.metric("Questionnaires", len(unique_questionnaires) or "—")
    col3.metric("Most recent submission", most_recent or "—")

    columns = _table_columns(submissions)
    table_rows = _strip_private_keys(submissions)
    with st.container():
        st.markdown("<div class='app-card app-card--table'>", unsafe_allow_html=True)
        st.dataframe(
            table_rows,
            width="stretch",
            hide_index=True,
            column_order=columns,
        )
        st.markdown("</div>", unsafe_allow_html=True)

    options: List[Optional[Dict[str, Any]]] = [None] + submissions
    default_index = 0
    preselected = _get_query_param(SUBMISSION_ID_PARAM)
    if preselected:
        for idx, record in enumerate(submissions, start=1):
            if str(record.get("Submission ID")) == preselected:
                default_index = idx
                break

    selected = st.selectbox(
        "Manage submission",
        options,
        index=default_index,
        format_func=_format_option,
        key="assessment_submission_selector",
    )

    if selected:
        submission_id = str(selected.get("Submission ID"))
        _set_query_param(SUBMISSION_ID_PARAM, submission_id)
        st.subheader("Submission details")
        st.write(
            f"**Submission ID:** `{submission_id}`  ",
            f"**Questionnaire:** {selected.get('Questionnaire') or '—'}  ",
            f"**Submitted at:** {selected.get('Submitted at') or '—'}",
        )

        payload = selected.get("_raw_payload", {})
        if isinstance(payload, dict):
            st.markdown("**Stored payload**")
            st.json(payload)

        default_text = json.dumps(payload, indent=2, sort_keys=True)
        editor_key = f"assessment_submission_editor::{submission_id}"
        widget_key = f"assessment_submission_text::{submission_id}"
        if editor_key not in st.session_state:
            st.session_state[editor_key] = default_text
        edited_text = st.text_area(
            "Edit submission JSON",
            value=st.session_state[editor_key],
            height=300,
            key=widget_key,
        )
        st.session_state[editor_key] = edited_text

        col_save, col_delete = st.columns([3, 1])
        with col_save:
            if st.button("Save changes", type="primary", key=f"assessment_save::{submission_id}"):
                try:
                    updated_payload = json.loads(edited_text)
                except json.JSONDecodeError as exc:
                    st.error(f"Invalid JSON: {exc}.")
                else:
                    if not isinstance(updated_payload, dict):
                        st.error("Submission data must be a JSON object.")
                    else:
                        current_id = str(updated_payload.get("id") or "").strip()
                        if current_id and current_id != submission_id:
                            st.error(
                                "The submission ID inside the JSON must match the filename. "
                                "Please keep the original ID."
                            )
                        else:
                            updated_payload.setdefault("id", submission_id)
                            path = selected.get("_path")
                            if isinstance(path, Path):
                                try:
                                    with path.open("w", encoding="utf-8") as handle:
                                        json.dump(updated_payload, handle, indent=2)
                                        handle.write("\n")
                                except OSError as exc:
                                    st.error(f"Failed to save submission: {exc}.")
                                else:
                                    st.success("Submission updated successfully.")
                                    st.session_state.pop(editor_key, None)
                                    st.session_state.pop(widget_key, None)
                                    _rerun()
                            else:
                                st.error("Unable to determine the submission file path.")

        with col_delete:
            if st.button(
                "Delete", type="secondary", key=f"assessment_delete::{submission_id}"
            ):
                path = selected.get("_path")
                if isinstance(path, Path):
                    try:
                        path.unlink()
                    except OSError as exc:
                        st.error(f"Failed to delete submission: {exc}.")
                    else:
                        st.success("Submission deleted successfully.")
                        st.session_state.pop(editor_key, None)
                        st.session_state.pop(widget_key, None)
                        _set_query_param(SUBMISSION_ID_PARAM, None)
                        _rerun()
                else:
                    st.error("Unable to determine the submission file path.")
    else:
        _set_query_param(SUBMISSION_ID_PARAM, None)
