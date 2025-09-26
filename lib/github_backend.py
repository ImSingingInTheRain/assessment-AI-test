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

