"""Landing page for the questionnaire app."""

import json
from html import escape as html_escape
from typing import Any, Dict, Iterable, List, Tuple

import streamlit as st

from lib.form_store import load_combined_schema
from lib.questionnaire_utils import (
    RUNNER_SELECTED_STATE_KEY,
    iter_questionnaires,
    normalize_questionnaires,
)
from lib.ui_theme import apply_app_theme, page_header, render_card


@st.cache_data(show_spinner=False)
def load_schema() -> Dict[str, Any]:
    """Load the combined questionnaire schema from local form files."""

    combined, _, _ = load_combined_schema()
    return combined


def render_question_summary(questionnaires: Iterable[Tuple[str, Dict[str, Any]]]) -> None:
    """Render a summary of the available questionnaires and their questions."""

    for questionnaire_key, questionnaire in questionnaires:
        questions: List[Dict[str, Any]] = questionnaire.get("questions", [])
        label = questionnaire.get("label", questionnaire_key)
        safe_label = html_escape(str(label))
        if not questions:
            render_card(
                "<p class='app-muted'>No questions configured yet.</p>",
                title=safe_label,
                compact=True,
            )
            continue

        question_markup: List[str] = []
        for question in questions:
            question_label = html_escape(str(question.get("label", "Untitled question")))
            question_key = html_escape(str(question.get("key", "n/a")))
            question_type = html_escape(str(question.get("type", "unknown")))
            item_markup = [
                f"<strong>{question_label}</strong>",
                (
                    f"<div class='app-question-list__meta'>"
                    f"Key: <code>{question_key}</code> · Type: <code>{question_type}</code>"
                    "</div>"
                ),
            ]
            if show_if := question.get("show_if"):
                show_if_code = html_escape(json.dumps(show_if, indent=2))
                item_markup.append(
                    f"<pre><code class='language-json'>{show_if_code}</code></pre>"
                )
            question_markup.append(
                f"<li class='app-question-list__item'>{''.join(item_markup)}</li>"
            )

        render_card(
            f"<ul class='app-question-list'>{''.join(question_markup)}</ul>",
            title=safe_label,
            compact=True,
        )


def render_launch_checklist() -> None:
    """Display the quick launch checklist for the workflow."""

    checklist_steps = [
        "Configure secrets",
        "Create personal access token",
        "Open a draft pull request",
        "Publish the updated schema",
    ]
    checklist_markup = "".join(
        f"<li><span class='app-checklist__badge'>{index}</span>{html_escape(step)}</li>"
        for index, step in enumerate(checklist_steps, start=1)
    )
    render_card(
        f"<ul class='app-checklist'>{checklist_markup}</ul>",
        title="Launch checklist",
        compact=True,
    )


def main() -> None:
    """Entry point for the landing page."""

    apply_app_theme(page_title="Config-driven Questionnaire", page_icon="📝")

    page_header(
        "Config-driven Questionnaire Hub",
        "A single JSON schema powering runner, editor, and review workflows.",
        icon="📝",
    )

    render_card(
        """
        <p>
            Welcome! This project demonstrates how a centrally managed JSON schema can
            deliver a polished questionnaire experience alongside tools for editing and
            reviewing responses.
        </p>
        <p>
            Use the quick links and launch checklist below to jump into the workflow that
            matters most for your team.
        </p>
        """,
        title="Getting started",
    )

    render_launch_checklist()

    st.subheader("Schema health")
    schema_status = st.empty()

    try:
        schema = load_schema()
    except json.JSONDecodeError as exc:  # pragma: no cover - streamlit UI feedback
        schema_status.error("Schema failed to parse. See details below for fixes.")
        st.code(str(exc))
        return

    questionnaires = normalize_questionnaires(schema)
    if not schema or not questionnaires:
        schema_status.warning(
            "Schema files not found. Add form_schemas/<name>/form_schema.json to continue."
        )
        return

    total_questions = sum(len(entry.get("questions", [])) for entry in questionnaires.values())
    schema_status.success(
        f"Schema loaded with {len(questionnaires)} questionnaire(s) and {total_questions} question(s)."
    )

    meta_col, version_col = st.columns(2)
    meta_col.metric("Title", schema.get("title", "—"))
    version_col.metric("Version", schema.get("version", "—"))

    st.subheader("Choose where to start")
    choice_options = [
        (key, entry.get("label", key), len(entry.get("questions", [])))
        for key, entry in questionnaires.items()
    ]

    if not choice_options:
        st.info("No questionnaires configured yet. Use the editor to add one.")
    else:
        option_labels = [
            f"{label} ({count} question{'s' if count != 1 else ''})"
            for _, label, count in choice_options
        ]
        selected_index = 0
        initial_selection = st.session_state.get(RUNNER_SELECTED_STATE_KEY)
        if initial_selection:
            for idx, (key, _, _) in enumerate(choice_options):
                if key == initial_selection:
                    selected_index = idx
                    break
        selection = st.selectbox(
            "Questionnaire",
            options=option_labels,
            index=selected_index,
            help="Select which questionnaire to open in the runner.",
        )
        selected_key = choice_options[option_labels.index(selection)][0]
        st.session_state[RUNNER_SELECTED_STATE_KEY] = selected_key

        def _switch_to_questionnaire() -> None:
            if hasattr(st, "switch_page"):
                st.switch_page("pages/01_Questionnaire.py")
            else:
                st.info(
                    "Use the navigation menu to open the Questionnaire page. "
                    "Your selection will be remembered."
                )

        if st.button("Start questionnaire", type="primary"):
            _switch_to_questionnaire()

    st.page_link("pages/02_Editor.py", label="Open editor", icon="🛠️")

    with st.expander("Question overview", expanded=False):
        render_question_summary(iter_questionnaires(schema))


if __name__ == "__main__":
    main()
