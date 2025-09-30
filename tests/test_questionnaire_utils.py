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
