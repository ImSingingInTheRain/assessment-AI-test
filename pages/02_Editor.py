"""Authenticated editor page for managing questionnaire questions."""

from __future__ import annotations

import hashlib
import hmac
import json
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from collections.abc import Mapping
from typing import Any, Dict, List, Optional, Sequence, Tuple

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from Home import load_schema
from lib.github_backend import GitHubBackend, create_branch, ensure_pr, put_file
from lib.form_store import load_combined_schema, local_form_path, resolve_remote_form_path
import lib.questionnaire_utils as questionnaire_utils

EDITOR_SELECTED_STATE_KEY = questionnaire_utils.EDITOR_SELECTED_STATE_KEY
normalize_questionnaires = questionnaire_utils.normalize_questionnaires

# ``RECORD_NAME_FIELD`` and ``RECORD_NAME_TYPE`` are new additions. Older
# ``questionnaire_utils`` modules won't define them which used to crash the page
# during import. ``getattr`` keeps the editor working with those deployments.
RECORD_NAME_FIELD = getattr(questionnaire_utils, "RECORD_NAME_FIELD", "_record_name")
RECORD_NAME_TYPE = getattr(questionnaire_utils, "RECORD_NAME_TYPE", "record_name")
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

SCHEMA_STATE_KEY = "editor_schema"
SCHEMA_SHA_STATE_KEY = "editor_schema_sha"
DRAFT_BRANCH_STATE_KEY = "editor_draft_branch"
FORM_SOURCES_STATE_KEY = "editor_form_sources"
FORM_RAW_STATE_KEY = "editor_form_raw"
QUESTION_TYPES = [
    "single",
    "multiselect",
    "bool",
    "text",
    RECORD_NAME_TYPE,
    "statement",
    "related_record",
]
QUESTION_TYPE_LABELS = {
    "single": "Single select",
    "multiselect": "Multi select",
    "bool": "Yes/No",
    "text": "Free text",
    RECORD_NAME_TYPE: "Name of the record",
    "statement": "Statement",
    "related_record": "Related record",
}
SHOW_IF_BUILDER_STATE_KEY = "editor_show_if_builder"


def _active_questionnaire_id(schema: Dict[str, Any]) -> str:
    """Return the identifier of the questionnaire currently being edited."""

    identifier = schema.get("_active_questionnaire")
    if isinstance(identifier, str):
        return identifier
    return ""


def _state_prefix(schema: Dict[str, Any]) -> str:
    """Return a stable prefix for widget keys based on the active questionnaire."""

    questionnaire_id = _active_questionnaire_id(schema)
    return "".join(ch if ch.isalnum() else "_" for ch in questionnaire_id)


def _rerun_app() -> None:
    """Trigger a Streamlit rerun using the available API."""

    if hasattr(st, "rerun"):
        st.rerun()
    elif hasattr(st, "experimental_rerun"):
        st.experimental_rerun()



def _is_clause_rule(value: Any) -> bool:
    """Return ``True`` if ``value`` represents a terminal rule clause."""

    return isinstance(value, dict) and "operator" in value and "all" not in value and "any" not in value


def _normalize_groups(groups: List[Dict[str, Any]]) -> None:
    """Ensure rule group metadata is internally consistent."""

    for group in groups:
        if group.get("mode") not in {"all", "any"}:
            group["mode"] = "all"
        if not isinstance(group.get("clauses"), list):
            group["clauses"] = []
        if "connector" in group:
            group.pop("connector", None)


def _generate_group_label(
    groups: Sequence[Dict[str, Any]], base_label: str = "New rule group"
) -> str:
    """Return a unique, human-friendly label for a new rule group."""

    used_labels = {
        str(group.get("label", "")).strip()
        for group in groups
        if str(group.get("label", "")).strip()
    }

    candidate = base_label
    if candidate not in used_labels:
        return candidate

    suffix = 2
    while True:
        candidate = f"{base_label} ({suffix})"
        if candidate not in used_labels:
            return candidate
        suffix += 1


def _ensure_group_labels(groups: List[Dict[str, Any]]) -> None:
    """Ensure each rule group exposes a readable, unique label for the UI."""

    used_labels: Dict[str, int] = {}
    for index, group in enumerate(groups, start=1):
        raw_label = str(group.get("label", "")).strip()
        base_label = raw_label or f"Group {index}"
        label = base_label
        duplicate_index = used_labels.get(base_label, 0)
        while label in used_labels:
            duplicate_index += 1
            label = f"{base_label} ({duplicate_index})"
        used_labels[base_label] = duplicate_index
        used_labels[label] = 0
        group["label"] = label


def _group_to_rule(group: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a builder group into a schema-compatible rule segment."""

    mode = group.get("mode", "all")
    clauses = [deepcopy(clause) for clause in group.get("clauses", []) if clause]
    if not clauses:
        return {}
    if mode not in {"all", "any"}:
        mode = "all"
    return {mode: clauses}


def _groups_to_rule(
    groups: List[Dict[str, Any]], combine_mode: str = "all"
) -> Dict[str, Any]:
    """Collapse an ordered list of rule groups into a nested rule tree."""

    normalized = [group for group in groups if group.get("clauses")]
    if not normalized:
        return {}

    _normalize_groups(normalized)

    combine_mode = combine_mode if combine_mode in {"all", "any"} else "all"

    rendered_groups = []
    for group in normalized:
        rendered = _group_to_rule(group)
        if rendered:
            rendered_groups.append(rendered)

    if not rendered_groups:
        return {}

    if len(rendered_groups) == 1:
        return rendered_groups[0]

    return {combine_mode: rendered_groups}


def _rule_to_groups(rule: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Attempt to decompose a rule tree into ordered builder groups."""

    if not rule:
        return {"groups": [], "combine_mode": "all"}

    groups: List[Dict[str, Any]] = []

    def _extract_group(node: Any) -> Optional[Dict[str, Any]]:
        if _is_clause_rule(node):
            return {"mode": "all", "clauses": [deepcopy(node)]}

        if not isinstance(node, dict):
            return None

        key: Optional[str] = None
        if "all" in node:
            key = "all"
        elif "any" in node:
            key = "any"

        if key is None:
            return None

        items = node.get(key)
        if not isinstance(items, list):
            return None

        if all(_is_clause_rule(item) for item in items):
            return {
                "mode": key,
                "clauses": [deepcopy(item) for item in items],
            }

        if len(items) == 1:
            return _extract_group(items[0])

        return None

    potential_group = _extract_group(rule)
    if potential_group is not None:
        return {"groups": [potential_group], "combine_mode": "all"}

    if not isinstance(rule, dict):
        return None

    top_key: Optional[str] = None
    if "all" in rule:
        top_key = "all"
    elif "any" in rule:
        top_key = "any"

    if top_key is None:
        return None

    items = rule.get(top_key)
    if not isinstance(items, list):
        return None

    for item in items:
        extracted = _extract_group(item)
        if extracted is None:
            return None
        groups.append(extracted)

    _normalize_groups(groups)
    return {"groups": groups, "combine_mode": top_key}

OPERATOR_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "equals": {
        "label": "Equals",
        "description": "Matches when the referenced answer exactly equals the chosen value.",
        "value_mode": "single",
    },
    "not_equals": {
        "label": "Does not equal",
        "description": "Matches when the referenced answer differs from the chosen value.",
        "value_mode": "single",
    },
    "includes": {
        "label": "Includes",
        "description": "Matches when the answer contains the chosen value.",
        "value_mode": "single",
    },
    "not_includes": {
        "label": "Does not include",
        "description": "Matches when the answer does not contain the chosen value.",
        "value_mode": "single",
    },
    "any_selected": {
        "label": "Matches any of",
        "description": "Matches when any of the selected values are chosen.",
        "value_mode": "multi",
    },
    "contains_any": {
        "label": "Contains any of",
        "description": "Matches when the answer contains any of the provided values.",
        "value_mode": "multi",
    },
    "all_selected": {
        "label": "Matches all of",
        "description": "Matches when all provided values are selected.",
        "value_mode": "multi",
    },
    "is_true": {
        "label": "Is true",
        "description": "Matches when the referenced answer is true.",
        "value_mode": "none",
    },
    "is_false": {
        "label": "Is false",
        "description": "Matches when the referenced answer is false.",
        "value_mode": "none",
    },
    "always": {
        "label": "Always",
        "description": "Always matches regardless of other answers.",
        "value_mode": "none",
    },
}

QUESTION_TYPE_OPERATORS: Dict[str, List[str]] = {
    "single": ["equals", "not_equals"],
    "multiselect": ["includes", "not_includes", "any_selected", "all_selected", "contains_any"],
    "bool": ["is_true", "is_false"],
    "text": ["equals", "not_equals", "contains_any"],
    RECORD_NAME_TYPE: ["equals", "not_equals", "contains_any"],
    "statement": ["always"],
}
DEFAULT_OPERATORS = ["equals", "not_equals", "contains_any"]
PREVIEW_ANSWERS_STATE_KEY = "editor_preview_answers"


def _secrets_dict(name: str) -> Dict[str, Any]:
    """Return a mapping stored under ``name`` in Streamlit secrets."""

    value = st.secrets.get(name, {})  # type: ignore[arg-type]
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def get_github_config() -> Optional[Dict[str, Any]]:
    """Return GitHub configuration from Streamlit secrets if available."""

    secrets = _secrets_dict("github")
    token = secrets.get("token")
    repo = secrets.get("repo")
    path = secrets.get("path", "form_schemas/{form_key}/form_schema.json")
    branch = secrets.get("branch", "main")
    api_url = secrets.get("api_url", "https://api.github.com")

    if not (token and repo and path):
        token = st.secrets.get("github_token", token)
        repo = st.secrets.get("github_repo", repo)
        path = st.secrets.get("github_file_path", path)
        branch = st.secrets.get("github_branch", branch)
        api_url = st.secrets.get("github_api_url", api_url)

    if token and repo and path:
        return {
            "token": token,
            "repo": repo,
            "path": path,
            "branch": branch,
            "api_url": api_url,
        }
    return None


def get_backend(form_key: str) -> Optional[GitHubBackend]:
    """Instantiate a GitHub backend for ``form_key`` if configuration is available."""

    config = get_github_config()
    if config is None:
        return None

    return GitHubBackend(
        token=config["token"],
        repo=config["repo"],
        path=resolve_remote_form_path(config["path"], form_key),
        branch=config.get("branch", "main"),
        api_url=config.get("api_url", "https://api.github.com"),
    )


def get_schema() -> Dict[str, Any]:
    """Fetch the current schema for editing, caching in session state."""

    if SCHEMA_STATE_KEY not in st.session_state or FORM_SOURCES_STATE_KEY not in st.session_state:
        schema, sources, raw_payloads = load_combined_schema()
        normalize_questionnaires(schema)
        st.session_state[SCHEMA_STATE_KEY] = schema
        st.session_state[FORM_SOURCES_STATE_KEY] = sources
        st.session_state[FORM_RAW_STATE_KEY] = raw_payloads
    else:
        schema = st.session_state[SCHEMA_STATE_KEY]
        normalize_questionnaires(schema)

    sha_state = st.session_state.get(SCHEMA_SHA_STATE_KEY)
    if not isinstance(sha_state, dict):
        sha_state = {}
        st.session_state[SCHEMA_SHA_STATE_KEY] = sha_state

    config = get_github_config()
    if config is not None:
        questionnaires = schema.get("questionnaires", {})
        for form_key in questionnaires.keys():
            if form_key in sha_state:
                continue
            backend = get_backend(form_key)
            if backend is None:
                sha_state[form_key] = None
                continue
            try:
                sha_state[form_key] = backend.get_file_sha()
            except Exception as exc:  # pylint: disable=broad-except
                st.error(f"Could not load schema metadata from GitHub for '{form_key}': {exc}")
                sha_state[form_key] = None
    return schema


def schema_for_storage(schema: Dict[str, Any]) -> Tuple[str, Dict[str, Any], Dict[str, Any]]:
    """Return the active form key, payload for persistence, and questionnaire data."""

    storage = deepcopy(schema)
    questionnaires = normalize_questionnaires(storage)
    if not questionnaires:
        return "", {}, {}

    active_id = storage.pop("_active_questionnaire", None)
    if not isinstance(active_id, str) or active_id not in questionnaires:
        active_id = next(iter(questionnaires))

    selected = deepcopy(questionnaires[active_id])
    if storage.get("page"):
        selected["page"] = storage.get("page", selected.get("page", {}))
    if storage.get("questions"):
        selected["questions"] = storage.get("questions", selected.get("questions", []))

    raw_payloads: Dict[str, Dict[str, Any]] = st.session_state.get(FORM_RAW_STATE_KEY, {})
    base_payload = deepcopy(raw_payloads.get(active_id, {}))

    if isinstance(base_payload.get("questionnaire"), dict):
        questionnaire_section = base_payload["questionnaire"]
    elif base_payload:
        questionnaire_section = base_payload
    else:
        base_payload = {}
        questionnaire_section = base_payload

    questionnaire_section["key"] = selected.get("key", active_id)
    questionnaire_section["label"] = selected.get("label", questionnaire_section.get("key", active_id))
    questionnaire_section["page"] = selected.get("page", {})
    questionnaire_section["questions"] = selected.get("questions", [])

    meta = selected.get("meta")
    if isinstance(meta, dict):
        base_payload["meta"] = meta
    elif "meta" in base_payload and not isinstance(base_payload.get("meta"), dict):
        base_payload.pop("meta", None)

    if questionnaire_section is not base_payload:
        base_payload["questionnaire"] = questionnaire_section
    else:
        base_payload["key"] = questionnaire_section.get("key", active_id)
        base_payload["label"] = questionnaire_section.get("label", active_id)

    questionnaire_copy = deepcopy(questionnaire_section)

    storage.pop("page", None)
    storage.pop("questions", None)
    storage.pop("questionnaires", None)

    return active_id, base_payload, questionnaire_copy


def verify_password(password: str) -> bool:
    """Validate a plaintext password against the configured hash."""

    stored_hash = st.secrets.get("editor_password_hash", "")
    if not stored_hash:
        return False

    digest = hashlib.sha256(password.encode("utf-8")).hexdigest()
    return hmac.compare_digest(digest, stored_hash)


def require_authentication() -> None:
    """Enforce a minimal password gate for the editor."""

    if st.session_state.get("auth"):
        return

    stored_hash = st.secrets.get("editor_password_hash", "")
    if not stored_hash:
        st.error("Editor password is not configured.")
        st.stop()

    password = st.text_input("Password", type="password")
    if not password:
        st.stop()

    if verify_password(password):
        st.session_state.auth = True
        return

    st.error("Incorrect password.")
    st.stop()


def parse_show_if(raw: str) -> Optional[Dict[str, Any]]:
    """Parse the JSON show_if structure provided by the user."""

    if not raw.strip():
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as error:
        st.error(f"Invalid show_if JSON: {error.msg}")
        return None


def render_options_editor(
    base_key: str, question_type: str, existing_options: Sequence[str] | None
) -> List[str]:
    """Render a dynamic options editor for list-based questions."""

    if question_type not in {"single", "multiselect"}:
        st.caption("Options are not used for this question type.")
        return []

    st.caption(
        "Add the answer choices below. Use the ⊕ button to create new rows and drag to reorder."
    )

    option_rows = (
        [{"Option": option} for option in existing_options or []]
        or [{"Option": ""}]
    )
    edited_rows = st.data_editor(
        option_rows,
        num_rows="dynamic",
        hide_index=True,
        use_container_width=True,
        key=f"{base_key}_options_editor_{question_type}",
    )

    if hasattr(edited_rows, "to_dict"):
        rows_iterable = edited_rows.to_dict(orient="records")  # type: ignore[call-arg]
    elif isinstance(edited_rows, list):
        rows_iterable = edited_rows
    else:
        rows_iterable = []

    cleaned: List[str] = []
    for row in rows_iterable:
        value = row.get("Option", "") if isinstance(row, dict) else None
        if not isinstance(value, str):
            continue
        trimmed = value.strip()
        if trimmed:
            cleaned.append(trimmed)

    if not cleaned:
        st.info("Provide at least one option to offer selectable answers.")

    return cleaned


def render_related_record_settings(
    base_key: str, question_type: str, current_source: Optional[str]
) -> Optional[str]:
    """Render configuration inputs for related record questions."""

    if question_type != "related_record":
        return None

    source_keys = list(RELATED_RECORD_SOURCES.keys())
    if not source_keys:
        st.warning("No related record sources are configured.")
        return None

    default_index = 0
    if current_source in source_keys:
        default_index = source_keys.index(current_source)

    return st.selectbox(
        "Record source",
        options=source_keys,
        index=default_index,
        key=f"{base_key}_related_record_source",
        format_func=related_record_source_label,
        help="Choose which submissions repository this question should reference.",
    )


def render_question_overview(questions: Sequence[Dict[str, Any]]) -> None:
    """Show a compact table summarising all configured questions."""

    st.subheader("Question overview")
    if not questions:
        st.info("Questions will appear here once added.")
        return

    overview_rows = []
    for index, question in enumerate(questions, start=1):
        overview_rows.append(
            {
                "#": index,
                "Label": question.get("label", ""),
                "Key": question.get("key", ""),
                "Type": question.get("type", ""),
                "Conditions": "Yes" if question.get("show_if") else "No",
            }
        )

    st.dataframe(overview_rows, use_container_width=True, hide_index=True)


def sync_show_if_builder_state(schema: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Ensure the rule builder session state mirrors the current schema."""

    questionnaire_id = _active_questionnaire_id(schema)
    all_states: Dict[str, Dict[str, Any]] = st.session_state.setdefault(
        SHOW_IF_BUILDER_STATE_KEY,
        {},
    )
    builder_state = all_states.setdefault(questionnaire_id, {})
    valid_keys = set()
    for question in schema.get("questions", []):
        key = question.get("key")
        if not key:
            continue
        valid_keys.add(key)

        show_if = question.get("show_if") or {}
        existing_state = builder_state.get(key, {})

        parsed_state = _rule_to_groups(show_if) if show_if else {"groups": [], "combine_mode": "all"}
        unsupported = bool(show_if) and parsed_state is None

        if unsupported:
            groups = deepcopy(existing_state.get("groups", []))
            combine_mode = existing_state.get("combine_mode", "all")
        else:
            groups = (
                deepcopy(parsed_state["groups"])
                if parsed_state is not None
                else deepcopy(existing_state.get("groups", []))
            )
            combine_mode = (
                parsed_state.get("combine_mode", "all")
                if parsed_state is not None
                else existing_state.get("combine_mode", "all")
            )

        if groups is None:
            groups = []

        _normalize_groups(groups)
        _ensure_group_labels(groups)

        active_group = existing_state.get("active_group", -1 if not groups else 0)
        if not groups:
            active_group = -1
        elif not 0 <= active_group < len(groups):
            active_group = 0

        builder_state[key] = {
            "groups": groups,
            "combine_mode": combine_mode if combine_mode in {"all", "any"} else "all",
            "active_group": active_group,
            "unsupported": unsupported,
        }

    for key in list(builder_state.keys()):
        if key not in valid_keys:
            builder_state.pop(key)

    all_states[questionnaire_id] = builder_state
    st.session_state[SHOW_IF_BUILDER_STATE_KEY] = all_states
    return builder_state


def _question_lookup(questions: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Return a lookup dictionary keyed by question key."""

    lookup: Dict[str, Dict[str, Any]] = {}
    for question in questions:
        key = question.get("key")
        if isinstance(key, str) and key:
            lookup[key] = question
    return lookup


def _operator_options(question: Optional[Dict[str, Any]]) -> List[str]:
    """Return operator keys applicable to the referenced question."""

    if not question:
        return ["always"]

    question_type = question.get("type")
    operators = QUESTION_TYPE_OPERATORS.get(str(question_type), DEFAULT_OPERATORS)
    if "always" not in operators:
        operators = [*operators, "always"]
    return operators or DEFAULT_OPERATORS


def _format_question_option(key: str, lookup: Dict[str, Dict[str, Any]]) -> str:
    """Return a user-friendly label for a question selection option."""

    if not key:
        return "Always (no condition)"

    question = lookup.get(key, {})
    label = question.get("label")
    if isinstance(label, str) and label:
        return f"{label} ({key})"
    return key


def _format_clause_value(value: Any) -> str:
    """Return a readable representation of a clause value."""

    if value is None or value == "":
        return "—"
    if isinstance(value, (list, tuple, set)):
        return ", ".join(str(item) for item in value)
    return str(value)


def render_page_content_editor(schema: Dict[str, Any]) -> None:
    """Render controls for editing questionnaire page content."""

    page_settings = schema.get("page") if isinstance(schema.get("page"), dict) else {}
    introduction_settings = (
        page_settings.get("introduction")
        if isinstance(page_settings.get("introduction"), dict)
        else {}
    )
    submit_settings = (
        page_settings.get("submit")
        if isinstance(page_settings.get("submit"), dict)
        else {}
    )

    if "title" in page_settings:
        page_title_value = str(page_settings.get("title") or "")
    else:
        page_title_value = DEFAULT_PAGE_TITLE

    if "heading" in introduction_settings:
        intro_heading_value = str(introduction_settings.get("heading") or "")
    else:
        intro_heading_value = DEFAULT_INTRO_HEADING

    if "paragraphs" in introduction_settings:
        paragraphs_source = introduction_settings.get("paragraphs")
        if isinstance(paragraphs_source, list):
            intro_paragraphs_value = "\n".join(str(item) for item in paragraphs_source)
        elif isinstance(paragraphs_source, str):
            intro_paragraphs_value = paragraphs_source
        else:
            intro_paragraphs_value = ""
    else:
        intro_paragraphs_value = "\n".join(intro_paragraphs_list())

    if "label" in submit_settings:
        submit_label_value = str(submit_settings.get("label") or "")
    else:
        submit_label_value = DEFAULT_SUBMIT_LABEL

    if "success_message" in submit_settings:
        submit_success_value = str(submit_settings.get("success_message") or "")
    else:
        submit_success_value = DEFAULT_SUBMIT_SUCCESS_MESSAGE

    show_introduction_value = bool(
        page_settings.get("show_introduction")
        if "show_introduction" in page_settings
        else DEFAULT_SHOW_INTRODUCTION
    )
    show_debug_value = bool(
        page_settings.get("show_debug_answers")
        if "show_debug_answers" in page_settings
        else DEFAULT_SHOW_DEBUG
    )
    debug_label_value = (
        str(page_settings.get("debug_expander_label") or "")
        if "debug_expander_label" in page_settings
        else DEFAULT_DEBUG_LABEL
    )
    show_answers_summary_value = bool(
        submit_settings.get("show_answers_summary")
        if "show_answers_summary" in submit_settings
        else DEFAULT_SHOW_ANSWERS_SUMMARY
    )

    st.subheader("Page content")
    with st.form("page_content"):
        page_title = st.text_input("Page title", value=page_title_value)
        show_intro = st.checkbox(
            "Show introduction", value=show_introduction_value
        )
        intro_heading = st.text_input(
            "Introduction heading",
            value=intro_heading_value,
            help="Supports emoji and plain text.",
        )
        intro_paragraphs = st.text_area(
            "Introduction paragraphs (one per line)",
            value=intro_paragraphs_value,
            help="Each line becomes a separate paragraph in the introduction card.",
        )
        submit_label = st.text_input("Submit button label", value=submit_label_value)
        submit_success = st.text_area(
            "Submission success message",
            value=submit_success_value,
        )
        show_answers_summary = st.checkbox(
            "Show answers after submission",
            value=show_answers_summary_value,
            help="Displays the captured answers below the success message.",
        )
        show_debug = st.checkbox(
            "Show debug answers expander",
            value=show_debug_value,
            help="Controls whether the questionnaire page shows the answers expander.",
        )
        debug_label = st.text_input(
            "Debug expander label",
            value=debug_label_value,
            help="Used as the label for the debug answers expander.",
        )
        submitted = st.form_submit_button("Save page content")

        if submitted:
            updated_page_settings = {
                key: value
                for key, value in page_settings.items()
                if key
                not in {
                    "title",
                    "show_introduction",
                    "introduction",
                    "show_debug_answers",
                    "debug_expander_label",
                    "submit",
                }
            }
            updated_page_settings["title"] = page_title.strip() or DEFAULT_PAGE_TITLE
            updated_page_settings["show_introduction"] = bool(show_intro)

            if show_intro:
                updated_intro = {
                    key: value
                    for key, value in introduction_settings.items()
                    if key not in {"heading", "paragraphs"}
                }
                updated_intro["heading"] = intro_heading.strip()
                raw_paragraphs = [line.rstrip() for line in intro_paragraphs.splitlines()]
                updated_intro["paragraphs"] = [
                    paragraph.strip()
                    for paragraph in raw_paragraphs
                    if paragraph.strip()
                ]
                updated_page_settings["introduction"] = updated_intro
            else:
                updated_page_settings.pop("introduction", None)

            updated_page_settings["show_debug_answers"] = bool(show_debug)
            if show_debug:
                updated_page_settings["debug_expander_label"] = (
                    debug_label.strip() or DEFAULT_DEBUG_LABEL
                )
            else:
                updated_page_settings.pop("debug_expander_label", None)

            preserved_submit = {
                key: value
                for key, value in submit_settings.items()
                if key not in {"label", "success_message", "show_answers_summary"}
            }
            preserved_submit["label"] = submit_label.strip() or DEFAULT_SUBMIT_LABEL
            preserved_submit["success_message"] = (
                submit_success.strip() or DEFAULT_SUBMIT_SUCCESS_MESSAGE
            )
            preserved_submit["show_answers_summary"] = bool(show_answers_summary)
            updated_page_settings["submit"] = preserved_submit

            schema["page"] = updated_page_settings
            st.session_state[SCHEMA_STATE_KEY] = schema
            st.success("Page content updated. Use Publish or Save as Draft to persist changes.")

def render_show_if_builder(
    question: Dict[str, Any],
    schema: Dict[str, Any],
    json_state_key: str,
) -> None:
    """Render the guided rule builder UI scoped to a single question."""

    prefix = _state_prefix(schema)
    json_override_key = f"{json_state_key}_override"

    questions = schema.get("questions", [])
    if not questions:
        st.info("Add questions to configure show_if rules.")
        return

    question_key = question.get("key")
    if not isinstance(question_key, str) or not question_key:
        st.info("Assign a key to this question before configuring visibility rules.")
        return

    builder_state = sync_show_if_builder_state(schema)

    question_keys = [q.get("key") for q in questions if q.get("key")]
    if question_key not in question_keys:
        st.info("Save the question to use the rule builder.")
        return

    lookup = _question_lookup(questions)
    target_question = lookup.get(question_key)
    if target_question is None:
        return

    target_state = builder_state.setdefault(
        question_key,
        {
            "groups": [],
            "combine_mode": "all",
            "active_group": -1,
            "unsupported": False,
        },
    )

    if target_state.get("unsupported"):
        st.warning(
            "This rule contains advanced combinations that are not supported by the "
            "builder. Use the JSON editor to modify it."
        )
        return

    groups = target_state.setdefault("groups", [])
    _normalize_groups(groups)
    _ensure_group_labels(groups)

    combine_mode = target_state.get("combine_mode", "all")
    if combine_mode not in {"all", "any"}:
        combine_mode = "all"
    target_state["combine_mode"] = combine_mode

    active_group_index = target_state.get("active_group", 0)
    if not groups:
        active_group_index = -1
    elif not 0 <= active_group_index < len(groups):
        active_group_index = 0
    target_state["active_group"] = active_group_index

    def _sync_question_rule() -> None:
        """Update the question schema and JSON editor when rules change."""

        rule_expression = _groups_to_rule(groups, target_state.get("combine_mode", "all"))
        if rule_expression:
            target_question["show_if"] = rule_expression
        else:
            target_question.pop("show_if", None)

        if target_question.get("show_if"):
            st.session_state[json_override_key] = json.dumps(
                target_question["show_if"],
                indent=2,
            )
        else:
            st.session_state[json_override_key] = ""

        st.session_state[SCHEMA_STATE_KEY] = schema

    _sync_question_rule()

    group_selector_key = f"show_if_active_group_{prefix}_{question_key}"
    pending_selector_key = f"show_if_pending_active_group_{prefix}_{question_key}"
    pending_active_group = st.session_state.pop(pending_selector_key, None)
    if pending_active_group is not None:
        st.session_state[group_selector_key] = pending_active_group
    if groups:
        if group_selector_key not in st.session_state:
            st.session_state[group_selector_key] = (
                active_group_index if active_group_index >= 0 else 0
            )
        if not 0 <= st.session_state[group_selector_key] < len(groups):
            st.session_state[group_selector_key] = 0
    else:
        st.session_state[group_selector_key] = -1

    st.subheader("Rule groups overview")
    if groups:
        for idx, group in enumerate(groups):
            mode_label = str(group.get("mode", "all")).upper()
            clause_count = len(group.get("clauses", []))
            label = group.get("label", f"Group {idx + 1}")
            st.caption(
                f"{label}: {mode_label} · {clause_count} clause"
                f"{'s' if clause_count != 1 else ''}"
            )
    else:
        st.info("This question does not have any rule groups yet.")

    selected_group_index = -1
    if groups:
        selected_group_index = st.selectbox(
            "Choose a rule group to edit",
            options=list(range(len(groups))),
            key=group_selector_key,
            format_func=lambda idx: groups[idx].get("label", f"Group {idx + 1}"),
            help="Pick which group of rules you would like to review or update.",
        )
        target_state["active_group"] = selected_group_index

    add_group_clicked = st.button(
        "Add rule group", key=f"show_if_add_group_{prefix}_{question_key}", help="Create a new set of conditions for showing this question."
    )

    if add_group_clicked:
        new_group = {
            "mode": "all",
            "clauses": [{"operator": "always"}],
            "label": _generate_group_label(groups),
        }
        groups.append(new_group)
        _normalize_groups(groups)
        _ensure_group_labels(groups)
        new_index = len(groups) - 1
        target_state["active_group"] = new_index
        st.session_state[pending_selector_key] = new_index
        _sync_question_rule()
        st.success("Rule group added.")
        _rerun_app()
        return

    if len(groups) > 1:
        combine_key = f"show_if_group_combine_{prefix}_{question_key}"
        combine_choice = st.radio(
            "Show this question when",
            options=("all", "any"),
            index=(0 if target_state.get("combine_mode", "all") == "all" else 1),
            key=combine_key,
            horizontal=True,
            format_func=lambda value: "every group matches" if value == "all" else "any group matches",
            help="Control how the rule groups work together.",
        )
        if combine_choice != target_state.get("combine_mode"):
            target_state["combine_mode"] = combine_choice
            _sync_question_rule()

    if selected_group_index == -1:
        return

    active_group = groups[selected_group_index]
    _normalize_groups(groups)
    _ensure_group_labels(groups)

    label_col, mode_col, remove_col, save_col = st.columns([3, 2, 1, 1])

    group_label_key = f"show_if_group_label_{prefix}_{question_key}_{selected_group_index}"
    current_label = active_group.get("label", f"Group {selected_group_index + 1}")
    stored_label = st.session_state.get(group_label_key)
    if stored_label != current_label:
        st.session_state[group_label_key] = current_label

    with label_col:
        entered_label = st.text_input(
            "Group title",
            key=group_label_key,
            help="Give this group a clear name so it is easy to find later.",
        )
        sanitized_label = entered_label.strip()
        if not sanitized_label:
            sanitized_label = f"Group {selected_group_index + 1}"

        if sanitized_label != current_label:
            duplicate = any(
                sanitized_label == group.get("label")
                for idx, group in enumerate(groups)
                if idx != selected_group_index
            )
            if duplicate:
                st.warning("Group name must be unique.")
                st.session_state[group_label_key] = current_label
            else:
                active_group["label"] = sanitized_label
                st.session_state[group_label_key] = sanitized_label
                _ensure_group_labels(groups)

    group_mode_key = f"show_if_group_mode_{prefix}_{question_key}_{selected_group_index}"
    current_mode = active_group.get("mode", "all")
    if current_mode not in {"all", "any"}:
        current_mode = "all"
    with mode_col:
        mode_choice = st.radio(
            "Inside this group require",
            options=("all", "any"),
            index=(0 if current_mode == "all" else 1),
            key=group_mode_key,
            horizontal=True,
            format_func=lambda value: "all conditions" if value == "all" else "any condition",
            help="Choose whether every clause must match or if one match is enough.",
        )
        if mode_choice != current_mode:
            active_group["mode"] = mode_choice
            _sync_question_rule()

    with remove_col:
        remove_disabled = len(groups) == 0
        remove_clicked = st.button(
            "Delete group",
            key=f"show_if_remove_group_{prefix}_{question_key}_{selected_group_index}",
            disabled=remove_disabled,
            help="Remove this group and all of its clauses.",
        )
        if remove_clicked and not remove_disabled:
            groups.pop(selected_group_index)
            _normalize_groups(groups)
            _ensure_group_labels(groups)
            if groups:
                new_index = min(selected_group_index, len(groups) - 1)
            else:
                new_index = -1
            target_state["active_group"] = new_index
            st.session_state[pending_selector_key] = new_index
            _sync_question_rule()
            st.success("Rule group removed.")
            _rerun_app()
            return

    with save_col:
        if st.button(
            "Save changes",
            key=f"show_if_save_group_{prefix}_{question_key}_{selected_group_index}",
            help="Record updates you've made to this group.",
        ):
            _sync_question_rule()
            st.success("Rule group saved.")

    active_group.setdefault("clauses", [])

    clause_question_options = [key for key in question_keys if key != question_key] or question_keys
    field_options = [""] + clause_question_options

    if active_group["clauses"]:
        st.markdown("**Clauses in this group**")
        for idx, clause in enumerate(active_group["clauses"]):
            clause_field_label = _format_question_option(
                str(clause.get("field", "") or ""),
                lookup,
            )
            operator_details = OPERATOR_DEFINITIONS.get(clause.get("operator", ""), {})
            operator_label = operator_details.get("label", clause.get("operator", ""))
            summary_parts: List[str] = []
            if clause.get("field"):
                summary_parts.append(clause_field_label)
            summary_parts.append(operator_label)
            clause_summary = " · ".join(part for part in summary_parts if part)
            if not clause_summary:
                clause_summary = f"Clause {idx + 1}"

            with st.expander(f"Clause {idx + 1}: {clause_summary}"):
                edit_field_col, edit_operator_col = st.columns([2, 2])

                current_field_value = str(clause.get("field", "") or "")
                available_field_options = list(field_options)
                if current_field_value and current_field_value not in available_field_options:
                    available_field_options.append(current_field_value)
                edit_field_key = (
                    f"show_if_existing_field_{prefix}_{question_key}_{selected_group_index}_{idx}"
                )
                with edit_field_col:
                    selected_field_value = st.selectbox(
                        "Question to reference",
                        options=available_field_options,
                        index=available_field_options.index(current_field_value),
                        key=edit_field_key,
                        format_func=lambda key: _format_question_option(key, lookup),
                        help="Choose which question's answer this clause should evaluate.",
                    )

                referenced_question = (
                    lookup.get(selected_field_value) if selected_field_value else None
                )
                operator_options = _operator_options(referenced_question)
                current_operator_value = str(
                    clause.get("operator", operator_options[0] if operator_options else "equals")
                )
                if current_operator_value not in operator_options:
                    operator_options = [current_operator_value] + [
                        option for option in operator_options if option != current_operator_value
                    ]
                edit_operator_key = (
                    f"show_if_existing_operator_{prefix}_{question_key}_{selected_group_index}_{idx}"
                )
                with edit_operator_col:
                    selected_operator_value = st.selectbox(
                        "Condition type",
                        options=operator_options,
                        index=operator_options.index(current_operator_value),
                        key=edit_operator_key,
                        format_func=lambda op: OPERATOR_DEFINITIONS.get(op, {}).get("label", op),
                        help="Select how the referenced answer should be compared.",
                    )
                    selected_operator_definition = OPERATOR_DEFINITIONS.get(
                        selected_operator_value, {}
                    )
                    operator_description = selected_operator_definition.get("description")
                    if operator_description:
                        st.caption(operator_description)

                if selected_operator_value != current_operator_value:
                    clause["operator"] = selected_operator_value
                    selected_operator_definition = OPERATOR_DEFINITIONS.get(
                        selected_operator_value, {}
                    )
                    _sync_question_rule()
                else:
                    selected_operator_definition = OPERATOR_DEFINITIONS.get(
                        current_operator_value, {}
                    )

                if selected_field_value:
                    if clause.get("field") != selected_field_value:
                        clause["field"] = selected_field_value
                        _sync_question_rule()
                elif "field" in clause:
                    clause.pop("field", None)
                    _sync_question_rule()

                value_mode = selected_operator_definition.get("value_mode", "none")
                if selected_operator_value != "always" and not selected_field_value:
                    st.warning("Choose a question to reference for this clause.")

                if value_mode == "single":
                    value_options: List[str] = []
                    if referenced_question:
                        reference_options = referenced_question.get("options")
                        if isinstance(reference_options, list):
                            value_options = [
                                str(option) for option in reference_options if isinstance(option, str)
                            ]

                    if value_options:
                        current_value = str(clause.get("value", value_options[0]))
                        if current_value not in value_options:
                            value_options = [current_value] + [
                                option for option in value_options if option != current_value
                            ]
                        value_single_key = (
                            f"show_if_existing_value_single_{question_key}_{selected_group_index}_{idx}"
                        )
                        selected_value = st.selectbox(
                            "Comparison value",
                            options=value_options,
                            index=value_options.index(current_value),
                            key=value_single_key,
                            help="Pick the answer choice that should trigger this clause.",
                        )
                        if clause.get("value") != selected_value:
                            clause["value"] = selected_value
                            _sync_question_rule()
                    else:
                        value_text_key = (
                            f"show_if_existing_value_text_{question_key}_{selected_group_index}_{idx}"
                        )
                        if value_text_key not in st.session_state:
                            st.session_state[value_text_key] = str(clause.get("value", ""))
                        entered_value = st.text_input(
                            "Comparison value",
                            key=value_text_key,
                            placeholder="Enter a value to compare against",
                        )
                        sanitized_value = entered_value.strip()
                        if sanitized_value:
                            if clause.get("value") != sanitized_value:
                                clause["value"] = sanitized_value
                                _sync_question_rule()
                        else:
                            if "value" in clause:
                                clause.pop("value", None)
                                _sync_question_rule()
                            st.info("Provide a value to compare against.")
                elif value_mode == "multi":
                    value_options = []
                    if referenced_question:
                        reference_options = referenced_question.get("options")
                        if isinstance(reference_options, list):
                            value_options = [
                                str(option) for option in reference_options if isinstance(option, str)
                            ]

                    if value_options:
                        existing_values = clause.get("value")
                        if not isinstance(existing_values, list):
                            existing_values = []
                        normalized_existing = [str(option) for option in existing_values]
                        value_multi_key = (
                            f"show_if_existing_value_multi_{question_key}_{selected_group_index}_{idx}"
                        )
                        if value_multi_key not in st.session_state:
                            st.session_state[value_multi_key] = normalized_existing
                        st.session_state[value_multi_key] = [
                            option
                            for option in st.session_state[value_multi_key]
                            if option in value_options
                        ]
                        selected_values = st.multiselect(
                            "Matching values",
                            options=value_options,
                            default=st.session_state[value_multi_key],
                            key=value_multi_key,
                            help="Select all answers that should satisfy this clause.",
                        )
                        if clause.get("value") != selected_values:
                            clause["value"] = selected_values
                            _sync_question_rule()
                        if not selected_values:
                            st.info("Select at least one value to keep this clause active.")
                    else:
                        value_rows_key = (
                            f"show_if_existing_value_rows_{question_key}_{selected_group_index}_{idx}"
                        )
                        existing_rows = st.session_state.get(value_rows_key)
                        if existing_rows is None:
                            clause_values = clause.get("value")
                            if isinstance(clause_values, Sequence) and not isinstance(clause_values, str):
                                default_rows = [
                                    {"Value": str(item)} for item in clause_values if str(item).strip()
                                ] or [{"Value": ""}]
                            else:
                                default_rows = [{"Value": ""}]
                        else:
                            default_rows = existing_rows
                        value_rows = st.data_editor(
                            default_rows,
                            num_rows="dynamic",
                            hide_index=True,
                            key=value_rows_key,
                            use_container_width=True,
                        )

                        if hasattr(value_rows, "to_dict"):
                            rows_iterable = value_rows.to_dict(orient="records")  # type: ignore[call-arg]
                        elif isinstance(value_rows, list):
                            rows_iterable = value_rows
                        else:
                            rows_iterable = []

                        extracted: List[str] = []
                        for row in rows_iterable:
                            if isinstance(row, dict):
                                raw_value = str(row.get("Value", "")).strip()
                            else:
                                raw_value = str(row).strip()
                            if raw_value:
                                extracted.append(raw_value)

                        if clause.get("value") != extracted:
                            clause["value"] = extracted
                            _sync_question_rule()
                        if not extracted:
                            st.info("Add at least one value for this clause.")
                else:
                    if "value" in clause:
                        clause.pop("value", None)
                        _sync_question_rule()

                remove_key = f"remove_clause_{question_key}_{selected_group_index}_{idx}"
                if st.button(
                    "Remove clause",
                    key=remove_key,
                    help="Delete this condition from the group.",
                ):
                    active_group["clauses"].pop(idx)
                    _sync_question_rule()
                    _rerun_app()
                    return

    st.divider()
    st.markdown("**Add a new clause**")

    field_state_key = f"show_if_clause_field_{question_key}_{selected_group_index}"
    if field_state_key not in st.session_state:
        st.session_state[field_state_key] = field_options[1] if len(field_options) > 1 else ""
    if st.session_state[field_state_key] not in field_options:
        st.session_state[field_state_key] = field_options[0]

    selector_col, operator_col = st.columns([2, 2])
    with selector_col:
        clause_field_key = st.selectbox(
            "Question to reference",
            options=field_options,
            index=field_options.index(st.session_state[field_state_key]),
            key=field_state_key,
            format_func=lambda key: _format_question_option(key, lookup),
            help="Pick which existing question this new clause should depend on.",
        )

    referenced_question = lookup.get(clause_field_key) if clause_field_key else None

    operator_options = _operator_options(referenced_question)
    operator_state_key = f"show_if_operator_{question_key}_{selected_group_index}"
    if operator_state_key not in st.session_state:
        st.session_state[operator_state_key] = operator_options[0]
    if st.session_state[operator_state_key] not in operator_options:
        st.session_state[operator_state_key] = operator_options[0]

    with operator_col:
        selected_operator = st.selectbox(
            "Condition type",
            options=operator_options,
            index=operator_options.index(st.session_state[operator_state_key]),
            key=operator_state_key,
            format_func=lambda op: OPERATOR_DEFINITIONS.get(op, {}).get("label", op),
            help="Decide how the selected question should be evaluated.",
        )
        operator_definition = OPERATOR_DEFINITIONS.get(selected_operator, {})
        operator_description = operator_definition.get("description")
        if operator_description:
            st.caption(operator_description)

    value_mode = operator_definition.get("value_mode", "none")
    value: Any = None
    value_valid = True

    if value_mode == "single":
        value_options: List[str] = []
        if referenced_question:
            reference_options = referenced_question.get("options")
            if isinstance(reference_options, list):
                value_options = [str(option) for option in reference_options if isinstance(option, str)]

        if value_options:
            value_single_key = f"show_if_value_single_{question_key}_{selected_group_index}"
            if value_single_key not in st.session_state:
                st.session_state[value_single_key] = value_options[0]
            if st.session_state[value_single_key] not in value_options:
                st.session_state[value_single_key] = value_options[0]
            value = st.selectbox(
                "Comparison value",
                options=value_options,
                index=value_options.index(st.session_state[value_single_key]),
                key=value_single_key,
                help="Pick the answer that should satisfy this new clause.",
            )
        else:
            value = st.text_input(
                "Comparison value",
                key=f"show_if_value_text_{question_key}_{selected_group_index}",
                placeholder="Enter a value to compare against",
            )
            value_valid = bool(str(value).strip())
            if not value_valid:
                st.info("Provide a value to compare against.")
    elif value_mode == "multi":
        value_options = []
        if referenced_question:
            reference_options = referenced_question.get("options")
            if isinstance(reference_options, list):
                value_options = [str(option) for option in reference_options if isinstance(option, str)]

        if value_options:
            value_multi_key = f"show_if_value_multi_{question_key}_{selected_group_index}"
            if value_multi_key not in st.session_state:
                st.session_state[value_multi_key] = []
            if st.session_state[value_multi_key]:
                st.session_state[value_multi_key] = [
                    option for option in st.session_state[value_multi_key] if option in value_options
                ]
            value = st.multiselect(
                "Matching values",
                options=value_options,
                default=st.session_state[value_multi_key],
                key=value_multi_key,
                help="Choose one or more answers that should satisfy this clause.",
            )
            value_valid = bool(value)
            if not value_valid:
                st.info("Select at least one value to compare against.")
        else:
            value_rows_key = f"show_if_value_rows_{question_key}_{selected_group_index}"
            existing_rows = st.session_state.get(value_rows_key)
            if existing_rows is None:
                default_rows: Sequence[Any] = [{"Value": ""}]
            else:
                default_rows = existing_rows
            value_rows = st.data_editor(
                default_rows,
                num_rows="dynamic",
                hide_index=True,
                key=value_rows_key,
                use_container_width=True,
            )

            rows_iterable: Sequence[Any]
            if hasattr(value_rows, "to_dict"):
                rows_iterable = value_rows.to_dict(orient="records")  # type: ignore[call-arg]
            elif isinstance(value_rows, list):
                rows_iterable = value_rows
            else:
                rows_iterable = []

            extracted: List[str] = []
            for row in rows_iterable:
                if isinstance(row, dict):
                    raw_value = str(row.get("Value", "")).strip()
                else:
                    raw_value = str(row).strip()
                if raw_value:
                    extracted.append(raw_value)

            value = extracted
            value_valid = bool(extracted)
            if not extracted:
                st.info("Add at least one value for this clause.")

    if st.button(
        "Add condition",
        key=f"show_if_add_clause_{prefix}_{question_key}_{selected_group_index}",
        help="Append this new condition to the selected group.",
    ):
        if selected_operator != "always" and not clause_field_key:
            st.error("Select a question to reference for this clause.")
        elif value_mode == "single" and not value_valid:
            st.error("Provide a value to compare against.")
        elif value_mode == "multi" and not value_valid:
            st.error("Provide at least one value for this condition.")
        else:
            clause: Dict[str, Any] = {"operator": selected_operator}
            if clause_field_key:
                clause["field"] = clause_field_key
            if value_mode == "single":
                clause_value = value
                if isinstance(clause_value, str):
                    clause_value = clause_value.strip()
                clause["value"] = clause_value
            elif value_mode == "multi":
                clause["value"] = value

            active_group["clauses"].append(clause)
            _sync_question_rule()

            st.session_state.pop(f"show_if_value_text_{question_key}_{selected_group_index}", None)
            st.session_state.pop(f"show_if_value_single_{question_key}_{selected_group_index}", None)
            st.session_state.pop(f"show_if_value_multi_{question_key}_{selected_group_index}", None)
            st.session_state.pop(f"show_if_value_rows_{question_key}_{selected_group_index}", None)
            st.success("Condition added.")

    clear_col, _ = st.columns([1, 3])
    with clear_col:
        if st.button("Clear all rules", key=f"clear_show_if_{question_key}", help="Remove every rule group and start fresh."):
            target_state["groups"] = []
            target_state["combine_mode"] = "all"
            st.session_state[group_selector_key] = -1
            target_state["active_group"] = -1
            _sync_question_rule()
            st.success("All show_if rules cleared.")
            _rerun_app()

    if target_question.get("show_if"):
        st.markdown("**Current rule JSON**")
        st.json(target_question["show_if"])
    else:
        st.info("No show_if rule configured for this question.")


def eval_clause(clause: Dict[str, Any], answers: Dict[str, Any]) -> bool:
    """Evaluate a single rule clause against preview answers."""

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
    """Evaluate a composite rule against preview answers."""

    if not rule:
        return True
    if "all" in rule:
        return all(eval_rule(subrule, answers) for subrule in rule.get("all", []))
    if "any" in rule:
        return any(eval_rule(subrule, answers) for subrule in rule.get("any", []))
    return eval_clause(rule, answers)


def should_show_question(question: Dict[str, Any], answers: Dict[str, Any]) -> bool:
    """Determine whether a preview question should be displayed."""

    show_if = question.get("show_if")
    if not show_if:
        return True
    return eval_rule(show_if, answers)


def render_preview_question(
    question: Dict[str, Any], answers: Dict[str, Any], *, prefix: str = ""
) -> None:
    """Render an individual question widget for the live preview."""

    question_key = question["key"]
    widget_key = f"preview_question_{prefix}_{question_key}" if prefix else f"preview_question_{question_key}"

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
        index = options.index(default_value) if default_value in options else 0
        selection = st.radio(
            label,
            options,
            index=index,
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
        selection = st.checkbox(
            label,
            value=default_bool,
            key=widget_key,
            help=help_text,
        )
        answers[question_key] = selection
    elif question_type in {"text", RECORD_NAME_TYPE}:
        default_text = "" if default_value is None else str(default_value)
        text_value = st.text_input(
            label,
            value=default_text,
            key=widget_key,
            placeholder=question.get("placeholder"),
            help=help_text,
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
                "Related record questions require a valid source. Update the configuration to continue."
            )
            return

        options = load_related_record_options(source_key)
        if not options:
            answers.pop(question_key, None)
            if widget_key in st.session_state:
                st.session_state.pop(widget_key)
            st.info(
                f"No records available for {related_record_source_label(source_key)} yet."
            )
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
            help=help_text,
            format_func=lambda value: labels.get(value, value),
        )
        answers[question_key] = selection
        st.caption(f"Selected record ID: `{selection}`")
    elif question_type == "statement":
        answers.pop(question_key, None)
        if widget_key in st.session_state:
            st.session_state.pop(widget_key)
        st.info(label)
        if help_text:
            st.caption(help_text)
    else:
        st.warning(f"Unsupported question type: {question_type}")


def _rename_show_if_fields(schema: Dict[str, Any], old_key: str, new_key: str) -> None:
    """Update show_if rule field references when a question key changes."""

    def _update_rule(rule: Any) -> None:
        if isinstance(rule, dict):
            if rule.get("field") == old_key:
                rule["field"] = new_key
            for value in rule.values():
                _update_rule(value)
        elif isinstance(rule, list):
            for item in rule:
                _update_rule(item)

    for question in schema.get("questions", []):
        show_if = question.get("show_if")
        if show_if:
            _update_rule(show_if)

def validate_schema(schema: Dict[str, Any]) -> List[str]:
    """Run simple validation checks on the questionnaire schema."""

    errors: List[str] = []
    questions = schema.get("questions", [])

    seen_keys = set()
    for question in questions:
        key = question.get("key")
        if not key:
            errors.append("All questions must define a key.")
            continue
        if key in seen_keys:
            errors.append(f"Duplicate question key detected: {key}")
        seen_keys.add(key)

    def iter_rule_fields(rule: Any) -> List[str]:
        fields: List[str] = []
        if isinstance(rule, dict):
            field_value = rule.get("field")
            if isinstance(field_value, str):
                fields.append(field_value)
            for value in rule.values():
                if isinstance(value, dict):
                    fields.extend(iter_rule_fields(value))
                elif isinstance(value, list):
                    for item in value:
                        fields.extend(iter_rule_fields(item))
        elif isinstance(rule, list):
            for item in rule:
                fields.extend(iter_rule_fields(item))
        return fields

    for question in questions:
        show_if = question.get("show_if")
        if not show_if:
            continue
        for field in iter_rule_fields(show_if):
            if field not in seen_keys:
                errors.append(
                    f"Question '{question.get('key', '<unknown>')}' references unknown field '{field}' in show_if rules."
                )

    return errors


def handle_save_draft(schema: Dict[str, Any]) -> None:
    """Save the current schema to a draft branch and ensure a PR exists."""

    form_key, persistable, questionnaire_payload = schema_for_storage(schema)
    if not form_key:
        st.error("No questionnaire selected to save.")
        return

    errors = validate_schema(questionnaire_payload)
    if errors:
        for error in errors:
            st.error(error)
        return

    config = get_github_config()
    if config is None:
        st.error("GitHub configuration is required to save drafts.")
        return

    branch = st.session_state.get(DRAFT_BRANCH_STATE_KEY)
    if not branch:
        branch = f"draft/form-editor-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        st.session_state[DRAFT_BRANCH_STATE_KEY] = branch

    try:
        create_branch(config, branch)
    except Exception as exc:  # pylint: disable=broad-except
        st.error(f"Could not create draft branch: {exc}")
        return

    backend = GitHubBackend(
        token=config["token"],
        repo=config["repo"],
        path=resolve_remote_form_path(config["path"], form_key),
        branch=branch,
        api_url=config.get("api_url", "https://api.github.com"),
    )

    try:
        sha = backend.get_file_sha()
    except Exception as exc:  # pylint: disable=broad-except
        st.error(f"Could not read draft schema from GitHub: {exc}")
        return

    try:
        form_config = dict(config)
        form_config["path"] = resolve_remote_form_path(config["path"], form_key)
        put_file(
            form_config,
            persistable,
            sha,
            message=f"chore: save questionnaire draft ({branch})",
            branch=branch,
        )
    except Exception as exc:  # pylint: disable=broad-except
        st.error(f"Could not write draft schema to GitHub: {exc}")
        return

    try:
        pr = ensure_pr(
            config,
            branch,
            title="Draft: Update questionnaire schema",
            body="Automated draft update from the questionnaire editor.",
        )
    except Exception as exc:  # pylint: disable=broad-except
        st.error(f"Could not ensure draft pull request: {exc}")
        return

    st.success(f"Draft saved to branch {branch}.")
    pr_url = pr.get("html_url")
    if pr_url:
        st.markdown(f"[View pull request]({pr_url})")


def handle_publish(schema: Dict[str, Any]) -> None:
    """Publish the schema to the main branch or save locally if unavailable."""

    form_key, persistable, questionnaire_payload = schema_for_storage(schema)
    if not form_key:
        st.error("No questionnaire selected to publish.")
        return

    errors = validate_schema(questionnaire_payload)
    if errors:
        for error in errors:
            st.error(error)
        return

    config = get_github_config()
    if config is not None:
        backend = GitHubBackend(
            token=config["token"],
            repo=config["repo"],
            path=resolve_remote_form_path(config["path"], form_key),
            branch=config.get("branch", "main"),
            api_url=config.get("api_url", "https://api.github.com"),
        )

        sha_state_obj = st.session_state.get(SCHEMA_SHA_STATE_KEY, {})
        if not isinstance(sha_state_obj, dict):
            sha_state_obj = {}
        sha_state = sha_state_obj
        stored_sha = sha_state.get(form_key)
        try:
            latest_sha = backend.get_file_sha()
        except Exception as exc:  # pylint: disable=broad-except
            st.error(f"Could not read schema from GitHub: {exc}")
            return

        if stored_sha is not None and stored_sha != latest_sha:
            st.error("Schema changed upstream—refresh and retry.")
            sha_state[form_key] = latest_sha
            st.session_state[SCHEMA_SHA_STATE_KEY] = sha_state
            return

        form_config = dict(config)
        form_config["path"] = resolve_remote_form_path(config["path"], form_key)

        try:
            response = put_file(
                form_config,
                persistable,
                latest_sha,
                message="chore: publish questionnaire schema",
                branch=config.get("branch", "main"),
            )
        except Exception as exc:  # pylint: disable=broad-except
            st.error(f"Could not publish schema to GitHub: {exc}")
            return

        published_sha = None
        if isinstance(response, dict):
            published_sha = response.get("content", {}).get("sha")
        sha_state[form_key] = published_sha or latest_sha
        st.session_state[SCHEMA_SHA_STATE_KEY] = sha_state
        st.success("Schema published to the main branch.")
    else:
        try:
            sources: Dict[str, Path] = st.session_state.get(FORM_SOURCES_STATE_KEY, {})
            target_path = local_form_path(form_key, sources)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            with target_path.open("w", encoding="utf-8") as schema_file:
                json.dump(persistable, schema_file, indent=2)
                schema_file.write("\n")
            sources = dict(sources)
            sources[form_key] = target_path
            st.session_state[FORM_SOURCES_STATE_KEY] = sources
        except OSError as exc:
            st.error(f"Could not save schema locally: {exc}")
            return
        st.info("GitHub is not configured; schema saved locally instead.")
        sha_state_obj = st.session_state.setdefault(SCHEMA_SHA_STATE_KEY, {})
        if not isinstance(sha_state_obj, dict):
            sha_state_obj = {}
        sha_state_obj[form_key] = None
        st.session_state[SCHEMA_SHA_STATE_KEY] = sha_state_obj

    st.cache_data.clear()
    load_schema.clear()
    st.session_state[SCHEMA_STATE_KEY] = schema
    raw_payloads = st.session_state.setdefault(FORM_RAW_STATE_KEY, {})
    if isinstance(raw_payloads, dict):
        raw_payloads[form_key] = persistable
        st.session_state[FORM_RAW_STATE_KEY] = raw_payloads
    st.session_state.pop(DRAFT_BRANCH_STATE_KEY, None)


def render_question_editor(question: Dict[str, Any], schema: Dict[str, Any]) -> None:
    """Render the editor form for a single question."""

    original_key = question.get("key", "")
    prefix = _state_prefix(schema)
    show_if_json_key = f"show_if_json_{prefix}_{original_key}" if prefix else f"show_if_json_{original_key}"
    show_if_json_override_key = f"{show_if_json_key}_override"
    initial_show_if = (
        json.dumps(question.get("show_if", {}), indent=2)
        if question.get("show_if")
        else ""
    )
    if show_if_json_key not in st.session_state:
        st.session_state[show_if_json_key] = initial_show_if

    if show_if_json_override_key in st.session_state:
        st.session_state[show_if_json_key] = st.session_state.pop(
            show_if_json_override_key
        )

    form_key = f"edit_{prefix}_{original_key}" if prefix else f"edit_{original_key}"
    existing_related_source = question.get("related_record_source")

    with st.form(form_key):
        st.subheader(f"Edit question: {question.get('label', original_key)}")

        key_input = st.text_input(
            "Key",
            value=original_key,
            help="Unique identifier used in the schema. Letters, numbers, and underscores only.",
        )

        col_label, col_type = st.columns([3, 2])
        with col_label:
            label = st.text_input(
                "Question label",
                value=question.get("label", ""),
                help="Shown to respondents on the questionnaire page.",
            )
        with col_type:
            current_type = question.get("type", "text")
            try:
                default_type_index = QUESTION_TYPES.index(current_type)
            except ValueError:
                default_type_index = QUESTION_TYPES.index("text")
            question_type = st.selectbox(
                "Answer type",
                options=QUESTION_TYPES,
                index=default_type_index,
                help="Determines how the answer is captured.",
                format_func=lambda value: QUESTION_TYPE_LABELS.get(value, value),
            )

        related_record_source = render_related_record_settings(
            form_key,
            question_type,
            existing_related_source if isinstance(existing_related_source, str) else None,
        )

        with st.expander(
            "Guidance and placeholders",
            expanded=bool(question.get("help") or question.get("placeholder")),
        ):
            help_text = st.text_area(
                "Help text",
                value=question.get("help", ""),
                help="Optional supporting text displayed beneath the label.",
            )
            placeholder = st.text_input(
                "Placeholder",
                value=question.get("placeholder", ""),
                help="Appears inside the input when no answer has been provided.",
            )

        options = render_options_editor(
            f"{prefix}_{original_key}" if prefix else original_key,
            question_type,
            question.get("options"),
        )

        with st.expander(
            "Visibility conditions",
            expanded=bool(question.get("show_if")),
        ):
            st.caption(
                "Use the rule builder below for a guided experience or paste JSON here for advanced control."
            )
            show_if_raw = st.text_area(
                "Show if (JSON)",
                key=show_if_json_key,
                value=st.session_state.get(show_if_json_key, initial_show_if),
                placeholder='{"all": [{"field": "previous_question", "operator": "equals", "value": "Yes"}]}',
                help="JSON logic describing when the question should appear.",
            )

        col_save, col_delete = st.columns([3, 1])
        with col_save:
            submitted = st.form_submit_button("Save changes")
        with col_delete:
            delete_requested = st.form_submit_button("Delete question", type="secondary")

        if submitted:
            new_key = key_input.strip()
            if not new_key:
                st.error("Key is required.")
                return

            duplicate_key = any(
                existing.get("key") == new_key and existing is not question
                for existing in schema.get("questions", [])
            )
            if duplicate_key:
                st.error("A question with this key already exists.")
                return

            if question_type in {"single", "multiselect"} and not options:
                st.error("Add at least one option for selectable question types.")
                return

            show_if = parse_show_if(show_if_raw)
            if show_if_raw and show_if is None:
                return

            preserved_fields = {
                existing_key: value
                for existing_key, value in question.items()
                if existing_key
                not in {
                    "key",
                    "label",
                    "type",
                    "help",
                    "placeholder",
                    "options",
                    "show_if",
                    "related_record_source",
                }
            }

            updated_question: Dict[str, Any] = {
                **preserved_fields,
                "key": new_key,
                "label": label.strip() or new_key,
                "type": question_type,
            }
            if help_text.strip():
                updated_question["help"] = help_text.strip()
            if placeholder.strip():
                updated_question["placeholder"] = placeholder.strip()
            if options:
                updated_question["options"] = options
            if show_if:
                updated_question["show_if"] = show_if
            if question_type == "related_record":
                if not related_record_source:
                    st.error("Select a record source for related record questions.")
                    return
                updated_question["related_record_source"] = related_record_source

            for idx, existing in enumerate(schema.get("questions", [])):
                if existing.get("key") == original_key:
                    schema["questions"][idx] = updated_question
                    question = schema["questions"][idx]
                    break

            if new_key != original_key:
                preview_state = st.session_state.get(PREVIEW_ANSWERS_STATE_KEY)
                active_id = _active_questionnaire_id(schema)
                if isinstance(preview_state, dict):
                    answers = preview_state.get(active_id)
                    if isinstance(answers, dict) and original_key in answers:
                        answers[new_key] = answers.pop(original_key)
                        preview_state[active_id] = answers
                        st.session_state[PREVIEW_ANSWERS_STATE_KEY] = preview_state

                preview_widget_key = (
                    f"preview_question_{prefix}_{original_key}"
                    if prefix
                    else f"preview_question_{original_key}"
                )
                if preview_widget_key in st.session_state:
                    st.session_state.pop(preview_widget_key)

                builder_state = st.session_state.get(SHOW_IF_BUILDER_STATE_KEY)
                active_id = _active_questionnaire_id(schema)
                if isinstance(builder_state, dict):
                    questionnaire_state = builder_state.get(active_id)
                    if isinstance(questionnaire_state, dict) and original_key in questionnaire_state:
                        questionnaire_state[new_key] = questionnaire_state.pop(original_key)
                        builder_state[active_id] = questionnaire_state
                        st.session_state[SHOW_IF_BUILDER_STATE_KEY] = builder_state

                target_suffix = (
                    f"_{prefix}_{original_key}" if prefix else f"_{original_key}"
                )
                for session_key in list(st.session_state.keys()):
                    if session_key.startswith("show_if_") and session_key.endswith(target_suffix):
                        st.session_state.pop(session_key)

                _rename_show_if_fields(schema, original_key, new_key)

                new_show_if_json_key = (
                    f"show_if_json_{prefix}_{new_key}"
                    if prefix
                    else f"show_if_json_{new_key}"
                )
                st.session_state[new_show_if_json_key] = st.session_state.pop(
                    show_if_json_key,
                    json.dumps(question.get("show_if", {}), indent=2)
                    if question.get("show_if")
                    else "",
                )
                show_if_json_key = new_show_if_json_key
                original_key = new_key

            st.session_state[SCHEMA_STATE_KEY] = schema
            st.success("Question updated. Use Publish or Save as Draft to persist changes.")

        if delete_requested:
            schema["questions"] = [
                q for q in schema.get("questions", []) if q.get("key") != original_key
            ]
            preview_state = st.session_state.get(PREVIEW_ANSWERS_STATE_KEY)
            active_id = _active_questionnaire_id(schema)
            if isinstance(preview_state, dict):
                answers = preview_state.get(active_id)
                if isinstance(answers, dict) and original_key in answers:
                    answers.pop(original_key, None)
                    preview_state[active_id] = answers
                    st.session_state[PREVIEW_ANSWERS_STATE_KEY] = preview_state
            builder_state = st.session_state.get(SHOW_IF_BUILDER_STATE_KEY)
            if isinstance(builder_state, dict):
                questionnaire_state = builder_state.get(active_id)
                if isinstance(questionnaire_state, dict) and original_key in questionnaire_state:
                    questionnaire_state.pop(original_key, None)
                    builder_state[active_id] = questionnaire_state
                    st.session_state[SHOW_IF_BUILDER_STATE_KEY] = builder_state
            target_suffix = (
                f"_{prefix}_{original_key}" if prefix else f"_{original_key}"
            )
            for session_key in list(st.session_state.keys()):
                if session_key.endswith(target_suffix):
                    st.session_state.pop(session_key)
            st.session_state[SCHEMA_STATE_KEY] = schema
            st.warning("Question removed. Use Publish or Save as Draft to persist changes.")

    with st.expander("Rule builder", expanded=bool(question.get("show_if"))):
        render_show_if_builder(question, schema, show_if_json_key)


def render_add_question(schema: Dict[str, Any]) -> None:
    """Render the form to create a new question."""

    st.subheader("Add new question")
    prefix = _state_prefix(schema)
    form_key = f"add_question_{prefix}" if prefix else "add_question"
    with st.form(form_key):
        key = st.text_input(
            "Key",
            help="Unique identifier used in the schema. Letters, numbers, and underscores only.",
        )
        label = st.text_input(
            "Question label",
            help="Displayed to respondents. Leave blank to reuse the key.",
        )
        question_type = st.selectbox(
            "Answer type",
            options=QUESTION_TYPES,
            format_func=lambda value: QUESTION_TYPE_LABELS.get(value, value),
        )

        related_record_source = render_related_record_settings(
            form_key, question_type, None
        )

        with st.expander("Guidance and placeholders"):
            help_text = st.text_area(
                "Help text",
                help="Optional supporting text displayed beneath the label.",
            )
            placeholder = st.text_input(
                "Placeholder",
                help="Appears inside the input when no answer has been provided.",
            )

        options = render_options_editor(
            f"{prefix}_new" if prefix else "new", question_type, None
        )

        with st.expander("Visibility conditions"):
            st.caption(
                "Use the rule builder below for a guided experience or paste JSON here for advanced control."
            )
            show_if_raw = st.text_area(
                "Show if (JSON)",
                placeholder='{"any": [{"field": "q1", "operator": "equals", "value": "Yes"}]}',
            )

        submitted = st.form_submit_button("Add question")

        if submitted:
            if not key:
                st.error("Key is required.")
                return
            if any(question.get("key") == key for question in schema.get("questions", [])):
                st.error("A question with this key already exists.")
                return
            if question_type in {"single", "multiselect"} and not options:
                st.error("Add at least one option for selectable question types.")
                return

            show_if = parse_show_if(show_if_raw)
            if show_if_raw and show_if is None:
                return

            new_question: Dict[str, Any] = {
                "key": key,
                "label": label.strip() or key,
                "type": question_type,
            }
            if help_text.strip():
                new_question["help"] = help_text.strip()
            if placeholder.strip():
                new_question["placeholder"] = placeholder.strip()
            if options:
                new_question["options"] = options
            if show_if:
                new_question["show_if"] = show_if
            if question_type == "related_record":
                if not related_record_source:
                    st.error("Select a record source for related record questions.")
                    return
                new_question["related_record_source"] = related_record_source

            schema.setdefault("questions", []).append(new_question)
            st.session_state[SCHEMA_STATE_KEY] = schema
            st.success("Question added. Use Publish or Save as Draft to persist changes.")


def main() -> None:
    """Render the questionnaire editor page."""

    require_authentication()

    st.title("Questionnaire editor")
    st.caption("Authentication is assumed to have already succeeded.")

    schema = get_schema()
    questionnaires = schema.get("questionnaires", {})
    if not questionnaires:
        st.error("No questionnaires configured. Use the runner to add a definition.")
        return

    questionnaire_keys = list(questionnaires.keys())
    selected_key = st.session_state.get(EDITOR_SELECTED_STATE_KEY)
    if selected_key not in questionnaire_keys:
        selected_key = questionnaire_keys[0]
    if len(questionnaire_keys) > 1:
        selected_key = st.radio(
            "Select questionnaire",
            options=questionnaire_keys,
            index=questionnaire_keys.index(selected_key),
            format_func=lambda key: questionnaires[key].get("label", key),
            help="Choose which questionnaire to edit.",
            horizontal=True,
        )
    else:
        st.caption(
            f"Editing questionnaire: {questionnaires[selected_key].get('label', selected_key)}"
        )

    st.session_state[EDITOR_SELECTED_STATE_KEY] = selected_key
    schema["_active_questionnaire"] = selected_key
    selected_questionnaire = questionnaires[selected_key]
    schema["page"] = selected_questionnaire.setdefault("page", {})
    schema["questions"] = selected_questionnaire.setdefault("questions", [])
    questions = schema.get("questions", [])

    render_page_content_editor(schema)
    st.divider()

    render_question_overview(questions)
    st.divider()

    with st.expander("Live Preview", expanded=False):
        preview_state: Dict[str, Dict[str, Any]] = st.session_state.setdefault(
            PREVIEW_ANSWERS_STATE_KEY,
            {},
        )
        preview_answers = preview_state.setdefault(selected_key, {})
        if not questions:
            st.info("Add questions to see the live preview.")
        else:
            st.caption(
                "Interact with the questions below to preview the questionnaire using the current in-memory schema."
            )
            active_keys = set()
            for question in questions:
                render_preview_question(question, preview_answers, prefix=_state_prefix(schema))
                active_keys.add(question.get("key"))
            for key in list(preview_answers.keys()):
                if key not in active_keys:
                    preview_answers.pop(key, None)
        preview_state[selected_key] = preview_answers
        st.session_state[PREVIEW_ANSWERS_STATE_KEY] = preview_state

    if questions:
        option_labels = [
            f"{question.get('label', question.get('key', '')) or question.get('key', '')} · {question.get('key', '')}"
            for question in questions
        ]
        key_lookup = {
            label: question.get("key")
            for label, question in zip(option_labels, questions)
        }
        selected_label = st.selectbox(
            "Select a question to edit",
            option_labels,
            help="Pick a question from the list above to adjust its settings.",
        )
        selected_key = key_lookup.get(selected_label)
        selected_question = next((q for q in questions if q.get("key") == selected_key), None)
        if selected_question:
            render_question_editor(selected_question, schema)
    else:
        st.info("No questions defined yet. Add a question below.")

    render_add_question(schema)

    with st.expander("View raw schema"):
        _, persistable_preview, _ = schema_for_storage(schema)
        st.json(persistable_preview)

    st.divider()
    st.subheader("Save changes")
    col_draft, col_publish = st.columns(2)
    with col_draft:
        if st.button("Save as Draft"):
            handle_save_draft(schema)
    with col_publish:
        if st.button("Publish", type="primary"):
            handle_publish(schema)


if __name__ == "__main__":
    main()
