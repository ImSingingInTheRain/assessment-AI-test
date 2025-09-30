"""Streamlit page listing system registration submissions."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlencode

import pandas as pd
import streamlit as st

from lib import questionnaire_utils
from lib.ui_theme import apply_app_theme, page_header
from lib.submission_storage import delete_submission_files

RECORD_NAME_KEY = getattr(questionnaire_utils, "RECORD_NAME_KEY", "record_name")

SUBMISSIONS_DIR = Path("system_registration/submissions")
ASSESSMENT_SUBMISSIONS_DIR = Path("assessment/submissions")
DEFAULT_TABLE_COLUMNS = ("Submission ID", "Submitted at", "Questionnaire")
SYSTEM_ID_PARAM = "system_id"
RELATED_SYSTEM_FIELD = "related-sytem"
ASSESSMENT_QUERY_PARAM = "submission_id"
MANAGED_SYSTEM_KEY = "system_managed_submission_id"


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
    record["_raw_payload"] = payload
    record["_path"] = path

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


def _format_editor_value(value: Any) -> str:
    """Return ``value`` formatted for display in the visual editor."""

    if value is None:
        return ""
    if isinstance(value, (dict, list, bool, int, float)):
        try:
            return json.dumps(value, ensure_ascii=False)
        except TypeError:
            return str(value)
    return str(value)


def _parse_editor_value(value: Any) -> Any:
    """Return the Python value represented by ``value`` from the editor."""

    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return ""
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return stripped
    return value


def _prepare_answers_dataframe(answers: Dict[str, Any]) -> pd.DataFrame:
    """Return a dataframe representing ``answers`` for editing."""

    rows = [
        {"Question": str(key), "Answer": _format_editor_value(value)}
        for key, value in answers.items()
    ]
    if not rows:
        rows = [{"Question": "", "Answer": ""}]
    return pd.DataFrame(rows, columns=["Question", "Answer"])


def _answers_from_dataframe(data: pd.DataFrame) -> Dict[str, Any]:
    """Convert edited answers back to a mapping."""

    answers: Dict[str, Any] = {}
    if data is None:
        return answers
    for _, row in data.iterrows():
        key = str(row.get("Question") or "").strip()
        if not key:
            continue
        answers[key] = _parse_editor_value(row.get("Answer"))
    return answers


def _prepare_metadata_dataframe(payload: Dict[str, Any]) -> pd.DataFrame:
    """Return editable metadata rows excluding known submission keys."""

    known_keys = {"id", "questionnaire_key", "submitted_at", "answers", RECORD_NAME_KEY}
    rows = [
        {"Field": str(key), "Value": _format_editor_value(payload[key])}
        for key in payload
        if key not in known_keys
    ]
    if not rows:
        rows = [{"Field": "", "Value": ""}]
    return pd.DataFrame(rows, columns=["Field", "Value"])


def _metadata_from_dataframe(data: pd.DataFrame) -> Dict[str, Any]:
    """Return a mapping extracted from edited metadata rows."""

    values: Dict[str, Any] = {}
    if data is None:
        return values
    for _, row in data.iterrows():
        field = str(row.get("Field") or "").strip()
        if not field:
            continue
        values[field] = _parse_editor_value(row.get("Value"))
    return values


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
        pass


def _rerun() -> None:
    """Trigger a Streamlit rerun using the available API."""

    try:
        st.experimental_rerun()
    except AttributeError:
        st.rerun()


def _render_page_link(page: str, *, label: str, icon: str = "", params: Optional[Dict[str, Any]] = None) -> None:
    """Render a link to another Streamlit page, preserving query parameters when needed."""

    query = urlencode(params or {}) if params else ""
    url = f"./{page}{f'?{query}' if query else ''}"

    if params:
        st.markdown(f"[{label}]({url})", unsafe_allow_html=False)
        return

    try:
        st.page_link(page, label=label, icon=icon)
    except (AttributeError, TypeError):
        st.markdown(f"[{label}]({url})", unsafe_allow_html=False)


def _load_assessment_links() -> Dict[str, List[Dict[str, Any]]]:
    """Return assessment submissions keyed by referenced system ID."""

    links: Dict[str, List[Dict[str, Any]]] = {}
    if not ASSESSMENT_SUBMISSIONS_DIR.exists():
        return links

    for submission_file in sorted(ASSESSMENT_SUBMISSIONS_DIR.glob("*.json")):
        try:
            with submission_file.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError):
            st.warning(f"Skipping invalid assessment file: {submission_file.name}")
            continue

        answers = payload.get("answers", {})
        if not isinstance(answers, dict):
            continue
        system_id = str(answers.get(RELATED_SYSTEM_FIELD, "")).strip()
        if not system_id:
            continue

        timestamp, sort_key = _parse_timestamp(payload.get("submitted_at"))
        record = {
            "submission_id": payload.get("id", submission_file.stem),
            "timestamp": timestamp,
            "_sort_key": sort_key,
            "_path": submission_file,
            "payload": payload,
        }
        entries = links.setdefault(system_id, [])
        entries.append(record)

    for records in links.values():
        records.sort(key=lambda item: item.get("_sort_key", 0.0), reverse=True)

    return links


apply_app_theme(page_title="Registered systems", page_icon="📋")
page_header(
    "Registered systems",
    "Browse the systems registered through the questionnaire. Duplicate submissions are grouped by their identifier, showing the most recent entry.",
    icon="📋",
)

submissions = _load_submissions(SUBMISSIONS_DIR)

if not submissions:
    st.info("No system registration submissions found yet.")
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

    assessment_links = _load_assessment_links()
    for record in submissions:
        submission_id = str(record.get("Submission ID", ""))
        linked = assessment_links.get(submission_id, [])
        record["_linked_assessments"] = linked
        record["Has assessment"] = "Yes" if linked else "No"
        record["Latest assessment"] = linked[0]["submission_id"] if linked else "—"

    records_by_id = {str(record.get("Submission ID")): record for record in submissions}

    columns = _table_columns(submissions)
    table_rows = _strip_private_keys(submissions)

    managed_id = st.session_state.get(MANAGED_SYSTEM_KEY)
    preselected = _get_query_param(SYSTEM_ID_PARAM)
    if preselected and preselected in records_by_id:
        managed_id = preselected
        st.session_state[MANAGED_SYSTEM_KEY] = preselected
    elif preselected and preselected not in records_by_id:
        _set_query_param(SYSTEM_ID_PARAM, None)
    if managed_id and managed_id not in records_by_id:
        st.session_state.pop(MANAGED_SYSTEM_KEY, None)
        managed_id = None

    table_df = pd.DataFrame(table_rows, columns=columns)
    if "Select" not in table_df.columns:
        table_df.insert(0, "Select", False)
    else:
        table_df["Select"] = False
    if managed_id:
        table_df.loc[table_df["Submission ID"] == managed_id, "Select"] = True

    with st.container():
        st.markdown("<div class='app-card app-card--table'>", unsafe_allow_html=True)
        edited_df = st.data_editor(
            table_df,
            hide_index=True,
            column_order=["Select", *columns],
            width="stretch",
            num_rows="fixed",
            key="system_submissions_table",
            column_config={
                "Select": st.column_config.CheckboxColumn(
                    "Select",
                    help="Choose a system to manage.",
                ),
                **{
                    column: st.column_config.Column(column, disabled=True)
                    for column in columns
                },
            },
        )
        st.markdown("</div>", unsafe_allow_html=True)

    selected_rows = edited_df.loc[edited_df["Select"].astype(bool)] if not edited_df.empty else edited_df
    candidate_id: Optional[str] = None
    if not selected_rows.empty:
        if len(selected_rows) > 1:
            st.warning("Select only one system submission to manage at a time.")
        else:
            candidate_id = str(selected_rows.iloc[0]["Submission ID"])

    if candidate_id:
        if candidate_id == managed_id:
            st.info("You are currently viewing the selected system.")
        else:
            if st.button("Manage selected system", type="primary"):
                st.session_state[MANAGED_SYSTEM_KEY] = candidate_id
                _set_query_param(SYSTEM_ID_PARAM, candidate_id)
                managed_id = candidate_id
                st.success("System ready to manage below.")

    if managed_id:
        selected = records_by_id.get(managed_id)
        if not selected:
            st.info("The selected system submission is no longer available.")
            st.session_state.pop(MANAGED_SYSTEM_KEY, None)
            _set_query_param(SYSTEM_ID_PARAM, None)
        else:
            submission_id = str(selected.get("Submission ID"))
            st.subheader("Submission details")
            st.write(
                f"**Submission ID:** `{submission_id}`  ",
                f"**Questionnaire:** {selected.get('Questionnaire') or '—'}  ",
                f"**Submitted at:** {selected.get('Submitted at') or '—'}",
            )

            payload = selected.get("_raw_payload", {})
            if not isinstance(payload, dict):
                st.error("Submission payload is not a JSON object and cannot be edited visually.")
                st.stop()

            answers = payload.get("answers", {})
            if not isinstance(answers, dict):
                answers = {}

            answers_df = _prepare_answers_dataframe(answers)
            metadata_df = _prepare_metadata_dataframe(payload)

            form_key = f"system_submission_form::{submission_id}"
            answers_key = f"system_answers_editor::{submission_id}"
            metadata_key = f"system_metadata_editor::{submission_id}"

            with st.form(form_key):
                questionnaire_value = st.text_input(
                    "Questionnaire key",
                    value=str(payload.get("questionnaire_key") or ""),
                )
                submitted_value = st.text_input(
                    "Submitted at",
                    value=str(payload.get("submitted_at") or ""),
                    help="Use ISO 8601 format when updating timestamps.",
                )
                record_name_value = st.text_input(
                    "Record name",
                    value=str(payload.get(RECORD_NAME_KEY) or ""),
                )

                st.markdown("**Answers**")
                edited_answers = st.data_editor(
                    answers_df,
                    hide_index=True,
                    num_rows="dynamic",
                    width="stretch",
                    key=answers_key,
                    column_config={
                        "Question": st.column_config.TextColumn("Question", required=True),
                        "Answer": st.column_config.TextColumn(
                            "Answer",
                            help="Provide values as text or JSON."
                        ),
                    },
                )

                st.markdown("**Additional fields**")
                edited_metadata = st.data_editor(
                    metadata_df,
                    hide_index=True,
                    num_rows="dynamic",
                    width="stretch",
                    key=metadata_key,
                    column_config={
                        "Field": st.column_config.TextColumn("Field", required=True),
                        "Value": st.column_config.TextColumn(
                            "Value",
                            help="Provide values as text or JSON."
                        ),
                    },
                )

                save_clicked = st.form_submit_button("Save changes", type="primary")

            if save_clicked:
                updated_payload = dict(payload)
                updated_payload["questionnaire_key"] = questionnaire_value.strip()
                if submitted_value.strip():
                    updated_payload["submitted_at"] = submitted_value.strip()
                else:
                    updated_payload.pop("submitted_at", None)
                record_name_clean = record_name_value.strip()
                if record_name_clean:
                    updated_payload[RECORD_NAME_KEY] = record_name_clean
                else:
                    updated_payload.pop(RECORD_NAME_KEY, None)

                updated_payload["answers"] = _answers_from_dataframe(edited_answers)

                for key in list(updated_payload.keys()):
                    if key not in {"id", "questionnaire_key", "submitted_at", "answers", RECORD_NAME_KEY}:
                        updated_payload.pop(key)
                for key, value in _metadata_from_dataframe(edited_metadata).items():
                    updated_payload[key] = value

                updated_payload.setdefault("id", submission_id)
                current_id = str(updated_payload.get("id") or "").strip()
                if current_id != submission_id:
                    st.error("The submission ID inside the payload must match the stored filename.")
                else:
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
                            _rerun()
                    else:
                        st.error("Unable to determine the submission file path.")

            col_delete = st.columns([1, 3])[0]
            with col_delete:
                if st.button("Delete submission", type="secondary"):
                    path = selected.get("_path")
                    if isinstance(path, Path):
                        submission_id = str(selected.get("Submission ID") or "").strip()
                        try:
                            path.unlink()
                        except OSError as exc:
                            st.error(f"Failed to delete submission: {exc}.")
                        else:
                            removed_extra, failed_extra = [], []
                            if submission_id:
                                removed_extra, failed_extra = delete_submission_files(
                                    submission_id,
                                    SUBMISSIONS_DIR,
                                    skip_paths=[path],
                                )

                            if failed_extra:
                                failed_names = ", ".join(candidate.name for candidate in failed_extra)
                                st.warning(
                                    "Deleted the selected submission but failed to remove "
                                    f"additional copies: {failed_names}."
                                )

                            st.success("Submission deleted successfully.")
                            st.session_state.pop(MANAGED_SYSTEM_KEY, None)
                            _set_query_param(SYSTEM_ID_PARAM, None)
                            _rerun()
                    else:
                        st.error("Unable to determine the submission file path.")

            with st.expander("Raw payload", expanded=False):
                st.json(payload)

            linked_assessments: List[Dict[str, Any]] = selected.get("_linked_assessments", [])
            if linked_assessments:
                st.info(
                    f"This system is referenced by {len(linked_assessments)} assessment submission"
                    f"{'s' if len(linked_assessments) != 1 else ''}."
                )
                for index, assessment in enumerate(linked_assessments, start=1):
                    assessment_id = assessment.get("submission_id", "")
                    timestamp = assessment.get("timestamp") or "—"
                    header = f"Assessment {index}: {assessment_id or 'Unknown'} ({timestamp})"
                    with st.expander(header, expanded=False):
                        if assessment_id:
                            st.write(f"**Submission ID:** `{assessment_id}`  **Submitted at:** {timestamp}")
                        else:
                            st.write(f"**Submitted at:** {timestamp}")

                        params = {ASSESSMENT_QUERY_PARAM: assessment_id} if assessment_id else {}
                        _render_page_link(
                            "pages/04_Assessment_Submissions.py",
                            label="Open in assessment submissions",
                            icon="📝",
                            params=params or None,
                        )

                        payload = assessment.get("payload")
                        if isinstance(payload, dict):
                            st.json(payload)
            else:
                st.info("No assessment submissions currently reference this system.")
    else:
        _set_query_param(SYSTEM_ID_PARAM, None)

