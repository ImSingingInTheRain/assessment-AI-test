"""Authenticated editor page for managing questionnaire questions."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

import streamlit as st

from Home import load_schema
from lib.github_backend import GitHubBackend, create_branch, ensure_pr, put_file

SCHEMA_STATE_KEY = "editor_schema"
DRAFT_BRANCH_STATE_KEY = "editor_draft_branch"
QUESTION_TYPES = ["single", "multiselect", "bool", "text"]


def get_github_config() -> Optional[Dict[str, Any]]:
    """Return GitHub configuration from Streamlit secrets if available."""

    secrets = st.secrets.get("github", {})  # type: ignore[arg-type]
    token = secrets.get("token")
    repo = secrets.get("repo")
    path = secrets.get("path", "form_schema.json")
    branch = secrets.get("branch", "main")
    api_url = secrets.get("api_url", "https://api.github.com")

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
        backend = GitHubBackend(
            token=config["token"],
            repo=config["repo"],
            path=config["path"],
            branch=branch,
            api_url=config.get("api_url", "https://api.github.com"),
        )
        sha = backend.get_file_sha()
        put_file(
            config,
            schema,
            sha,
            message=f"chore: save questionnaire draft ({branch})",
            branch=branch,
        )
        pr = ensure_pr(
            config,
            branch,
            title="Draft: Update questionnaire schema",
            body="Automated draft update from the questionnaire editor.",
        )
    except Exception as exc:  # pylint: disable=broad-except
        st.error(f"Failed to save draft: {exc}")
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
    try:
        if config is not None:
            backend = GitHubBackend(
                token=config["token"],
                repo=config["repo"],
                path=config["path"],
                branch=config.get("branch", "main"),
                api_url=config.get("api_url", "https://api.github.com"),
            )
            sha = backend.get_file_sha()
            put_file(
                config,
                schema,
                sha,
                message="chore: publish questionnaire schema",
                branch=config.get("branch", "main"),
            )
            st.success("Schema published to the main branch.")
        else:
            with open("form_schema.json", "w", encoding="utf-8") as schema_file:
                json.dump(schema, schema_file, indent=2)
            st.info("GitHub is not configured; schema saved locally instead.")
    except Exception as exc:  # pylint: disable=broad-except
        st.error(f"Failed to publish schema: {exc}")
        return

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
