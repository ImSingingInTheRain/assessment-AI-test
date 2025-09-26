"""Authenticated editor page for managing questionnaire questions."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import streamlit as st

from Home import load_schema
from lib.github_backend import GitHubBackend

SCHEMA_STATE_KEY = "editor_schema"
QUESTION_TYPES = ["single", "multiselect", "bool", "text"]


def get_backend() -> Optional[GitHubBackend]:
    """Instantiate a GitHub backend using Streamlit secrets if available."""

    secrets = st.secrets.get("github", {})  # type: ignore[arg-type]
    token = secrets.get("token")
    repo = secrets.get("repo")
    path = secrets.get("path", "form_schema.json")
    branch = secrets.get("branch", "main")

    if token and repo and path:
        return GitHubBackend(token=token, repo=repo, path=path, branch=branch)
    return None


def get_schema() -> Dict[str, Any]:
    """Fetch the current schema for editing, caching in session state."""

    if SCHEMA_STATE_KEY not in st.session_state:
        schema = load_schema() or {"questions": []}
        st.session_state[SCHEMA_STATE_KEY] = schema
    return st.session_state[SCHEMA_STATE_KEY]


def parse_options(raw: str) -> List[str]:
    """Parse newline-separated options into a clean list."""

    return [option.strip() for option in raw.splitlines() if option.strip()]


def parse_show_if(raw: str) -> Optional[Dict[str, Any]]:
    """Parse the JSON show_if structure provided by the user."""

    if not raw.strip():
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as error:
        st.error(f"Invalid show_if JSON: {error.msg}")
        return None


def persist_schema(schema: Dict[str, Any], message: str) -> None:
    """Persist the schema using the GitHub backend or locally as a fallback."""

    backend = get_backend()
    if backend is not None:
        try:
            backend.write_json(schema, message)
            st.success("Schema saved to GitHub.")
        except Exception as exc:  # pylint: disable=broad-except
            st.error(f"Failed to save schema to GitHub: {exc}")
            return
    else:
        with open("form_schema.json", "w", encoding="utf-8") as schema_file:
            json.dump(schema, schema_file, indent=2)
        st.info("Schema saved locally. Configure GitHub secrets to enable remote persistence.")

    load_schema.clear()
    st.session_state[SCHEMA_STATE_KEY] = schema


def render_question_editor(question: Dict[str, Any], schema: Dict[str, Any]) -> None:
    """Render the editor form for a single question."""

    with st.form(f"edit_{question['key']}"):
        st.subheader(f"Edit question: {question['label']}")
        label = st.text_input("Label", value=question.get("label", ""))
        question_type = st.selectbox(
            "Type",
            options=QUESTION_TYPES,
            index=QUESTION_TYPES.index(question.get("type", "text")),
        )
        help_text = st.text_input("Help text", value=question.get("help", ""))
        placeholder = st.text_input("Placeholder", value=question.get("placeholder", ""))
        options_raw = st.text_area(
            "Options (one per line)",
            value="\n".join(question.get("options", [])),
            help="Applicable to single and multiselect questions.",
        )
        show_if_raw = st.text_area(
            "Show if (JSON)",
            value=json.dumps(question.get("show_if", {}), indent=2) if question.get("show_if") else "",
            help="Provide a JSON object describing show/hide rules.",
        )

        col_save, col_delete = st.columns([3, 1])
        with col_save:
            submitted = st.form_submit_button("Save changes")
        with col_delete:
            delete_requested = st.form_submit_button("Delete question", type="secondary")

        if submitted:
            options = parse_options(options_raw) if question_type in {"single", "multiselect"} else []
            show_if = parse_show_if(show_if_raw)
            if show_if_raw and show_if is None:
                return

            updated_question = {
                "key": question["key"],
                "label": label or question["key"],
                "type": question_type,
            }
            if help_text:
                updated_question["help"] = help_text
            if placeholder:
                updated_question["placeholder"] = placeholder
            if options:
                updated_question["options"] = options
            if show_if:
                updated_question["show_if"] = show_if

            for idx, existing in enumerate(schema.get("questions", [])):
                if existing.get("key") == question.get("key"):
                    schema["questions"][idx] = updated_question
                    break

            persist_schema(schema, message=f"Update question {question['key']}")

        if delete_requested:
            schema["questions"] = [
                q for q in schema.get("questions", []) if q.get("key") != question.get("key")
            ]
            persist_schema(schema, message=f"Remove question {question['key']}")


def render_add_question(schema: Dict[str, Any]) -> None:
    """Render the form to create a new question."""

    st.subheader("Add new question")
    with st.form("add_question"):
        key = st.text_input("Key")
        label = st.text_input("Label")
        question_type = st.selectbox("Type", options=QUESTION_TYPES)
        options_raw = st.text_area("Options (one per line)")
        show_if_raw = st.text_area("Show if (JSON)")
        submitted = st.form_submit_button("Add question")

        if submitted:
            if not key:
                st.error("Key is required.")
                return
            if any(question.get("key") == key for question in schema.get("questions", [])):
                st.error("A question with this key already exists.")
                return

            options = parse_options(options_raw) if question_type in {"single", "multiselect"} else []
            show_if = parse_show_if(show_if_raw)
            if show_if_raw and show_if is None:
                return

            new_question: Dict[str, Any] = {
                "key": key,
                "label": label or key,
                "type": question_type,
            }
            if options:
                new_question["options"] = options
            if show_if:
                new_question["show_if"] = show_if

            schema.setdefault("questions", []).append(new_question)
            persist_schema(schema, message=f"Add question {key}")


def main() -> None:
    """Render the questionnaire editor page."""

    st.title("Questionnaire editor")
    st.caption("Authentication is assumed to have already succeeded.")

    schema = get_schema()
    questions = schema.get("questions", [])

    if questions:
        question_keys = [question["key"] for question in questions]
        selected_key = st.selectbox("Select a question to edit", question_keys)
        selected_question = next((q for q in questions if q.get("key") == selected_key), None)
        if selected_question:
            render_question_editor(selected_question, schema)
    else:
        st.info("No questions defined yet. Add a question below.")

    render_add_question(schema)

    with st.expander("View raw schema"):
        st.json(schema)


if __name__ == "__main__":
    main()
