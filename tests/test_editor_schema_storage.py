"""Tests for persisting risks from the editor schema."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from typing import Any, Dict

import streamlit as st

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

MODULE_PATH = REPO_ROOT / "pages" / "02_Editor.py"
SPEC = importlib.util.spec_from_file_location("editor_module", MODULE_PATH)
if SPEC is None or SPEC.loader is None:  # pragma: no cover - defensive
    raise RuntimeError("Could not load editor module for testing.")
EDITOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EDITOR)


def _clear_session_state() -> None:
    """Remove all keys from Streamlit's session state."""

    for key in list(st.session_state.keys()):
        del st.session_state[key]


def _base_schema() -> Dict[str, Any]:
    """Return a minimal questionnaire schema with an active questionnaire."""

    return {
        "_active_questionnaire": "demo",
        "questionnaires": {
            "demo": {
                "key": "demo",
                "label": "Demo",
                "questions": [{"key": "q1"}],
                "risks": [
                    {
                        "key": "r1",
                        "name": "Example risk",
                        "level": "high",
                    }
                ],
            }
        },
        "questions": [{"key": "q1"}],
        "risks": [
            {
                "key": "r1",
                "name": "Example risk",
                "level": "high",
            }
        ],
    }


def test_schema_for_storage_includes_risks_in_flat_payload() -> None:
    """Risks captured in the editor should be persisted when publishing."""

    _clear_session_state()
    schema = _base_schema()

    form_key, persistable, questionnaire = EDITOR.schema_for_storage(schema)

    assert form_key == "demo"
    assert persistable["key"] == "demo"
    assert persistable["risks"] == schema["risks"]
    assert questionnaire["risks"] == schema["risks"]


def test_schema_for_storage_includes_risks_in_nested_payload() -> None:
    """Risks should also be stored when the raw payload nests questionnaire data."""

    _clear_session_state()
    schema = _base_schema()

    st.session_state[EDITOR.FORM_RAW_STATE_KEY] = {
        "demo": {
            "questionnaire": {
                "key": "demo",
                "label": "Demo",
                "page": {},
                "questions": [],
            },
            "meta": {"foo": "bar"},
        }
    }

    form_key, persistable, questionnaire = EDITOR.schema_for_storage(schema)

    assert form_key == "demo"
    assert persistable["questionnaire"]["risks"] == schema["risks"]
    assert persistable["meta"] == {"foo": "bar"}
    assert questionnaire["risks"] == schema["risks"]
