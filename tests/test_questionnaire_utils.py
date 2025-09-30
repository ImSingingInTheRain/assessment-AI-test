"""Tests for questionnaire utility helpers."""

import importlib


def test_extract_record_name_prefers_question_value() -> None:
    utils = importlib.import_module("lib.questionnaire_utils")

    questionnaire = {
        "questions": [
            {"key": "record_title", "type": utils.RECORD_NAME_TYPE},
            {"key": "other", "type": "text"},
        ]
    }
    answers = {
        "record_title": "  My record  ",
        utils.RECORD_NAME_FIELD: "Fallback",
    }

    assert utils.extract_record_name(questionnaire, answers) == "My record"


def test_extract_record_name_uses_fallback_field() -> None:
    utils = importlib.import_module("lib.questionnaire_utils")

    questionnaire = {"questions": [{"key": "other", "type": "text"}]}
    answers = {utils.RECORD_NAME_FIELD: "  Backup name  "}

    assert utils.extract_record_name(questionnaire, answers) == "Backup name"


def test_extract_record_name_handles_missing_values() -> None:
    utils = importlib.import_module("lib.questionnaire_utils")

    questionnaire = {"questions": []}
    answers = {}

    assert utils.extract_record_name(questionnaire, answers) == ""


def test_constants_available_while_module_initialises(monkeypatch) -> None:
    """Importing the module exposes constants even before other imports."""

    import sys
    import builtins
    import importlib

    sys.modules.pop("lib.questionnaire_utils", None)

    real_import = builtins.__import__

    def intercept(name, globals=None, locals=None, fromlist=(), level=0):  # type: ignore[override]
        module_name = globals.get("__name__") if globals else None
        if module_name == "lib.questionnaire_utils" and name == "typing":
            module = sys.modules.get("lib.questionnaire_utils")
            assert module is not None
            assert getattr(module, "DEFAULT_QUESTIONNAIRE_KEY", None) == "assessment"
            assert getattr(module, "MULTI_FORM_FLAG", None) == "_multi_form"
            assert getattr(module, "RECORD_NAME_FIELD", None) == "_record_name"
            assert getattr(module, "RECORD_NAME_KEY", None) == "record_name"
            assert getattr(module, "RECORD_NAME_TYPE", None) == "record_name"
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", intercept)

    importlib.import_module("lib.questionnaire_utils")
