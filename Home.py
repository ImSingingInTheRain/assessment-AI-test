"""Landing page for the questionnaire app."""

import json
from pathlib import Path
from typing import Any, Dict, List

import streamlit as st

SCHEMA_PATH = Path("form_schema.json")


@st.cache_data(show_spinner=False)
def load_schema() -> Dict[str, Any]:
    """Load questionnaire schema from the local JSON file."""
    if not SCHEMA_PATH.exists():
        return {}

    with SCHEMA_PATH.open("r", encoding="utf-8") as schema_file:
        return json.load(schema_file)


def render_question_summary(questions: List[Dict[str, Any]]) -> None:
    """Render a summary list of questions available in the schema."""

    for question in questions:
        with st.container():
            st.subheader(question.get("label", "Untitled question"))
            st.caption(f"Key: {question.get('key', 'n/a')}")
            st.write(f"Type: {question.get('type', 'unknown')}")
            if show_if := question.get("show_if"):
                st.write("Show rule:")
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

    st.subheader("Jump into the app")
    st.page_link("pages/01_Questionnaire.py", label="Questionnaire", icon="🧾")
    st.page_link("pages/02_Editor.py", label="Editor", icon="🛠️")

    render_launch_checklist()

    st.subheader("Schema health")
    schema_status = st.empty()

    try:
        schema = load_schema()
    except json.JSONDecodeError as exc:  # pragma: no cover - streamlit UI feedback
        schema_status.error("Schema failed to parse. See details below for fixes.")
        st.code(str(exc))
        return

    if not schema:
        schema_status.warning("Schema file not found. Add form_schema.json to continue.")
        return

    questions: List[Dict[str, Any]] = schema.get("questions", [])
    schema_status.success(f"Schema loaded with {len(questions)} question(s).")

    meta_col, version_col = st.columns(2)
    meta_col.metric("Title", schema.get("title", "—"))
    version_col.metric("Version", schema.get("version", "—"))

    with st.expander("Question overview", expanded=False):
        render_question_summary(questions)


if __name__ == "__main__":
    main()
