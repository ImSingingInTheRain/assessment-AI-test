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


def main() -> None:
    """Entry point for the landing page."""

    st.set_page_config(page_title="Config-driven Questionnaire", page_icon="📝")

    st.title("Config-driven Questionnaire")
    st.write(
        "This demo illustrates a questionnaire rendered from a JSON schema "
        "with declarative show/hide rules and a GitHub-backed editor."
    )

    schema = load_schema()
    if not schema:
        st.error("Schema file is missing. Please add form_schema.json to the project.")
        return

    questions: List[Dict[str, Any]] = schema.get("questions", [])
    st.success(f"Loaded {len(questions)} question(s) from the schema.")
    render_question_summary(questions)

    st.info(
        "Use the Questionnaire page to answer the form and the Editor page to "
        "manage questions."
    )


if __name__ == "__main__":
    main()
