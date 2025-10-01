"""Streamlit home screen focused on systems and assessments."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd
import streamlit as st

from lib.form_store import load_combined_schema
import lib.questionnaire_utils as questionnaire_utils
from lib.questionnaire_utils import RUNNER_SELECTED_STATE_KEY, normalize_questionnaires
from lib.risk_display import (
    aggregate_risks_for_system,
    normalise_risk_entries,
    risks_to_markdown,
)
from lib.ui_theme import apply_app_theme, page_header

# ``pages/01_Questionnaire.py`` imports ``load_schema`` from this module. Keep the
# function signature stable even though the rest of the home screen changed.
@st.cache_data(show_spinner=False)
def load_schema() -> Dict[str, Any]:
    """Load the combined questionnaire schema from local form files."""

    combined, _, _ = load_combined_schema()
    return combined


RECORD_NAME_KEY = getattr(questionnaire_utils, "RECORD_NAME_KEY", "record_name")
SYSTEM_SUBMISSIONS_DIR = Path("system_registration/submissions")
ASSESSMENT_SUBMISSIONS_DIR = Path("assessment/submissions")
DEFAULT_TABLE_COLUMNS = ("Submission ID", "Submitted at", "Questionnaire")
HOME_SELECTED_SYSTEM_KEY = "home_selected_system_id"
ANSWERS_STATE_KEY = "questionnaire_answers"
ASSESSMENT_KEY = "assessment"
SYSTEM_REGISTRATION_KEY = "system_registration"
RELATED_SYSTEM_FIELD = "related-sytem"


def _parse_timestamp(value: Any) -> tuple[str, float]:
    """Return a normalised timestamp string and sort key."""

    if isinstance(value, str) and value:
        text = value.strip()
        if text:
            try:
                dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError:
                return text, 0.0
            return dt.isoformat(), dt.timestamp()
    return "", 0.0


def _load_system_submission(path: Path) -> Dict[str, Any]:
    """Load a single system registration submission."""

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
    record_name = payload.get(RECORD_NAME_KEY)
    if isinstance(record_name, str) and record_name.strip():
        record["Record name"] = record_name.strip()
    for key, value in answers.items():
        record[str(key)] = value
    return record


def _load_systems(directory: Path) -> List[Dict[str, Any]]:
    """Return unique system submissions stored in ``directory``."""

    if not directory.exists():
        return []

    records: Dict[str, Dict[str, Any]] = {}
    for submission_file in sorted(directory.glob("*.json")):
        try:
            record = _load_system_submission(submission_file)
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
    """Return the ordered columns to use for the systems table."""

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
            continue

        answers = payload.get("answers", {})
        if not isinstance(answers, dict):
            answers = {}
        system_id = str(
            payload.get("related_system_id")
            or answers.get(RELATED_SYSTEM_FIELD, "")
        ).strip()
        if not system_id:
            continue

        timestamp, sort_key = _parse_timestamp(payload.get("submitted_at"))
        risk_entries = normalise_risk_entries(payload.get("risks"))
        record = {
            "submission_id": payload.get("id", submission_file.stem),
            "timestamp": timestamp,
            "_sort_key": sort_key,
            "system_id": system_id,
            "risks": risk_entries,
        }
        entries = links.setdefault(system_id, [])
        entries.append(record)

    for records in links.values():
        records.sort(key=lambda item: item.get("_sort_key", 0.0), reverse=True)

    return links


def _switch_to_questionnaire(selected_key: str) -> None:
    """Navigate to the questionnaire runner with ``selected_key`` selected."""

    st.session_state[RUNNER_SELECTED_STATE_KEY] = selected_key
    if hasattr(st, "switch_page"):
        try:
            st.switch_page("pages/01_Questionnaire.py")
        except Exception:  # pragma: no cover - streamlit navigation fallback
            st.info("Use the navigation menu to open the Questionnaire page.")
    else:
        st.info("Use the navigation menu to open the Questionnaire page.")


def _launch_assessment(system_id: str) -> None:
    """Open the assessment questionnaire with ``system_id`` preselected."""

    answers_state: Dict[str, Dict[str, Any]] = st.session_state.setdefault(ANSWERS_STATE_KEY, {})
    assessment_answers = answers_state.setdefault(ASSESSMENT_KEY, {})
    assessment_answers[RELATED_SYSTEM_FIELD] = system_id
    answers_state[ASSESSMENT_KEY] = assessment_answers
    st.session_state[ANSWERS_STATE_KEY] = answers_state
    _switch_to_questionnaire(ASSESSMENT_KEY)


def _launch_system_registration() -> None:
    """Open the system registration questionnaire."""

    answers_state: Dict[str, Dict[str, Any]] = st.session_state.setdefault(ANSWERS_STATE_KEY, {})
    answers_state.setdefault(SYSTEM_REGISTRATION_KEY, {})
    st.session_state[ANSWERS_STATE_KEY] = answers_state
    _switch_to_questionnaire(SYSTEM_REGISTRATION_KEY)


def main() -> None:
    """Render the home screen."""

    apply_app_theme(page_title="Assessment home", page_icon="🏠")
    page_header(
        "Assessment home",
        "Review systems, start assessments, and register new solutions.",
        icon="🏠",
    )

    schema = load_schema()
    questionnaires = normalize_questionnaires(schema) if schema else {}
    has_assessment = ASSESSMENT_KEY in questionnaires
    has_registration = SYSTEM_REGISTRATION_KEY in questionnaires

    if not has_assessment or not has_registration:
        st.warning(
            "Both the assessment and system registration questionnaires must be present "
            "to fully use this workflow."
        )

    systems = _load_systems(SYSTEM_SUBMISSIONS_DIR)
    assessment_links = _load_assessment_links()
    risk_level_counts = {
        "limited": 0,
        "high": 0,
        "unacceptable": 0,
        "unknown": 0,
    }
    total_risk_assignments = 0
    for record in systems:
        submission_id = str(record.get("Submission ID", ""))
        linked = assessment_links.get(submission_id, [])
        record["Has assessment"] = "Yes" if linked else "No"
        record["Latest assessment"] = linked[0]["submission_id"] if linked else "—"
        aggregated_risks = aggregate_risks_for_system(linked, submission_id)
        record["_aggregated_risks"] = aggregated_risks
        risk_summary = risks_to_markdown(aggregated_risks)
        record["Assigned risks"] = risk_summary or "—"
        record["Has assigned risks"] = "Yes" if aggregated_risks else "No"
        if aggregated_risks:
            total_risk_assignments += len(aggregated_risks)
            for risk in aggregated_risks:
                level = str(risk.get("level", "")).lower()
                key = level if level in risk_level_counts else "unknown"
                risk_level_counts[key] += 1

    total_systems = len(systems)
    unique_questionnaires = {
        str(record.get("Questionnaire", ""))
        for record in systems
        if str(record.get("Questionnaire", ""))
    }
    most_recent = systems[0].get("Submitted at", "—") if systems else "—"

    metric_col1, metric_col2, metric_col3 = st.columns(3)
    metric_col1.metric("Registered systems", total_systems or "0")
    metric_col2.metric("Questionnaires", len(unique_questionnaires) or "—")
    metric_col3.metric("Most recent registration", most_recent or "—")

    st.markdown("#### Risk overview")
    risk_metric_cols = st.columns(4)
    risk_metric_cols[0].metric("Total assigned risks", total_risk_assignments or "0")
    risk_metric_cols[1].metric("Unacceptable", risk_level_counts["unacceptable"] or "0")
    risk_metric_cols[2].metric("High", risk_level_counts["high"] or "0")
    risk_metric_cols[3].metric("Limited", risk_level_counts["limited"] or "0")
    if total_risk_assignments:
        if risk_level_counts["unknown"]:
            st.caption(
                f"Risks with unknown levels: {risk_level_counts['unknown']}"
            )
    else:
        st.caption(
            "Assessments have not assigned any risks yet. Launch an assessment to "
            "start tracking risk levels."
        )

    st.markdown("---")

    register_col, actions_col = st.columns([1, 3])
    with register_col:
        if st.button("Register a system", type="primary"):
            _launch_system_registration()

    if not systems:
        st.info("No systems registered yet. Start by registering a new system.")
        st.page_link("pages/01_Questionnaire.py", label="Open questionnaire", icon="🗒️")
        st.page_link("pages/03_Registered_Systems.py", label="View submissions", icon="📋")
        return

    columns = _table_columns(systems)
    table_rows = _strip_private_keys(systems)

    selected_system_id = st.session_state.get(HOME_SELECTED_SYSTEM_KEY)
    table_df = pd.DataFrame(table_rows, columns=columns)
    if "Select" not in table_df.columns:
        table_df.insert(0, "Select", False)
    else:
        table_df["Select"] = False
    if selected_system_id:
        table_df.loc[table_df["Submission ID"] == selected_system_id, "Select"] = True

    with st.container():
        st.markdown("<div class='app-card app-card--table'>", unsafe_allow_html=True)
        column_settings = {
            column: st.column_config.Column(column, disabled=True)
            for column in columns
        }
        if "Assigned risks" in column_settings:
            column_settings["Assigned risks"] = st.column_config.Column(
                "Assigned risks",
                disabled=True,
                help="Latest risk assignments linked to this system.",
                width="medium",
            )
        if "Has assigned risks" in column_settings:
            column_settings["Has assigned risks"] = st.column_config.Column(
                "Has assigned risks",
                disabled=True,
                help="Indicates whether any risks have been assigned to this system.",
                width="small",
            )

        edited_df = st.data_editor(
            table_df,
            hide_index=True,
            column_order=["Select", *columns],
            width="stretch",
            num_rows="fixed",
            key="home_systems_table",
            column_config={
                "Select": st.column_config.CheckboxColumn(
                    "Select",
                    help="Choose a system before launching an assessment.",
                ),
                **column_settings,
            },
        )
        st.markdown("</div>", unsafe_allow_html=True)

    selected_rows = edited_df.loc[edited_df["Select"].astype(bool)] if not edited_df.empty else edited_df
    candidate_id: Optional[str] = None
    if not selected_rows.empty:
        if len(selected_rows) > 1:
            st.warning("Select only one system at a time before launching an assessment.")
        else:
            candidate_id = str(selected_rows.iloc[0]["Submission ID"])
            st.session_state[HOME_SELECTED_SYSTEM_KEY] = candidate_id

    with actions_col:
        if candidate_id:
            if st.button("Launch assessment", type="primary", use_container_width=True):
                _launch_assessment(candidate_id)
        else:
            st.button(
                "Launch assessment",
                type="primary",
                use_container_width=True,
                disabled=True,
            )

    st.caption("Need to review details? Use the navigation menu to open the submissions pages.")
    st.page_link("pages/03_Registered_Systems.py", label="Registered systems", icon="📋")
    st.page_link("pages/04_Assessment_Submissions.py", label="Assessment submissions", icon="📝")


if __name__ == "__main__":
    main()
