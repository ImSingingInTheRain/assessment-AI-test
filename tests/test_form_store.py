"""Tests for the questionnaire form store helpers."""

from __future__ import annotations

import importlib
import sys
import types


def _reload_form_store():
    """Return a freshly reloaded ``lib.form_store`` module."""

    module = importlib.import_module("lib.form_store")
    return importlib.reload(module)


def test_multi_form_flag_matches_questionnaire_constant():
    """``form_store`` should expose the flag defined in ``questionnaire_utils``."""

    form_store = _reload_form_store()
    questionnaire_utils = importlib.import_module("lib.questionnaire_utils")
    assert form_store.MULTI_FORM_FLAG == questionnaire_utils.MULTI_FORM_FLAG


def test_multi_form_flag_fallback_when_missing(monkeypatch):
    """Fallback to the default constant when the attribute is unavailable."""

    stub_module = types.ModuleType("questionnaire_utils")
    monkeypatch.setitem(sys.modules, "lib.questionnaire_utils", stub_module)

    form_store = _reload_form_store()
    assert form_store.MULTI_FORM_FLAG == "_multi_form"

    # Restore the original module for any subsequent imports during the test run.
    monkeypatch.undo()
    _reload_form_store()
