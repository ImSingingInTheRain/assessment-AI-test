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

try:  # pragma: no cover - compatibility shim for older ``Home`` modules
    import Home as _home_module
except ImportError:  # pragma: no cover - legacy fallback
    _home_module = None

if _home_module is not None:  # pragma: no branch - small helper initialisation
    load_schema = _home_module.load_schema
    RELATED_SYSTEM_FIELDS = getattr(
        _home_module, "RELATED_SYSTEM_FIELDS", ("related-system",)
    )
    RELATED_SYSTEM_FIELD = getattr(
        _home_module, "RELATED_SYSTEM_FIELD", RELATED_SYSTEM_FIELDS[0]
    )
else:  # pragma: no cover - best effort defaults when ``Home`` import fails
    def load_schema() -> Dict[str, Any]:
        return {}

    RELATED_SYSTEM_FIELDS = ("related-system",)
    RELATED_SYSTEM_FIELD = RELATED_SYSTEM_FIELDS[0]
from lib.form_store import (
    available_form_keys,
    combine_forms,
    forms_from_payloads,
    resolve_remote_form_path,
)
from lib.github_backend import GitHubBackend
import lib.questionnaire_utils as questionnaire_utils
from lib.ui_theme import apply_app_theme, page_header

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
UNSELECTED_LABEL = "— Select an option —"


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


def _normalise_system_id(value: Any) -> str:
    """Return a cleaned identifier for a related system."""

    if isinstance(value, str):
        return value.strip()
    if value is None:
        return ""
    return str(value).strip()


def _extract_related_system_id(answers: Mapping[str, Any]) -> str:
    """Return the first populated related system identifier in ``answers``."""

    for field in RELATED_SYSTEM_FIELDS:
        value = answers.get(field)
        if value is None:
            continue
        text = _normalise_system_id(value)
        if text:
            return text
    return ""


def _collect_triggered_risks(
    answers: Dict[str, Any], *, system_id: str = ""
) -> List[Dict[str, Any]]:
    """Return risks whose logic evaluates to ``True`` for ``answers``."""

    try:
        schema = load_schema()
    except Exception:  # pragma: no cover - defensive against cache issues
        schema = {}

    if not isinstance(schema, dict):
        return []

    try:
        questionnaire = questionnaire_utils.get_questionnaire(schema, DEFAULT_QUESTIONNAIRE_KEY)
    except Exception:  # pragma: no cover - fall back gracefully
        questionnaire = {}

    risks = questionnaire.get("risks", [])
    if not isinstance(risks, list):
        return []

    triggered: List[Dict[str, Any]] = []
    for risk in risks:
        if not isinstance(risk, dict):
            continue

        logic = risk.get("logic")
        if isinstance(logic, Sequence) and not isinstance(logic, (str, bytes, dict)):
            logic = {"all": list(logic)}
        if logic is None:
            continue
        if not isinstance(logic, dict):
            continue

        try:
            is_triggered = eval_rule(logic, answers)
        except Exception:  # pragma: no cover - guard against malformed rules
            continue

        if not is_triggered:
            continue

        entry: Dict[str, Any] = {}
        key = risk.get("key")
        name = risk.get("name")
        level = risk.get("level")
        mitigations = risk.get("mitigations")

        if isinstance(key, str) and key.strip():
            entry["key"] = key.strip()
        if isinstance(name, str) and name.strip():
            entry["name"] = name.strip()
        if isinstance(level, str) and level.strip():
            entry["level"] = level.strip()
        if isinstance(mitigations, list):
            cleaned_mitigations = [
                str(item).strip()
                for item in mitigations
                if isinstance(item, str) and str(item).strip()
            ]
            if cleaned_mitigations:
                entry["mitigations"] = cleaned_mitigations
        if system_id:
            entry["system_id"] = system_id

        triggered.append(entry)

    return triggered


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

    related_system_id = ""
    triggered_risks: List[Dict[str, Any]] = []
    if isinstance(serialisable_answers, dict):
        related_system_id = _extract_related_system_id(serialisable_answers)
        triggered_risks = _collect_triggered_risks(
            serialisable_answers, system_id=related_system_id
        )
        extracted_name = serialisable_answers.pop(RECORD_NAME_FIELD, None)
        if related_system_id:
            serialisable_answers[RELATED_SYSTEM_FIELD] = related_system_id
        elif RELATED_SYSTEM_FIELD in serialisable_answers:
            serialisable_answers.pop(RELATED_SYSTEM_FIELD, None)
        for legacy_field in RELATED_SYSTEM_FIELDS[1:]:
            serialisable_answers.pop(legacy_field, None)
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
    if related_system_id:
        payload["related_system_id"] = related_system_id
    if triggered_risks:
        payload["risks"] = triggered_risks

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


def _is_required_question(question: Dict[str, Any]) -> bool:
    """Return ``True`` if the question should enforce a response."""

    return bool(question.get("required")) and question.get("type") != "statement"


def _has_required_answer(question: Dict[str, Any], answers: Dict[str, Any]) -> bool:
    """Check whether ``answers`` contains a valid response for ``question``."""

    key = question.get("key")
    if not isinstance(key, str) or not key:
        return True

    value = answers.get(key)
    question_type = question.get("type")

    if question_type == "single":
        options = [option for option in question.get("options", []) if isinstance(option, str)]
        return isinstance(value, str) and value in options

    if question_type == "multiselect":
        return isinstance(value, list) and bool(value)

    if question_type in {"text", RECORD_NAME_TYPE}:
        return isinstance(value, str) and value.strip() != ""

    if question_type == "bool":
        return key in answers

    if question_type == "related_record":
        return isinstance(value, str) and value != ""

    return True


def collect_missing_required_questions(
    questionnaire: Dict[str, Any], answers: Dict[str, Any]
) -> List[str]:
    """Return labels for required questions without answers."""

    missing: List[str] = []
    for question in questionnaire.get("questions", []) or []:
        if not isinstance(question, dict):
            continue
        if not _is_required_question(question):
            continue
        if not should_show_question(question, answers):
            continue
        if not _has_required_answer(question, answers):
            label = question.get("label")
            key = question.get("key")
            missing.append(label or key or "Unnamed question")
    return missing


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
    required = bool(question.get("required")) and question_type != "statement"

    if question_type == "statement":
        question_intro = "Statement"
    else:
        question_intro = f"Question {index + 1} of {total}"

    question_block = st.container()
    question_block.markdown(
        f"""
        <section class="question-block">
            <div class="question-block__header">
                <span class="question-block__step">{question_intro}</span>
                <h3 class="question-block__title">{label}{'<sup>*</sup>' if required else ''}</h3>
            </div>
            {f'<p class="question-block__help">{help_text}</p>' if help_text else ''}
        """,
        unsafe_allow_html=True,
    )

    def _close_block() -> None:
        question_block.markdown("</section>", unsafe_allow_html=True)

    if question_type == "single":
        options: List[str] = [option for option in question.get("options", []) if isinstance(option, str)]
        if not options:
            question_block.warning(f"Question '{question_key}' has no options configured.")
            _close_block()
            return
        choices = [UNSELECTED_LABEL, *options]
        if widget_key in st.session_state and st.session_state[widget_key] not in choices:
            st.session_state.pop(widget_key)
        default_choice = answers.get(question_key)
        if not isinstance(default_choice, str) or default_choice not in options:
            default_choice = (
                default_value if isinstance(default_value, str) and default_value in options else UNSELECTED_LABEL
            )
        index = choices.index(default_choice)
        selection = question_block.radio(
            label,
            choices,
            index=index,
            key=widget_key,
            label_visibility="collapsed",
        )
        if selection == UNSELECTED_LABEL:
            answers.pop(question_key, None)
        else:
            answers[question_key] = selection
    elif question_type == "multiselect":
        options = [option for option in question.get("options", []) if isinstance(option, str)]
        if not options:
            question_block.warning(f"Question '{question_key}' has no options configured.")
            _close_block()
            return
        if isinstance(default_value, list):
            default_selection = [value for value in default_value if value in options]
        elif isinstance(question.get("default"), list):
            default_selection = [value for value in question.get("default", []) if value in options]
        else:
            default_selection = []
        selections = question_block.multiselect(
            label,
            options=options,
            default=default_selection,
            key=widget_key,
            label_visibility="collapsed",
        )
        answers[question_key] = selections
    elif question_type == "bool":
        default_bool = bool(default_value) if default_value is not None else False
        selection = question_block.checkbox(
            label,
            value=default_bool,
            key=widget_key,
            label_visibility="hidden",
        )
        answers[question_key] = selection
    elif question_type in {"text", RECORD_NAME_TYPE}:
        default_text = "" if default_value is None else str(default_value)
        text_value = question_block.text_input(
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
            question_block.warning(
                "Related record questions require a valid source. Contact the questionnaire maintainer."
            )
            _close_block()
            return

        options = load_related_record_options(source_key)
        if not options:
            answers.pop(question_key, None)
            if widget_key in st.session_state:
                st.session_state.pop(widget_key)
            question_block.info(
                f"No records available for {related_record_source_label(source_key)} yet."
            )
            _close_block()
            return

        option_values = [value for value, _ in options]
        labels = {value: label for value, label in options}
        default_option = default_value if isinstance(default_value, str) else None
        if widget_key in st.session_state and st.session_state[widget_key] not in option_values + [UNSELECTED_LABEL]:
            st.session_state.pop(widget_key)
        choices = [UNSELECTED_LABEL, *option_values]
        current_selection = answers.get(question_key)
        if isinstance(current_selection, str) and current_selection in option_values:
            default_option = current_selection
        elif isinstance(default_option, str) and default_option in option_values:
            default_option = default_option
        else:
            default_option = UNSELECTED_LABEL
        index = choices.index(default_option)
        selection = question_block.selectbox(
            label,
            options=choices,
            index=index,
            key=widget_key,
            label_visibility="collapsed",
            format_func=lambda value: labels.get(value, value)
            if value != UNSELECTED_LABEL
            else UNSELECTED_LABEL,
        )
        if selection == UNSELECTED_LABEL:
            answers.pop(question_key, None)
        else:
            answers[question_key] = selection
            question_block.caption(f"Selected record ID: `{selection}`")
    elif question_type == "statement":
        answers.pop(question_key, None)
        if widget_key in st.session_state:
            st.session_state.pop(widget_key)
        question_block.caption("No response required.")
    else:
        question_block.warning(f"Unsupported question type: {question_type}")

    _close_block()


def main() -> None:
    """Render the questionnaire page."""

    apply_app_theme(page_title="Questionnaire runner", page_icon="🗒️")
    header_placeholder = st.empty()

    def update_header(title: str, subtitle: str) -> None:
        page_header(title, subtitle, icon="🗒️", container=header_placeholder)

    update_header(
        "Questionnaire runner",
        "Load a questionnaire configuration to start collecting responses.",
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
        update_header(
            "Questionnaire runner",
            "Schema failed to load. Add a form definition to continue.",
        )
        st.error("Schema failed to load. Please check form_schemas/<name>/form_schema.json.")
        return

    questionnaires = normalize_questionnaires(schema)
    if not questionnaires:
        update_header(
            "Questionnaire runner",
            "No questionnaires configured. Use the editor to create one.",
        )
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
    questions = selected_questionnaire.get("questions", [])
    question_count = len(questions) if isinstance(questions, list) else 0
    subtitle = (
        f"{question_count} question{'s' if question_count != 1 else ''} in this flow."
        if question_count
        else "No questions configured yet."
    )
    update_header(page_title or DEFAULT_PAGE_TITLE, subtitle)

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
        missing_required = collect_missing_required_questions(selected_questionnaire, answers)
        if missing_required:
            st.error("Please answer all required questions before submitting.")
            st.markdown("\n".join(f"- {label}" for label in missing_required))
            return

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
