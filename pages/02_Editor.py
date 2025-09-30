"""Authenticated editor page for managing questionnaire questions."""

from __future__ import annotations

import hashlib
import hmac
import json
from copy import deepcopy
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

import streamlit as st

from Home import load_schema
from lib.github_backend import GitHubBackend, create_branch, ensure_pr, put_file

SCHEMA_STATE_KEY = "editor_schema"
SCHEMA_SHA_STATE_KEY = "editor_schema_sha"
DRAFT_BRANCH_STATE_KEY = "editor_draft_branch"
QUESTION_TYPES = ["single", "multiselect", "bool", "text"]
SHOW_IF_BUILDER_STATE_KEY = "editor_show_if_builder"
LIST_OPERATORS = {"in", "not_in", "contains_any", "contains_all", "one_of"}
PREVIEW_ANSWERS_STATE_KEY = "editor_preview_answers"


def _secrets_dict(name: str) -> Dict[str, Any]:
    """Return a mapping stored under ``name`` in Streamlit secrets."""

    value = st.secrets.get(name, {})  # type: ignore[arg-type]
    if isinstance(value, dict):
        return dict(value)
    return {}


def get_github_config() -> Optional[Dict[str, Any]]:
    """Return GitHub configuration from Streamlit secrets if available."""

    secrets = _secrets_dict("github")
    token = secrets.get("token")
    repo = secrets.get("repo")
    path = secrets.get("path", "form_schema.json")
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


def get_backend() -> Optional[GitHubBackend]:
    """Instantiate a GitHub backend using Streamlit secrets if available."""

    config = get_github_config()
    if config is not None:
        return GitHubBackend(
            token=config["token"],
            repo=config["repo"],
            path=config["path"],
            branch=config.get("branch", "main"),
            api_url=config.get("api_url", "https://api.github.com"),
        )
    return None


def get_schema() -> Dict[str, Any]:
    """Fetch the current schema for editing, caching in session state."""

    if SCHEMA_STATE_KEY not in st.session_state:
        schema = load_schema() or {"questions": []}
        st.session_state[SCHEMA_STATE_KEY] = schema
    if SCHEMA_SHA_STATE_KEY not in st.session_state:
        backend = get_backend()
        if backend is not None:
            try:
                st.session_state[SCHEMA_SHA_STATE_KEY] = backend.get_file_sha()
            except Exception as exc:  # pylint: disable=broad-except
                st.error(f"Could not load schema metadata from GitHub: {exc}")
                st.session_state[SCHEMA_SHA_STATE_KEY] = None
    return st.session_state[SCHEMA_STATE_KEY]


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


def sync_show_if_builder_state(schema: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Ensure the rule builder session state mirrors the current schema."""

    builder_state: Dict[str, Dict[str, Any]] = st.session_state.setdefault(
        SHOW_IF_BUILDER_STATE_KEY,
        {},
    )
    valid_keys = set()
    for question in schema.get("questions", []):
        key = question.get("key")
        if not key:
            continue
        valid_keys.add(key)
        show_if = question.get("show_if") or {}
        existing_state = builder_state.get(key, {})
        active_bucket = existing_state.get("active", "all")
        if show_if:
            bucket_from_schema = next(iter(show_if.keys()))
            if bucket_from_schema in {"all", "any"}:
                active_bucket = bucket_from_schema
        builder_state[key] = {
            "all": deepcopy(show_if.get("all", existing_state.get("all", []))),
            "any": deepcopy(show_if.get("any", existing_state.get("any", []))),
            "active": active_bucket if active_bucket in {"all", "any"} else "all",
        }

    for key in list(builder_state.keys()):
        if key not in valid_keys:
            builder_state.pop(key)

    return builder_state


def render_show_if_builder(schema: Dict[str, Any]) -> None:
    """Render a basic rule builder UI for question visibility."""

    st.subheader("Show rule builder")

    questions = schema.get("questions", [])
    if not questions:
        st.info("Add questions to configure show_if rules.")
        return

    builder_state = sync_show_if_builder_state(schema)

    question_keys = [question.get("key") for question in questions if question.get("key")]
    if not question_keys:
        st.info("Questions require keys before rules can be created.")
        return

    target_key = st.selectbox(
        "Select the question to control visibility for",
        options=question_keys,
        key="show_if_target_question",
    )

    target_question = next((q for q in questions if q.get("key") == target_key), None)
    if target_question is None:
        return

    target_state = builder_state.setdefault(
        target_key,
        {"all": [], "any": [], "active": "all"},
    )

    bucket_key = f"show_if_bucket_{target_key}"
    st.session_state.setdefault(bucket_key, target_state.get("active", "all"))
    selected_bucket = st.radio(
        "Combine clauses using",
        options=["all", "any"],
        index=["all", "any"].index(st.session_state[bucket_key]),
        key=bucket_key,
        horizontal=True,
        help="Choose whether every clause must match or any single clause is sufficient.",
    )
    target_state["active"] = selected_bucket

    target_state.setdefault("all", [])
    target_state.setdefault("any", [])
    target_state.setdefault(selected_bucket, [])

    active_clauses = target_state.get(selected_bucket, [])
    if active_clauses:
        target_question["show_if"] = {selected_bucket: deepcopy(active_clauses)}
    else:
        target_question.pop("show_if", None)
    st.session_state[SCHEMA_STATE_KEY] = schema

    clause_question_options = [key for key in question_keys if key != target_key] or question_keys
    clause_field = st.selectbox(
        "Clause question",
        options=clause_question_options,
        key=f"show_if_clause_field_{target_key}",
    )
    operator = st.text_input(
        "Operator",
        key=f"show_if_operator_{target_key}",
        help="Examples: equals, in, is_true, contains_any",
    )
    value_input = st.text_input(
        "Value",
        key=f"show_if_value_{target_key}",
        help="For list operators provide comma-separated values. Leave blank for operators without a value.",
    )

    if st.button("Add clause", key=f"show_if_add_clause_{target_key}"):
        if not clause_field:
            st.error("Select a question to reference in the clause.")
        elif not operator.strip():
            st.error("Operator is required.")
        else:
            trimmed_operator = operator.strip()
            values = [segment.strip() for segment in value_input.split(",") if segment.strip()]

            clause: Dict[str, Any] = {
                "field": clause_field,
                "operator": trimmed_operator,
            }
            if trimmed_operator in LIST_OPERATORS or len(values) > 1:
                if values:
                    clause["value"] = values
            elif values:
                clause["value"] = values[0]

            target_state[selected_bucket].append(clause)
            if target_state[selected_bucket]:
                target_question["show_if"] = {
                    selected_bucket: deepcopy(target_state[selected_bucket])
                }
            else:
                target_question.pop("show_if", None)

            st.session_state[SCHEMA_STATE_KEY] = schema
            st.session_state[f"show_if_value_{target_key}"] = ""
            st.session_state[f"show_if_operator_{target_key}"] = ""
            st.success("Clause added.")

    if target_state[selected_bucket]:
        st.markdown("**Current clauses**")
        for idx, clause in enumerate(target_state[selected_bucket]):
            clause_col, remove_col = st.columns([4, 1])
            with clause_col:
                st.json(clause)
            with remove_col:
                if st.button("Remove", key=f"remove_clause_{target_key}_{selected_bucket}_{idx}"):
                    target_state[selected_bucket].pop(idx)
                    if target_state[selected_bucket]:
                        target_question["show_if"] = {
                            selected_bucket: deepcopy(target_state[selected_bucket])
                        }
                    else:
                        target_question.pop("show_if", None)
                    st.session_state[SCHEMA_STATE_KEY] = schema
                    st.experimental_rerun()

    clear_col, _ = st.columns([1, 3])
    with clear_col:
        if st.button("Clear rule", key=f"clear_show_if_{target_key}"):
            target_state["all"] = []
            target_state["any"] = []
            target_question.pop("show_if", None)
            st.session_state[SCHEMA_STATE_KEY] = schema
            st.success("Show rule cleared.")
            st.experimental_rerun()

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


def render_preview_question(question: Dict[str, Any], answers: Dict[str, Any]) -> None:
    """Render an individual question widget for the live preview."""

    question_key = question["key"]
    widget_key = f"preview_question_{question_key}"

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
    elif question_type == "text":
        default_text = "" if default_value is None else str(default_value)
        text_value = st.text_input(
            label,
            value=default_text,
            key=widget_key,
            placeholder=question.get("placeholder"),
            help=help_text,
        )
        answers[question_key] = text_value
    else:
        st.warning(f"Unsupported question type: {question_type}")

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

    errors = validate_schema(schema)
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
        path=config["path"],
        branch=branch,
        api_url=config.get("api_url", "https://api.github.com"),
    )

    try:
        sha = backend.get_file_sha()
    except Exception as exc:  # pylint: disable=broad-except
        st.error(f"Could not read draft schema from GitHub: {exc}")
        return

    try:
        put_file(
            config,
            schema,
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

    errors = validate_schema(schema)
    if errors:
        for error in errors:
            st.error(error)
        return

    config = get_github_config()
    if config is not None:
        backend = GitHubBackend(
            token=config["token"],
            repo=config["repo"],
            path=config["path"],
            branch=config.get("branch", "main"),
            api_url=config.get("api_url", "https://api.github.com"),
        )

        stored_sha = st.session_state.get(SCHEMA_SHA_STATE_KEY)
        try:
            latest_sha = backend.get_file_sha()
        except Exception as exc:  # pylint: disable=broad-except
            st.error(f"Could not read schema from GitHub: {exc}")
            return

        if stored_sha is not None and stored_sha != latest_sha:
            st.error("Schema changed upstream—refresh and retry.")
            st.session_state[SCHEMA_SHA_STATE_KEY] = latest_sha
            return

        try:
            response = put_file(
                config,
                schema,
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
        st.session_state[SCHEMA_SHA_STATE_KEY] = published_sha or latest_sha
        st.success("Schema published to the main branch.")
    else:
        try:
            with open("form_schema.json", "w", encoding="utf-8") as schema_file:
                json.dump(schema, schema_file, indent=2)
        except OSError as exc:
            st.error(f"Could not save schema locally: {exc}")
            return
        st.info("GitHub is not configured; schema saved locally instead.")
        st.session_state[SCHEMA_SHA_STATE_KEY] = None

    st.cache_data.clear()
    load_schema.clear()
    st.session_state[SCHEMA_STATE_KEY] = schema
    st.session_state.pop(DRAFT_BRANCH_STATE_KEY, None)


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

            st.session_state[SCHEMA_STATE_KEY] = schema
            st.success("Question updated. Use Publish or Save as Draft to persist changes.")

        if delete_requested:
            schema["questions"] = [
                q for q in schema.get("questions", []) if q.get("key") != question.get("key")
            ]
            st.session_state[SCHEMA_STATE_KEY] = schema
            st.warning("Question removed. Use Publish or Save as Draft to persist changes.")


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
            st.session_state[SCHEMA_STATE_KEY] = schema
            st.success("Question added. Use Publish or Save as Draft to persist changes.")


def main() -> None:
    """Render the questionnaire editor page."""

    require_authentication()

    st.title("Questionnaire editor")
    st.caption("Authentication is assumed to have already succeeded.")

    schema = get_schema()
    questions = schema.get("questions", [])

    with st.expander("Live Preview", expanded=False):
        preview_answers: Dict[str, Any] = st.session_state.setdefault(
            PREVIEW_ANSWERS_STATE_KEY,
            {},
        )
        if not questions:
            st.info("Add questions to see the live preview.")
        else:
            st.caption(
                "Interact with the questions below to preview the questionnaire using the current in-memory schema."
            )
            active_keys = set()
            for question in questions:
                render_preview_question(question, preview_answers)
                active_keys.add(question.get("key"))
            for key in list(preview_answers.keys()):
                if key not in active_keys:
                    preview_answers.pop(key, None)
        st.session_state[PREVIEW_ANSWERS_STATE_KEY] = preview_answers

    if questions:
        question_keys = [question["key"] for question in questions]
        selected_key = st.selectbox("Select a question to edit", question_keys)
        selected_question = next((q for q in questions if q.get("key") == selected_key), None)
        if selected_question:
            render_question_editor(selected_question, schema)
    else:
        st.info("No questions defined yet. Add a question below.")

    render_show_if_builder(schema)

    render_add_question(schema)

    with st.expander("View raw schema"):
        st.json(schema)

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
