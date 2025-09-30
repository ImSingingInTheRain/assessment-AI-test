"""Landing page for the questionnaire app."""

import json
from typing import Any, Dict, Iterable, List, Tuple

import streamlit as st

from lib.form_store import load_combined_schema
from lib.questionnaire_utils import (
    RUNNER_SELECTED_STATE_KEY,
    iter_questionnaires,
    normalize_questionnaires,
)


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
        with st.container():
            st.markdown(f"### {label}")
            if not questions:
                st.caption("No questions configured yet.")
                continue
            for question in questions:
                st.markdown(
                    f"**{question.get('label', 'Untitled question')}**  "
                    f"Key: `{question.get('key', 'n/a')}`  ·  "
                    f"Type: `{question.get('type', 'unknown')}`"
                )
                if show_if := question.get("show_if"):
                    st.code(json.dumps(show_if, indent=2), language="json")


def render_launch_checklist() -> None:
    """Display the quick launch checklist for the workflow."""

    st.subheader("Launch checklist")
    st.markdown(
        "\n".join(
            [
                "- [ ] 1. Configure secrets",
                "- [ ] 2. Create PAT",
                "- [ ] 3. Open PR on draft",
                "- [ ] 4. Publish",
            ]
        )
    )


def main() -> None:
    """Entry point for the landing page."""

    st.set_page_config(page_title="Config-driven Questionnaire", page_icon="📝")

    st.title("Config-driven Questionnaire Hub")
    st.write(
        "Welcome! This project demonstrates how a JSON schema can power both a "
        "questionnaire experience and a lightweight editing interface."
    )

    st.write(
        "Use the links below to jump into the interactive pages or review the "
        "launch checklist to get your workflow ready."
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
