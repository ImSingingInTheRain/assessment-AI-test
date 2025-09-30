"""Streamlit page to render the questionnaire from a JSON schema."""

from __future__ import annotations

import json
from dataclasses import dataclass
from html import escape as html_escape
from typing import Any, Dict, List, Optional, Sequence

import requests
import streamlit as st

from Home import load_schema
from lib.schema_defaults import (
    DEFAULT_DEBUG_LABEL,
    DEFAULT_INTRO_HEADING,
    DEFAULT_PAGE_TITLE,
    DEFAULT_SHOW_ANSWERS_SUMMARY,
    DEFAULT_SHOW_DEBUG,
    DEFAULT_SHOW_INTRODUCTION,
    DEFAULT_SUBMIT_LABEL,
    DEFAULT_SUBMIT_SUCCESS_MESSAGE,
    intro_paragraphs_list,
)


@dataclass(frozen=True)
class GHConfig:
    """Configuration required to fetch a file from GitHub."""

    repo: str
    path: str
    ref: str = "main"
    token: Optional[str] = None


def _secrets_dict(name: str) -> Dict[str, Any]:
    """Return a mapping stored under ``name`` in Streamlit secrets."""

    value = st.secrets.get(name, {})  # type: ignore[arg-type]
    if isinstance(value, dict):
        return dict(value)
    return {}


def _github_settings() -> Dict[str, Any]:
    """Return GitHub configuration from secrets in a normalised structure."""

    secrets = _secrets_dict("github")
    repo = secrets.get("repo")
    path = secrets.get("path", "form_schema.json")
    branch = secrets.get("branch", "main")
    token = secrets.get("token")

    if not (repo and path):
        repo = st.secrets.get("github_repo", repo)
        path = st.secrets.get("github_file_path", path)
        branch = st.secrets.get("github_branch", branch)
        token = st.secrets.get("github_token", token)

    if repo and path:
        return {"repo": repo, "path": path, "branch": branch, "token": token}
    return {}


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

    github_settings = _github_settings()
    repo = github_settings.get("repo")
    path = github_settings.get("path")
    ref = github_settings.get("branch", "main")
    token = github_settings.get("token")

    if not repo or not path:
        return {}

    config = GHConfig(repo=repo, path=path, ref=ref, token=token)
    contents = get_file(config)
    return json.loads(contents)

ANSWERS_STATE_KEY = "answers"


def _normalise_paragraphs(value: Any) -> List[str]:
    """Convert a stored paragraphs value into a clean list of strings."""

    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    return []


def eval_clause(clause: Dict[str, Any], answers: Dict[str, Any]) -> bool:
    """Evaluate a single rule clause against the current answers."""

    operator = clause.get("operator", "equals")
    field = clause.get("field")
    expected = clause.get("value")

    if field is None and operator != "always":
        st.warning("Rule clause missing 'field'.")
        return False

    value = answers.get(field)

    if operator == "always":
        return True
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
    if operator == "contains_any":
        if expected is None:
            return False
        if isinstance(expected, Sequence) and not isinstance(expected, str):
            expected_values = list(expected)
        else:
            expected_values = [expected]

        if isinstance(value, str):
            return any(isinstance(item, str) and item in value for item in expected_values)
        if isinstance(value, Sequence) and not isinstance(value, str):
            return any(item in value for item in expected_values)
        return False
    if operator == "all_selected":
        if not isinstance(value, Sequence) or isinstance(value, str):
            return False
        if not isinstance(expected, Sequence) or isinstance(expected, str):
            return False
        return all(item in value for item in expected)
    if operator == "is_true":
        return bool(value) is True
    if operator == "is_false":
        return bool(value) is False

    st.warning(f"Unsupported operator: {operator}")
    return False


def eval_rule(rule: Dict[str, Any], answers: Dict[str, Any]) -> bool:
    """Evaluate a rule made of clauses and logical operators."""

    if not rule:
        return True
    if "all" in rule:
        return all(eval_rule(subrule, answers) for subrule in rule.get("all", []))
    if "any" in rule:
        return any(eval_rule(subrule, answers) for subrule in rule.get("any", []))
    return eval_clause(rule, answers)


def should_show_question(question: Dict[str, Any], answers: Dict[str, Any]) -> bool:
    """Determine whether a question should be displayed."""

    show_if = question.get("show_if")
    if not show_if:
        return True
    return eval_rule(show_if, answers)


def render_question(
    question: Dict[str, Any], answers: Dict[str, Any], *, index: int, total: int
) -> None:
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

    question_intro = f"Question {index + 1} of {total}"

    st.markdown(
        "<div class='question-card'>",
        unsafe_allow_html=True,
    )
    st.markdown(
        f"""
        <div class="question-header">
            <span class="question-step">{question_intro}</span>
            <h3>{label}</h3>
        </div>
        {f'<p class="question-help">{help_text}</p>' if help_text else ''}
        """,
        unsafe_allow_html=True,
    )

    if question_type == "single":
        options: List[str] = question.get("options", [])
        if not options:
            st.warning(f"Question '{question_key}' has no options configured.")
            st.markdown("</div>", unsafe_allow_html=True)
            return
        if default_value not in options:
            default_value = options[0]
        index = options.index(default_value) if default_value in options else 0
        selection = st.radio(
            label,
            options,
            index=index,
            key=widget_key,
            label_visibility="collapsed",
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
            label_visibility="collapsed",
        )
        answers[question_key] = selections
    elif question_type == "bool":
        default_bool = bool(default_value) if default_value is not None else False
        selection = st.checkbox(
            label,
            value=default_bool,
            key=widget_key,
            label_visibility="hidden",
        )
        answers[question_key] = selection
    elif question_type == "text":
        default_text = "" if default_value is None else str(default_value)
        text_value = st.text_input(
            label,
            value=default_text,
            key=widget_key,
            placeholder=question.get("placeholder"),
            label_visibility="collapsed",
        )
        answers[question_key] = text_value
    else:
        st.warning(f"Unsupported question type: {question_type}")

    st.markdown("</div>", unsafe_allow_html=True)


def main() -> None:
    """Render the questionnaire page."""

    st.markdown(
        """
        <style>
        .questionnaire-intro {
            background: linear-gradient(135deg, rgba(64, 115, 255, 0.12), rgba(129, 212, 250, 0.12));
            padding: 1.5rem;
            border-radius: 1rem;
            border: 1px solid rgba(64, 115, 255, 0.25);
            margin-bottom: 1.5rem;
        }
        .questionnaire-intro h2 {
            margin: 0 0 0.75rem 0;
        }
        .questionnaire-intro p {
            margin-bottom: 0.75rem;
        }
        .question-card {
            padding: 1.25rem 1.5rem 1.5rem 1.5rem;
            border-radius: 1rem;
            background: rgba(255, 255, 255, 0.85);
            border: 1px solid rgba(49, 51, 63, 0.12);
            box-shadow: 0 8px 24px rgba(15, 23, 42, 0.05);
            margin-bottom: 1.25rem;
        }
        .question-header {
            display: flex;
            flex-direction: column;
            gap: 0.25rem;
            margin-bottom: 0.75rem;
        }
        .question-header h3 {
            margin: 0;
            font-size: 1.1rem;
        }
        .question-step {
            font-size: 0.85rem;
            font-weight: 600;
            color: #4361ee;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }
        .question-help {
            color: #5f6368;
            font-size: 0.92rem;
            margin-bottom: 0.75rem;
        }
        button[kind="primary"], .stButton>button {
            border-radius: 999px;
            padding: 0.6rem 1.5rem;
            font-weight: 600;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

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

    page_settings = schema.get("page") if isinstance(schema.get("page"), dict) else {}
    st.title(str(page_settings.get("title")) or DEFAULT_PAGE_TITLE)

    show_introduction = page_settings.get("show_introduction")
    if show_introduction is None:
        show_introduction = DEFAULT_SHOW_INTRODUCTION

    introduction_settings = (
        page_settings.get("introduction")
        if isinstance(page_settings.get("introduction"), dict)
        else {}
    )
    heading = (
        str(introduction_settings.get("heading") or "")
        if "heading" in introduction_settings
        else DEFAULT_INTRO_HEADING
    )
    if "paragraphs" in introduction_settings:
        paragraphs = _normalise_paragraphs(introduction_settings.get("paragraphs"))
    else:
        paragraphs = intro_paragraphs_list()

    if show_introduction and (heading or paragraphs):
        intro_parts = ["<div class=\"questionnaire-intro\">"]
        if heading:
            intro_parts.append(f"<h2>{html_escape(heading)}</h2>")
        for paragraph in paragraphs:
            intro_parts.append(f"<p>{html_escape(paragraph)}</p>")
        intro_parts.append("</div>")
        st.markdown("\n".join(intro_parts), unsafe_allow_html=True)

    questions = schema.get("questions", [])
    if not questions:
        st.info("No questions defined in the schema yet.")
        return

    answers: Dict[str, Any] = st.session_state.setdefault(ANSWERS_STATE_KEY, {})

    for idx, question in enumerate(questions):
        render_question(question, answers, index=idx, total=len(questions))

    st.session_state[ANSWERS_STATE_KEY] = answers

    submit_settings = (
        page_settings.get("submit")
        if isinstance(page_settings.get("submit"), dict)
        else {}
    )
    submit_label = (
        str(submit_settings.get("label") or DEFAULT_SUBMIT_LABEL)
        if "label" in submit_settings
        else DEFAULT_SUBMIT_LABEL
    )
    submit_success_message = (
        str(submit_settings.get("success_message") or DEFAULT_SUBMIT_SUCCESS_MESSAGE)
        if "success_message" in submit_settings
        else DEFAULT_SUBMIT_SUCCESS_MESSAGE
    )
    show_answers_summary = submit_settings.get("show_answers_summary")
    if show_answers_summary is None:
        show_answers_summary = DEFAULT_SHOW_ANSWERS_SUMMARY
    else:
        show_answers_summary = bool(show_answers_summary)

    show_debug_answers = page_settings.get("show_debug_answers")
    if show_debug_answers is None:
        show_debug_answers = DEFAULT_SHOW_DEBUG
    else:
        show_debug_answers = bool(show_debug_answers)

    if show_debug_answers:
        debug_label = (
            str(page_settings.get("debug_expander_label") or DEFAULT_DEBUG_LABEL)
            if "debug_expander_label" in page_settings
            else DEFAULT_DEBUG_LABEL
        )
        with st.expander(debug_label, expanded=False):
            st.json(st.session_state[ANSWERS_STATE_KEY])

    if st.button(submit_label):
        st.success(submit_success_message)
        if show_answers_summary:
            st.json(answers)


if __name__ == "__main__":
    main()
