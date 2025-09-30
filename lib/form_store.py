"""Helpers for working with questionnaire form schema files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Tuple

from lib.questionnaire_utils import MULTI_FORM_FLAG

FORM_SCHEMA_FILENAME = "form_schema.json"
SCHEMAS_ROOT = Path("form_schemas")
LEGACY_SCHEMA_PATH = Path("form_schema.json")


def _ensure_mapping(value: Any) -> Dict[str, Any]:
    """Return ``value`` if it is a mapping, otherwise an empty dict."""

    return dict(value) if isinstance(value, Mapping) else {}


def _ensure_list(value: Any) -> List[Any]:
    """Return ``value`` if it is a list, otherwise an empty list."""

    return list(value) if isinstance(value, list) else []


def discover_local_forms() -> Dict[str, Path]:
    """Return a mapping of ``form_key -> path`` for local schema files."""

    forms: Dict[str, Path] = {}
    if SCHEMAS_ROOT.exists():
        for entry in sorted(SCHEMAS_ROOT.iterdir()):
            if not entry.is_dir():
                continue
            schema_path = entry / FORM_SCHEMA_FILENAME
            if schema_path.exists():
                forms[entry.name] = schema_path
    if not forms and LEGACY_SCHEMA_PATH.exists():
        forms["default"] = LEGACY_SCHEMA_PATH
    return forms


def _normalise_form_payload(form_key: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Convert the raw payload into the questionnaire entry structure."""

    base = _ensure_mapping(payload.get("questionnaire")) or payload.copy()
    entry = _ensure_mapping(base)
    entry.setdefault("key", form_key)
    entry["label"] = str(entry.get("label") or form_key).strip() or form_key
    page_settings = _ensure_mapping(entry.get("page"))
    entry["page"] = page_settings
    entry["questions"] = _ensure_list(entry.get("questions"))

    meta = payload.get("meta")
    if isinstance(meta, Mapping):
        entry["meta"] = dict(meta)
    elif "meta" in entry and not isinstance(entry.get("meta"), Mapping):
        entry.pop("meta", None)

    return entry


def load_local_forms() -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Path], Dict[str, Dict[str, Any]]]:
    """Load all local forms returning normalised entries and raw payloads."""

    forms: Dict[str, Dict[str, Any]] = {}
    sources: Dict[str, Path] = {}
    raw_payloads: Dict[str, Dict[str, Any]] = {}

    for form_key, path in discover_local_forms().items():
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        raw_payloads[form_key] = payload
        forms[form_key] = _normalise_form_payload(form_key, payload)
        sources[form_key] = path

    return forms, sources, raw_payloads


def combine_forms(forms: Mapping[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Return a schema structure that exposes ``questionnaires`` mapping."""

    combined = {"questionnaires": {key: dict(value) for key, value in forms.items()}}
    combined[MULTI_FORM_FLAG] = True
    return combined


def load_combined_schema() -> Tuple[Dict[str, Any], Dict[str, Path], Dict[str, Dict[str, Any]]]:
    """Return the combined schema along with source metadata."""

    forms, sources, raw_payloads = load_local_forms()
    return combine_forms(forms), sources, raw_payloads


def ensure_form_directory(form_key: str) -> Path:
    """Ensure the directory for ``form_key`` exists and return it."""

    target_dir = SCHEMAS_ROOT / form_key
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir


def local_form_path(form_key: str, sources: Mapping[str, Path]) -> Path:
    """Return the on-disk path for ``form_key`` using known sources."""

    if form_key in sources:
        return sources[form_key]
    return ensure_form_directory(form_key) / FORM_SCHEMA_FILENAME


def available_form_keys() -> List[str]:
    """Return the list of known form identifiers."""

    return list(discover_local_forms().keys())


def resolve_remote_form_path(base_path: str, form_key: str) -> str:
    """Return the remote path for ``form_key`` using ``base_path`` template."""

    if "{form_key}" in base_path:
        return base_path.format(form_key=form_key)
    if "{questionnaire}" in base_path:
        return base_path.format(questionnaire=form_key)
    if "{form}" in base_path:
        return base_path.format(form=form_key)
    if base_path.endswith(".json"):
        return base_path
    return f"{base_path.rstrip('/')}/{form_key}/{FORM_SCHEMA_FILENAME}"


def forms_from_payloads(payloads: Mapping[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Normalise already-loaded payloads into questionnaire entries."""

    return {key: _normalise_form_payload(key, value) for key, value in payloads.items()}
