"""Utilities for working with stored questionnaire submission files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Sequence, Tuple


def delete_submission_files(
    submission_id: str,
    directory: Path,
    *,
    skip_paths: Sequence[Path] | None = None,
) -> Tuple[List[Path], List[Path]]:
    """Delete files in ``directory`` matching ``submission_id``.

    Parameters
    ----------
    submission_id:
        The identifier associated with the submission.
    directory:
        The directory where submission JSON files are stored.
    skip_paths:
        Optional paths that should not be deleted. These are typically files that
        have already been removed (to avoid repeated work) or ones that should be
        preserved.

    Returns
    -------
    Tuple[List[Path], List[Path]]
        Two lists containing the paths that were successfully removed and the
        ones that could not be deleted because of an ``OSError``.
    """

    normalized_id = str(submission_id or "").strip()
    if not normalized_id or not directory.exists():
        return [], []

    skipped: set[Path] = set()
    if skip_paths:
        for item in skip_paths:
            try:
                skipped.add(Path(item).resolve())
            except OSError:
                skipped.add(Path(item))

    removed: List[Path] = []
    failed: List[Path] = []

    for candidate in directory.glob("*.json"):
        try:
            resolved = candidate.resolve()
        except OSError:
            resolved = candidate
        if resolved in skipped:
            continue

        matches = candidate.stem == normalized_id
        if not matches:
            try:
                with candidate.open("r", encoding="utf-8") as handle:
                    payload = json.load(handle)
            except (OSError, json.JSONDecodeError):
                continue
            candidate_id = str(payload.get("id") or "").strip()
            matches = candidate_id == normalized_id

        if not matches:
            continue

        try:
            candidate.unlink()
        except OSError:
            failed.append(candidate)
        else:
            removed.append(candidate)

    return removed, failed


__all__ = ["delete_submission_files"]
