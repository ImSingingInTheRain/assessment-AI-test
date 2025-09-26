"""Streamlit page to render the questionnaire from a JSON schema."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

import requests
import streamlit as st

from Home import load_schema


@dataclass(frozen=True)
class GHConfig:
    """Configuration required to fetch a file from GitHub."""

    repo: str
    path: str
    ref: str = "main"
    token: Optional[str] = None


@st.cache_data(ttl=60, show_spinner=False)
def get_file(config: GHConfig) -> str:
    """Download a file from GitHub using the raw content endpoint."""

    headers = {"Accept": "application/vnd.github.v3.raw"}
    if config.token:
        headers["Authorization"] = f"Bearer {config.token}"

    url = f"https://raw.githubusercontent.com/{config.repo}/{config.ref}/{config.path}"
    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()
    return response.text


def load_schema_from_github() -> Dict[str, Any]:
    """Fetch the questionnaire schema from GitHub if configuration is provided."""

    github_settings = st.secrets.get("github", {})  # type: ignore[arg-type]
    repo = github_settings.get("repo")
    path = github_settings.get("path", "form_schema.json")
    ref = github_settings.get("branch", "main")
    token = github_settings.get("token")

    if not repo or not path:
        return {}

    config = GHConfig(repo=repo, path=path, ref=ref, token=token)
    contents = get_file(config)
    return json.loads(contents)

ANSWERS_STATE_KEY = "questionnaire_answers"


def evaluate_condition(condition: Dict[str, Any], answers: Dict[str, Any]) -> bool:
    """Evaluate a single condition or a group of conditions."""

    if "all" in condition:
        return all(evaluate_condition(item, answers) for item in condition["all"])
    if "any" in condition:
        return any(evaluate_condition(item, answers) for item in condition["any"])

    operator = condition.get("operator")
    field = condition.get("field")
    expected = condition.get("value")
    value = answers.get(field)

    if operator == "equals":
        return value == expected
    if operator == "not_equals":
        return value != expected
    if operator == "includes":
        if value is None:
            return False
        if isinstance(value, (list, tuple, set)):
            return expected in value
        return value == expected
    if operator == "not_includes":
        if value is None:
            return True
        if isinstance(value, (list, tuple, set)):
            return expected not in value
        return value != expected
    if operator == "any_selected":
        if not isinstance(value, Sequence) or isinstance(value, str):
            return False
        if not isinstance(expected, Sequence) or isinstance(expected, str):
            return False
        return any(item in value for item in expected)
    if operator == "all_selected":
        if not isinstance(value, Sequence) or isinstance(value, str):
            return False
        if not isinstance(expected, Sequence) or isinstance(expected, str):
            return False
        return all(item in value for item in expected)
    if operator == "is_true":
        return bool(value) is True

    st.warning(f"Unsupported operator: {operator}")
    return False


def should_show_question(question: Dict[str, Any], answers: Dict[str, Any]) -> bool:
    """Determine whether a question should be displayed."""

    show_if = question.get("show_if")
    if not show_if:
        return True
    return evaluate_condition(show_if, answers)


def render_question(question: Dict[str, Any], answers: Dict[str, Any]) -> None:
    """Render an individual question widget."""

    question_key = question["key"]
    widget_key = f"question_{question_key}"

    if not should_show_question(question, answers):
        answers.pop(question_key, None)
        if widget_key in st.session_state:
            st.session_state.pop(widget_key)
        return

    question_type = question.get("type")
    label = question.get("label", question_key)
    help_text = question.get("help")
    default_value = answers.get(question_key, question.get("default"))

    if question_type == "single":
        options: List[str] = question.get("options", [])
        if not options:
            st.warning(f"Question '{question_key}' has no options configured.")
            return
        if default_value not in options:
            default_value = options[0]
        index = options.index(default_value)
        selection = st.selectbox(
            label,
            options=options,
            index=index,
            placeholder=question.get("placeholder"),
            key=widget_key,
            help=help_text,
        )
        answers[question_key] = selection
    elif question_type == "multiselect":
        options = question.get("options", [])
        if not isinstance(default_value, list):
            default_value = question.get("default", [])
        selections = st.multiselect(
            label,
            options=options,
            default=default_value,
            key=widget_key,
            help=help_text,
        )
        answers[question_key] = selections
    elif question_type == "bool":
        default_bool = bool(default_value) if default_value is not None else False
        selection = st.toggle(
            label,
            value=st.session_state.get(widget_key, default_bool),
            key=widget_key,
            help=help_text,
        )
        answers[question_key] = selection
    elif question_type == "text":
        default_text = "" if default_value is None else str(default_value)
        text_value = st.text_input(
            label,
            value=st.session_state.get(widget_key, default_text),
            key=widget_key,
            placeholder=question.get("placeholder"),
            help=help_text,
        )
        answers[question_key] = text_value
    else:
        st.warning(f"Unsupported question type: {question_type}")


def main() -> None:
    """Render the questionnaire page."""

    st.title("Questionnaire")

    schema: Dict[str, Any] = {}
    github_error: Optional[str] = None
    try:
        schema = load_schema_from_github()
    except requests.RequestException:
        github_error = (
            "Unable to load the questionnaire schema from GitHub right now. "
            "Showing the local form definition instead."
        )
    except json.JSONDecodeError:
        github_error = (
            "The schema file on GitHub is not valid JSON. Using the local copy "
            "of form_schema.json instead."
        )
    except Exception:
        github_error = (
            "Something went wrong while reading the schema from GitHub. "
            "Falling back to the local form definition."
        )

    if github_error:
        st.error(github_error)

    if not schema:
        schema = load_schema()
    if not schema:
        st.error("Schema failed to load. Please check form_schema.json.")
        return

    questions = schema.get("questions", [])
    if not questions:
        st.info("No questions defined in the schema yet.")
        return

    answers: Dict[str, Any] = st.session_state.setdefault(ANSWERS_STATE_KEY, {})

    st.write(
        "Answer the following questions. Show/hide rules apply immediately "
        "based on your responses."
    )

    for question in questions:
        render_question(question, answers)

    st.session_state[ANSWERS_STATE_KEY] = answers

    if st.button("Submit questionnaire"):
        st.success("Responses captured. Persistence will be wired via GitHub.")
        st.json(answers)


if __name__ == "__main__":
    main()
