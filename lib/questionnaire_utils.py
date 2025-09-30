"""Utilities for working with multi-questionnaire schemas."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple

DEFAULT_QUESTIONNAIRE_KEY = "assessment"
EDITOR_SELECTED_STATE_KEY = "editor_selected_questionnaire"
RUNNER_SELECTED_STATE_KEY = "runner_selected_questionnaire"


def _ensure_mapping(value: Any) -> Dict[str, Any]:
    """Return ``value`` if it is a mapping, otherwise an empty dict."""

    return value if isinstance(value, dict) else {}


def _ensure_sequence(value: Any) -> List[Dict[str, Any]]:
    """Return ``value`` if it is a list, otherwise an empty list."""

    return value if isinstance(value, list) else []


def _derive_label(key: str, payload: Dict[str, Any]) -> str:
    """Return a human-friendly label for a questionnaire entry."""

    label = payload.get("label")
    if isinstance(label, str) and label.strip():
        return label.strip()

    page = _ensure_mapping(payload.get("page"))
    title = page.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()

    return key.replace("_", " ").title() if key else "Questionnaire"


def normalize_questionnaires(schema: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Ensure ``schema`` exposes a ``questionnaires`` mapping with defaults."""

    if not isinstance(schema, dict):
        return {}

    questionnaires = schema.get("questionnaires")
    if not isinstance(questionnaires, dict) or not questionnaires:
        page_settings = _ensure_mapping(schema.get("page"))
        questions = _ensure_sequence(schema.get("questions"))
        questionnaires = {
            DEFAULT_QUESTIONNAIRE_KEY: {
                "label": _derive_label(DEFAULT_QUESTIONNAIRE_KEY, {"page": page_settings}),
                "page": page_settings,
                "questions": questions,
            }
        }

    normalised: Dict[str, Dict[str, Any]] = {}
    for key, payload in questionnaires.items():
        entry = _ensure_mapping(payload).copy()
        entry["page"] = _ensure_mapping(entry.get("page"))
        entry["questions"] = _ensure_sequence(entry.get("questions"))
        entry["label"] = _derive_label(key, entry)
        normalised[str(key)] = entry

    schema["questionnaires"] = normalised
    schema.pop("page", None)
    schema.pop("questions", None)
    return normalised


def questionnaire_choices(schema: Dict[str, Any]) -> List[Tuple[str, str]]:
    """Return ``(key, label)`` pairs for all questionnaires in ``schema``."""

    questionnaires = normalize_questionnaires(schema)
    return [(key, entry.get("label", key)) for key, entry in questionnaires.items()]


def get_questionnaire(schema: Dict[str, Any], key: str) -> Dict[str, Any]:
    """Return the questionnaire entry identified by ``key``."""

    questionnaires = normalize_questionnaires(schema)
    if key in questionnaires:
        return questionnaires[key]
    return questionnaires[next(iter(questionnaires))]


def iter_questionnaires(schema: Dict[str, Any]) -> Iterable[Tuple[str, Dict[str, Any]]]:
    """Yield ``(key, questionnaire)`` tuples for the schema."""

    questionnaires = normalize_questionnaires(schema)
    return questionnaires.items()
