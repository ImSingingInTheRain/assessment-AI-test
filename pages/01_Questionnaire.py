"""Streamlit page to render the questionnaire from a JSON schema."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape as html_escape
from typing import Any, Dict, List, Optional, Sequence
import uuid

import requests
import streamlit as st

from Home import load_schema
from lib.form_store import (
    available_form_keys,
    combine_forms,
    forms_from_payloads,
    resolve_remote_form_path,
)
from lib.github_backend import GitHubBackend
import lib.questionnaire_utils as questionnaire_utils

DEFAULT_QUESTIONNAIRE_KEY = questionnaire_utils.DEFAULT_QUESTIONNAIRE_KEY
RUNNER_SELECTED_STATE_KEY = questionnaire_utils.RUNNER_SELECTED_STATE_KEY
normalize_questionnaires = questionnaire_utils.normalize_questionnaires

# ``RECORD_NAME_FIELD`` and related constants were added in tandem with this page,
# but older deployments may still import a version of ``questionnaire_utils``
# that predates them. ``getattr`` keeps the page working with those builds
# instead of failing with an ``ImportError`` when the constants are missing.
RECORD_NAME_FIELD = getattr(questionnaire_utils, "RECORD_NAME_FIELD", "_record_name")
RECORD_NAME_KEY = getattr(questionnaire_utils, "RECORD_NAME_KEY", "record_name")
RECORD_NAME_TYPE = getattr(questionnaire_utils, "RECORD_NAME_TYPE", "record_name")


def _fallback_extract_record_name(
    questionnaire: Dict[str, Any], answers: Dict[str, Any]
) -> str:
    """Best-effort extraction of a record name when helpers are unavailable."""

    questions = questionnaire.get("questions", [])
    if isinstance(questions, list):
        for question in questions:
            if not isinstance(question, dict):
                continue
            if question.get("type") != RECORD_NAME_TYPE:
                continue
            key = question.get("key")
            if not isinstance(key, str):
                continue
            value = answers.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

    value = answers.get(RECORD_NAME_FIELD)
    if isinstance(value, str) and value.strip():
        return value.strip()

    return ""


extract_record_name = getattr(
    questionnaire_utils,
    "extract_record_name",
    _fallback_extract_record_name,
)
from lib.related_records import (
    RELATED_RECORD_SOURCES,
    load_related_record_options,
    related_record_source_label,
)
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
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _github_settings() -> Dict[str, Any]:
    """Return GitHub configuration from secrets in a normalised structure."""

    secrets = _secrets_dict("github")
    repo = secrets.get("repo")
    path = secrets.get("path", "form_schemas/{form_key}/form_schema.json")
    branch = secrets.get("branch", "main")
    token = secrets.get("token")
    api_url = secrets.get("api_url")
    forms_config = secrets.get("forms", [])
    submissions_path = secrets.get("system_registration_submissions_path")
    assessment_submissions_path = secrets.get("assessment_submissions_path")

    configured_forms: List[str] = []
    if isinstance(forms_config, Sequence) and not isinstance(forms_config, (str, bytes)):
        configured_forms = [str(item).strip() for item in forms_config if str(item).strip()]

    if not (repo and path):
        repo = st.secrets.get("github_repo", repo)
        path = st.secrets.get("github_file_path", path)
        branch = st.secrets.get("github_branch", branch)
        token = st.secrets.get("github_token", token)
        api_url = st.secrets.get("github_api_url", api_url)
    if not configured_forms:
        secrets_forms = st.secrets.get("github_forms")
        if isinstance(secrets_forms, Sequence) and not isinstance(secrets_forms, (str, bytes)):
            configured_forms = [str(item).strip() for item in secrets_forms if str(item).strip()]
    if not submissions_path:
        submissions_path = st.secrets.get(
            "github_system_registration_submissions_path",
            st.secrets.get("system_registration_submissions_path", submissions_path),
        )
    if not assessment_submissions_path:
        assessment_submissions_path = st.secrets.get(
            "github_assessment_submissions_path",
            st.secrets.get("assessment_submissions_path", assessment_submissions_path),
        )

    if repo and path:
        return {
            "repo": repo,
            "path": path,
            "branch": branch,
            "token": token,
            "forms": configured_forms,
            "api_url": api_url,
            "system_registration_submissions_path": submissions_path,
            "assessment_submissions_path": assessment_submissions_path,
        }
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
    configured_forms = github_settings.get("forms") or []

    if not repo or not path:
        return {}

    form_keys = configured_forms or available_form_keys()
    if not form_keys:
        return {}

    payloads: Dict[str, Dict[str, Any]] = {}
    for form_key in form_keys:
        config = GHConfig(
            repo=repo,
            path=resolve_remote_form_path(path, form_key),
            ref=ref,
            token=token,
        )
        contents = get_file(config)
        payloads[form_key] = json.loads(contents)

    return combine_forms(forms_from_payloads(payloads))

ANSWERS_STATE_KEY = "questionnaire_answers"
QUESTIONNAIRE_QUERY_PARAM = "questionnaire"
SYSTEM_REGISTRATION_KEY = "system_registration"
ASSESSMENT_KEY = "assessment"
DEFAULT_SYSTEM_REGISTRATION_SUBMISSIONS_PATH = (
    "system_registration/submissions/{submission_id}.json"
)
DEFAULT_ASSESSMENT_SUBMISSIONS_PATH = "assessment/submissions/{submission_id}.json"


def _submission_storage_path(
    *,
    settings: Dict[str, Any],
    submission_id: str,
    template_key: str,
    default_template: str,
    error_subject: str,
) -> Optional[str]:
    """Format a storage path for a questionnaire submission."""

    template = settings.get(template_key) or default_template
    try:
        return template.format(submission_id=submission_id)
    except KeyError as exc:
        st.error(
            f"Invalid {error_subject} submissions path template; "
            f"missing placeholder: {exc}."
        )
        return None


def _system_registration_submission_path(settings: Dict[str, Any], submission_id: str) -> Optional[str]:
    """Build the storage path for a system registration submission."""

    return _submission_storage_path(
        settings=settings,
        submission_id=submission_id,
        template_key="system_registration_submissions_path",
        default_template=DEFAULT_SYSTEM_REGISTRATION_SUBMISSIONS_PATH,
        error_subject="system registration",
    )


def _assessment_submission_path(settings: Dict[str, Any], submission_id: str) -> Optional[str]:
    """Build the storage path for an assessment submission."""

    return _submission_storage_path(
        settings=settings,
        submission_id=submission_id,
        template_key="assessment_submissions_path",
        default_template=DEFAULT_ASSESSMENT_SUBMISSIONS_PATH,
        error_subject="assessment",
    )


def store_system_registration_submission(
    answers: Dict[str, Any],
    *,
    record_name: Optional[str] = None,
) -> Optional[str]:
    """Persist a system registration submission to GitHub and return its ID."""

    settings = _github_settings()
    token = settings.get("token")
    repo = settings.get("repo")
    branch = settings.get("branch", "main")
    api_url = settings.get("api_url") or "https://api.github.com"

    if not token or not repo:
        st.error("GitHub configuration is required to store system registrations.")
        return None

    submission_id = uuid.uuid4().hex
    storage_path = _system_registration_submission_path(settings, submission_id)
    if not storage_path:
        return None

    try:
        serialisable_answers = json.loads(json.dumps(answers))
    except TypeError as exc:
        st.error(f"System registration answers are not serialisable: {exc}.")
        return None

    if isinstance(serialisable_answers, dict):
        extracted_name = serialisable_answers.pop(RECORD_NAME_FIELD, None)
    else:
        extracted_name = None

    record_name_value = record_name or extracted_name
    if isinstance(record_name_value, str):
        record_name_value = record_name_value.strip()
    else:
        record_name_value = ""

    payload = {
        "id": submission_id,
        "questionnaire_key": SYSTEM_REGISTRATION_KEY,
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "answers": serialisable_answers,
    }

    if record_name_value:
        payload[RECORD_NAME_KEY] = record_name_value

    backend = GitHubBackend(
        token=token,
        repo=repo,
        path=storage_path,
        branch=branch,
        api_url=api_url,
    )

    try:
        backend.write_json(
            payload,
            message=f"Add system registration submission {submission_id}",
        )
    except Exception as exc:  # pylint: disable=broad-except
        st.error(f"Failed to store system registration submission: {exc}")
        return None

    return submission_id


def store_assessment_submission(
    answers: Dict[str, Any],
    *,
    record_name: Optional[str] = None,
) -> Optional[str]:
    """Persist an assessment submission to GitHub and return its ID."""

    settings = _github_settings()
    token = settings.get("token")
    repo = settings.get("repo")
    branch = settings.get("branch", "main")
    api_url = settings.get("api_url") or "https://api.github.com"

    if not token or not repo:
        st.error("GitHub configuration is required to store assessments.")
        return None

    submission_id = uuid.uuid4().hex
    storage_path = _assessment_submission_path(settings, submission_id)
    if not storage_path:
        return None

    try:
        serialisable_answers = json.loads(json.dumps(answers))
    except TypeError as exc:
        st.error(f"Assessment answers are not serialisable: {exc}.")
        return None

    if isinstance(serialisable_answers, dict):
        extracted_name = serialisable_answers.pop(RECORD_NAME_FIELD, None)
    else:
        extracted_name = None

    record_name_value = record_name or extracted_name
    if isinstance(record_name_value, str):
        record_name_value = record_name_value.strip()
    else:
        record_name_value = ""

    payload = {
        "id": submission_id,
        "questionnaire_key": ASSESSMENT_KEY,
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "answers": serialisable_answers,
    }

    if record_name_value:
        payload[RECORD_NAME_KEY] = record_name_value

    backend = GitHubBackend(
        token=token,
        repo=repo,
        path=storage_path,
        branch=branch,
        api_url=api_url,
    )

    try:
        backend.write_json(
            payload,
            message=f"Add assessment submission {submission_id}",
        )
    except Exception as exc:  # pylint: disable=broad-except
        st.error(f"Failed to store assessment submission: {exc}")
        return None

    return submission_id


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


def _get_query_param(name: str) -> Optional[str]:
    """Return the first query parameter value if present."""

    params = st.query_params
    values = params.get(name)
    if not values:
        return None
    if isinstance(values, list):
        return next((str(value) for value in values if value is not None), None)
    return str(values)


def _set_query_param(name: str, value: str) -> None:
    """Persist ``value`` in the query string under ``name``."""

    params = st.query_params
    params[name] = value


def render_question(
    questionnaire_key: str,
    question: Dict[str, Any],
    answers: Dict[str, Any],
    *,
    index: int,
    total: int,
) -> None:
    """Render an individual question widget."""

    question_key = question["key"]
    widget_key = f"{questionnaire_key}_question_{question_key}"

    if not should_show_question(question, answers):
        answers.pop(question_key, None)
        if widget_key in st.session_state:
            st.session_state.pop(widget_key)
        return

    question_type = question.get("type")
    label = question.get("label", question_key)
    help_text = question.get("help")
    default_value = answers.get(question_key, question.get("default"))

    if question_type == "statement":
        question_intro = "Statement"
    else:
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
    elif question_type in {"text", RECORD_NAME_TYPE}:
        default_text = "" if default_value is None else str(default_value)
        text_value = st.text_input(
            label,
            value=default_text,
            key=widget_key,
            placeholder=question.get("placeholder"),
            label_visibility="collapsed",
        )
        answers[question_key] = text_value
        if question_type == RECORD_NAME_TYPE:
            stripped = text_value.strip()
            if stripped:
                answers[RECORD_NAME_FIELD] = stripped
            else:
                answers.pop(RECORD_NAME_FIELD, None)
    elif question_type == "related_record":
        source_key = question.get("related_record_source")
        if not isinstance(source_key, str) or source_key not in RELATED_RECORD_SOURCES:
            answers.pop(question_key, None)
            if widget_key in st.session_state:
                st.session_state.pop(widget_key)
            st.warning(
                "Related record questions require a valid source. Contact the questionnaire maintainer."
            )
            st.markdown("</div>", unsafe_allow_html=True)
            return

        options = load_related_record_options(source_key)
        if not options:
            answers.pop(question_key, None)
            if widget_key in st.session_state:
                st.session_state.pop(widget_key)
            st.info(
                f"No records available for {related_record_source_label(source_key)} yet."
            )
            st.markdown("</div>", unsafe_allow_html=True)
            return

        option_values = [value for value, _ in options]
        labels = {value: label for value, label in options}
        default_option = default_value if isinstance(default_value, str) else None
        if default_option not in option_values:
            default_option = option_values[0]
        index = option_values.index(default_option)
        selection = st.selectbox(
            label,
            options=option_values,
            index=index,
            key=widget_key,
            label_visibility="collapsed",
            format_func=lambda value: labels.get(value, value),
        )
        answers[question_key] = selection
        st.caption(f"Selected record ID: `{selection}`")
    elif question_type == "statement":
        answers.pop(question_key, None)
        if widget_key in st.session_state:
            st.session_state.pop(widget_key)
        st.caption("No response required.")
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
            "The schema file on GitHub is not valid JSON. Using the local form definitions "
            "in form_schemas/<form_key>/form_schema.json instead."
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
        st.error("Schema failed to load. Please check form_schemas/<name>/form_schema.json.")
        return

    questionnaires = normalize_questionnaires(schema)
    if not questionnaires:
        st.error("No questionnaires configured. Use the editor to add one.")
        return

    initial_selection = _get_query_param(QUESTIONNAIRE_QUERY_PARAM)
    if not initial_selection:
        initial_selection = st.session_state.get(RUNNER_SELECTED_STATE_KEY)
    if not initial_selection or initial_selection not in questionnaires:
        initial_selection = next(iter(questionnaires))

    questionnaire_keys = list(questionnaires.keys())
    selected_key = initial_selection
    if len(questionnaire_keys) > 1:
        selected_index = questionnaire_keys.index(selected_key)
        selected_key = st.selectbox(
            "Questionnaire",
            options=questionnaire_keys,
            index=selected_index,
            format_func=lambda key: questionnaires[key].get("label", key),
            help="Choose which questionnaire to complete.",
        )

    st.session_state[RUNNER_SELECTED_STATE_KEY] = selected_key
    if _get_query_param(QUESTIONNAIRE_QUERY_PARAM) != selected_key:
        _set_query_param(QUESTIONNAIRE_QUERY_PARAM, selected_key)

    selected_questionnaire = questionnaires[selected_key]
    page_settings = selected_questionnaire.get("page", {})
    page_title = str(page_settings.get("title") or "")
    if not page_title:
        page_title = selected_questionnaire.get("label", DEFAULT_PAGE_TITLE)
    st.title(page_title or DEFAULT_PAGE_TITLE)

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

    questions = selected_questionnaire.get("questions", [])
    if not questions:
        st.info("No questions defined in the schema yet.")
        return

    answers_state: Dict[str, Dict[str, Any]] = st.session_state.setdefault(ANSWERS_STATE_KEY, {})
    answers = answers_state.setdefault(selected_key, {})

    for idx, question in enumerate(questions):
        render_question(
            selected_key,
            question,
            answers,
            index=idx,
            total=len(questions),
        )

    answers_state[selected_key] = answers
    st.session_state[ANSWERS_STATE_KEY] = answers_state

    record_name = extract_record_name(selected_questionnaire, answers)

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
            st.json(answers)

    if st.button(submit_label, key=f"submit_{selected_key}"):
        st.success(submit_success_message)

        if selected_key == SYSTEM_REGISTRATION_KEY:
            submission_id = store_system_registration_submission(
                answers,
                record_name=record_name,
            )
            if submission_id:
                st.info(f"Submission saved with ID `{submission_id}`.")
        elif selected_key == ASSESSMENT_KEY:
            submission_id = store_assessment_submission(
                answers,
                record_name=record_name,
            )
            if submission_id:
                st.info(f"Assessment saved with ID `{submission_id}`.")

        if show_answers_summary:
            st.json(answers)


if __name__ == "__main__":
    main()
