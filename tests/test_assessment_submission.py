"""Tests for storing assessment submissions to GitHub."""

from __future__ import annotations

from types import SimpleNamespace


def test_store_assessment_submission_success(monkeypatch):
    """Assessment submissions should be sent to GitHub with a generated identifier."""

    import importlib

    questionnaire = importlib.import_module("pages.01_Questionnaire")

    captured = {}

    class DummyBackend:
        def __init__(
            self,
            *,
            token: str,
            repo: str,
            path: str,
            branch: str = "main",
            api_url: str = "https://api.github.com",
        ) -> None:
            captured["init"] = {
                "token": token,
                "repo": repo,
                "path": path,
                "branch": branch,
                "api_url": api_url,
            }

        def write_json(self, data, message):
            captured["payload"] = data
            captured["message"] = message
            return {"ok": True}

    settings = {
        "token": "secret-token",
        "repo": "example/repo",
        "branch": "main",
        "api_url": "https://enterprise.example/api/v3",
        "assessment_submissions_path": "assessments/{submission_id}.json",
    }

    dummy_uuid = SimpleNamespace(hex="def456")

    monkeypatch.setattr(questionnaire, "GitHubBackend", DummyBackend)
    monkeypatch.setattr(questionnaire, "_github_settings", lambda: settings)
    monkeypatch.setattr(questionnaire.uuid, "uuid4", lambda: dummy_uuid)

    errors = []
    monkeypatch.setattr(questionnaire.st, "error", lambda message: errors.append(message))

    submission_id = questionnaire.store_assessment_submission({"assessment-score": 10})

    assert submission_id == "def456"
    assert captured["init"]["path"] == "assessments/def456.json"
    assert captured["payload"]["id"] == "def456"
    assert captured["payload"]["answers"] == {"assessment-score": 10}
    assert "def456" in captured["message"]
    assert errors == []


def test_store_assessment_submission_assigns_risks(monkeypatch):
    """Triggered risks should be stored with the assessment submission."""

    import importlib

    questionnaire = importlib.import_module("pages.01_Questionnaire")

    captured = {}

    class DummyBackend:
        def __init__(
            self,
            *,
            token: str,
            repo: str,
            path: str,
            branch: str = "main",
            api_url: str = "https://api.github.com",
        ) -> None:
            captured["init"] = {
                "token": token,
                "repo": repo,
                "path": path,
                "branch": branch,
                "api_url": api_url,
            }

        def write_json(self, data, message):
            captured["payload"] = data
            captured["message"] = message
            return {"ok": True}

    settings = {
        "token": "secret-token",
        "repo": "example/repo",
        "branch": "main",
        "api_url": "https://enterprise.example/api/v3",
        "assessment_submissions_path": "assessments/{submission_id}.json",
    }

    dummy_uuid = SimpleNamespace(hex="abc999")

    sample_schema = {
        "questionnaires": {
            "assessment": {
                "questions": [],
                "risks": [
                    {
                        "key": "demo-risk",
                        "name": "Demonstration risk",
                        "level": "high",
                        "logic": {
                            "field": "flag",
                            "operator": "equals",
                            "value": "yes",
                        },
                        "mitigations": ["Document controls"],
                    }
                ],
            }
        }
    }

    monkeypatch.setattr(questionnaire, "GitHubBackend", DummyBackend)
    monkeypatch.setattr(questionnaire, "_github_settings", lambda: settings)
    monkeypatch.setattr(questionnaire.uuid, "uuid4", lambda: dummy_uuid)
    monkeypatch.setattr(questionnaire, "load_schema", lambda: sample_schema)

    errors = []
    monkeypatch.setattr(questionnaire.st, "error", lambda message: errors.append(message))

    answers = {"flag": "yes", "related-sytem": "sys-123"}
    submission_id = questionnaire.store_assessment_submission(dict(answers))

    assert submission_id == "abc999"
    payload = captured.get("payload")
    assert payload is not None
    assert payload["related_system_id"] == "sys-123"
    assert payload["answers"].get("related-system") == "sys-123"
    assert "related-sytem" not in payload["answers"]
    assert payload["risks"] == [
        {
            "key": "demo-risk",
            "name": "Demonstration risk",
            "level": "high",
            "mitigations": ["Document controls"],
            "system_id": "sys-123",
        }
    ]
    assert errors == []


def test_store_assessment_submission_supports_list_logic(monkeypatch):
    """Legacy risk logic defined as lists should still trigger risks."""

    import importlib

    questionnaire = importlib.import_module("pages.01_Questionnaire")

    captured = {}

    class DummyBackend:
        def __init__(
            self,
            *,
            token: str,
            repo: str,
            path: str,
            branch: str = "main",
            api_url: str = "https://api.github.com",
        ) -> None:
            captured["init"] = {
                "token": token,
                "repo": repo,
                "path": path,
                "branch": branch,
                "api_url": api_url,
            }

        def write_json(self, data, message):
            captured["payload"] = data
            captured["message"] = message
            return {"ok": True}

    settings = {
        "token": "secret-token",
        "repo": "example/repo",
        "branch": "main",
        "api_url": "https://enterprise.example/api/v3",
        "assessment_submissions_path": "assessments/{submission_id}.json",
    }

    dummy_uuid = SimpleNamespace(hex="abc123")

    legacy_schema = {
        "questionnaires": {
            "assessment": {
                "questions": [],
                "risks": [
                    {
                        "key": "legacy-risk",
                        "name": "Legacy risk",
                        "level": "limited",
                        "logic": [
                            {
                                "field": "legacy",
                                "operator": "equals",
                                "value": "trigger",
                            }
                        ],
                    }
                ],
            }
        }
    }

    monkeypatch.setattr(questionnaire, "GitHubBackend", DummyBackend)
    monkeypatch.setattr(questionnaire, "_github_settings", lambda: settings)
    monkeypatch.setattr(questionnaire.uuid, "uuid4", lambda: dummy_uuid)
    monkeypatch.setattr(questionnaire, "load_schema", lambda: legacy_schema)

    errors = []
    monkeypatch.setattr(questionnaire.st, "error", lambda message: errors.append(message))

    submission_id = questionnaire.store_assessment_submission({"legacy": "trigger"})

    assert submission_id == "abc123"
    payload = captured.get("payload")
    assert payload is not None
    assert payload.get("risks") == [
        {
            "key": "legacy-risk",
            "name": "Legacy risk",
            "level": "limited",
        }
    ]
    assert errors == []


def test_store_assessment_submission_missing_github(monkeypatch):
    """If GitHub configuration is missing the assessment should not be stored."""

    import importlib

    questionnaire = importlib.import_module("pages.01_Questionnaire")

    monkeypatch.setattr(questionnaire, "_github_settings", lambda: {})

    errors = []
    monkeypatch.setattr(questionnaire.st, "error", lambda message: errors.append(message))

    submission_id = questionnaire.store_assessment_submission({"assessment-score": 5})

    assert submission_id is None
    assert errors, "Expected an error message when GitHub is not configured"
