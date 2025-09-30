"""Tests for storing system registration submissions to GitHub."""

from __future__ import annotations

from types import SimpleNamespace


def test_store_system_registration_submission_success(monkeypatch):
    """Submissions should be sent to GitHub with a generated identifier."""

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
        "system_registration_submissions_path": "registrations/{submission_id}.json",
    }

    dummy_uuid = SimpleNamespace(hex="abc123")

    monkeypatch.setattr(questionnaire, "GitHubBackend", DummyBackend)
    monkeypatch.setattr(questionnaire, "_github_settings", lambda: settings)
    monkeypatch.setattr(questionnaire.uuid, "uuid4", lambda: dummy_uuid)

    errors = []
    monkeypatch.setattr(questionnaire.st, "error", lambda message: errors.append(message))

    submission_id = questionnaire.store_system_registration_submission({"system-type": "api"})

    assert submission_id == "abc123"
    assert captured["init"]["path"] == "registrations/abc123.json"
    assert captured["payload"]["id"] == "abc123"
    assert captured["payload"]["answers"] == {"system-type": "api"}
    assert "abc123" in captured["message"]
    assert errors == []


def test_store_system_registration_submission_missing_github(monkeypatch):
    """If GitHub configuration is missing the submission should not be stored."""

    import importlib

    questionnaire = importlib.import_module("pages.01_Questionnaire")

    monkeypatch.setattr(questionnaire, "_github_settings", lambda: {})

    errors = []
    monkeypatch.setattr(questionnaire.st, "error", lambda message: errors.append(message))

    submission_id = questionnaire.store_system_registration_submission({"system-type": "api"})

    assert submission_id is None
    assert errors, "Expected an error message when GitHub is not configured"
