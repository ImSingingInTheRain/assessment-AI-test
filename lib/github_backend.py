"""Utilities for interacting with GitHub's Contents API."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests


@dataclass
class GitHubBackend:
    """GitHub Contents API wrapper for reading and writing JSON files."""

    token: str
    repo: str
    path: str
    branch: str = "main"
    api_url: str = "https://api.github.com"

    def _headers(self) -> Dict[str, str]:
        """Build request headers for the GitHub API."""

        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        }

    def _url(self) -> str:
        """Construct the contents URL for the configured repository."""

        return f"{self.api_url.rstrip('/')}/repos/{self.repo}/contents/{self.path}"

    def _get_file_sha(self) -> Optional[str]:
        """Retrieve the SHA of the target file if it exists."""

        response = requests.get(
            self._url(),
            headers=self._headers(),
            params={"ref": self.branch},
            timeout=10,
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        payload = response.json()
        return payload.get("sha")

    def get_file_sha(self) -> Optional[str]:
        """Public wrapper for retrieving the SHA of the target file."""

        return self._get_file_sha()

    def read_json(self) -> Dict[str, Any]:
        """Read a JSON file from GitHub and return its contents."""

        response = requests.get(
            self._url(),
            headers=self._headers(),
            params={"ref": self.branch},
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
        content = payload.get("content", "")
        encoding = payload.get("encoding", "base64")
        if encoding != "base64":
            raise ValueError(f"Unsupported encoding: {encoding}")

        decoded = base64.b64decode(content).decode("utf-8")
        return json.loads(decoded)

    def write_json(self, data: Dict[str, Any], message: str) -> Dict[str, Any]:
        """Write JSON data to GitHub using the Contents API."""

        payload: Dict[str, Any] = {
            "message": message,
            "branch": self.branch,
            "content": base64.b64encode(json.dumps(data, indent=2).encode("utf-8")).decode("utf-8"),
        }

        sha = self._get_file_sha()
        if sha:
            payload["sha"] = sha

        response = requests.put(
            self._url(),
            headers=self._headers(),
            json=payload,
            timeout=10,
        )
        response.raise_for_status()
        return response.json()


def _headers(cfg: Dict[str, Any]) -> Dict[str, str]:
    """Construct standard GitHub API headers."""

    return {
        "Authorization": f"Bearer {cfg['token']}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
    }


def _api_url(cfg: Dict[str, Any]) -> str:
    """Normalise the configured API URL."""

    return cfg.get("api_url", "https://api.github.com").rstrip("/")


def create_branch(cfg: Dict[str, Any], new_branch: str) -> Dict[str, Any]:
    """Create ``new_branch`` from the default branch's HEAD if needed."""

    repo = cfg["repo"]
    base_branch = cfg.get("branch", "main")
    api_url = _api_url(cfg)
    headers = _headers(cfg)

    # Return existing branch details if it already exists.
    ref_url = f"{api_url}/repos/{repo}/git/ref/heads/{new_branch}"
    response = requests.get(ref_url, headers=headers, timeout=10)
    if response.status_code == 200:
        return response.json()
    if response.status_code not in {404}:
        response.raise_for_status()

    base_ref_url = f"{api_url}/repos/{repo}/git/ref/heads/{base_branch}"
    base_response = requests.get(base_ref_url, headers=headers, timeout=10)
    base_response.raise_for_status()
    base_payload = base_response.json()
    base_sha = base_payload.get("object", {}).get("sha")
    if not base_sha:
        raise ValueError("Unable to determine base branch SHA.")

    payload = {"ref": f"refs/heads/{new_branch}", "sha": base_sha}
    create_url = f"{api_url}/repos/{repo}/git/refs"
    create_response = requests.post(create_url, headers=headers, json=payload, timeout=10)
    # If the branch was created by another process concurrently, fetch it.
    if create_response.status_code == 422:
        conflict = requests.get(ref_url, headers=headers, timeout=10)
        conflict.raise_for_status()
        return conflict.json()
    create_response.raise_for_status()
    return create_response.json()


def put_file(
    cfg: Dict[str, Any],
    new_json: Dict[str, Any],
    sha: Optional[str],
    message: str,
    branch: Optional[str] = None,
) -> Dict[str, Any]:
    """Write ``new_json`` to the configured path using the Contents API."""

    repo = cfg["repo"]
    path = cfg["path"]
    api_url = _api_url(cfg)
    headers = _headers(cfg)
    target_branch = branch or cfg.get("branch", "main")

    payload: Dict[str, Any] = {
        "message": message,
        "branch": target_branch,
        "content": base64.b64encode(json.dumps(new_json, indent=2).encode("utf-8")).decode("utf-8"),
    }
    if sha:
        payload["sha"] = sha

    url = f"{api_url}/repos/{repo}/contents/{path}"
    response = requests.put(url, headers=headers, json=payload, timeout=10)
    response.raise_for_status()
    return response.json()


def ensure_pr(
    cfg: Dict[str, Any],
    head_branch: str,
    title: str,
    body: str = "",
) -> Dict[str, Any]:
    """Ensure a pull request exists for ``head_branch``."""

    repo = cfg["repo"]
    base_branch = cfg.get("branch", "main")
    api_url = _api_url(cfg)
    headers = _headers(cfg)
    owner = repo.split("/")[0]

    pulls_url = f"{api_url}/repos/{repo}/pulls"
    params = {"head": f"{owner}:{head_branch}", "state": "open"}
    response = requests.get(pulls_url, headers=headers, params=params, timeout=10)
    response.raise_for_status()
    existing = response.json()
    if existing:
        return existing[0]

    payload = {"title": title, "head": head_branch, "base": base_branch, "body": body}
    create_response = requests.post(pulls_url, headers=headers, json=payload, timeout=10)
    create_response.raise_for_status()
    return create_response.json()

