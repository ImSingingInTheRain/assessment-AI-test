"""Tests for rule builder group helper utilities."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

MODULE_PATH = REPO_ROOT / "pages" / "02_Editor.py"
SPEC = importlib.util.spec_from_file_location("editor_module", MODULE_PATH)
if SPEC is None or SPEC.loader is None:  # pragma: no cover - defensive
    raise RuntimeError("Could not load editor module for testing.")
EDITOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EDITOR)


def test_ensure_group_labels_assigns_defaults_and_uniqueness() -> None:
    groups = [
        {"mode": "all", "clauses": [], "connector": None},
        {"mode": "all", "clauses": [], "connector": "all", "label": ""},
        {"mode": "any", "clauses": [], "connector": "any", "label": "Custom"},
        {"mode": "any", "clauses": [], "connector": "all", "label": "Custom"},
    ]

    EDITOR._ensure_group_labels(groups)  # type: ignore[attr-defined]

    labels = [group["label"] for group in groups]
    assert labels[0] == "Group 1"
    assert labels[1] == "Group 2"
    assert labels[2] == "Custom"
    assert labels[3] != "Custom"
    assert len(set(labels)) == len(labels)


def test_generate_group_label_skips_existing_names() -> None:
    groups = [
        {"label": "Team"},
        {"label": "Group 3"},
    ]

    label = EDITOR._generate_group_label(groups)  # type: ignore[attr-defined]
    assert label.startswith("Group 3")
    assert label not in {group["label"] for group in groups}


@pytest.mark.parametrize(
    "existing,expected",
    [
        ([{"label": "Group 1"}], "Group 2"),
        ([{"label": "Group 1"}, {"label": "Group 2"}, {"label": "Group 3"}], "Group 4"),
    ],
)
def test_generate_group_label_defaults(existing, expected) -> None:
    label = EDITOR._generate_group_label(existing)  # type: ignore[attr-defined]
    assert label == expected
