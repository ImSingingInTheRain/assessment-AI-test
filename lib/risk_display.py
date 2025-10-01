"""Helpers for presenting risk assignments consistently across pages."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any, Dict, List, Tuple


RISK_LEVEL_EMOJIS: Dict[str, Tuple[str, str]] = {
    "limited": ("🟢", "Limited"),
    "high": ("🟠", "High"),
    "unacceptable": ("🔴", "Unacceptable"),
}

RISK_BADGE_CLASSES: Dict[str, str] = {
    "limited": "app-risk-badge--limited",
    "high": "app-risk-badge--high",
    "unacceptable": "app-risk-badge--unacceptable",
}


def _clean_text(value: Any) -> str:
    """Return ``value`` converted to a trimmed string."""

    if isinstance(value, str):
        return value.strip()
    if value is None:
        return ""
    return str(value).strip()


def _ensure_sequence(value: Any) -> Sequence[Any]:
    """Return a safe sequence representation of ``value``."""

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return value
    if value is None:
        return []
    return [value]


def normalise_risk_entries(risks: Any) -> List[Dict[str, Any]]:
    """Return risk entries in a consistent, presentation-friendly form."""

    normalised: List[Dict[str, Any]] = []
    for entry in _ensure_sequence(risks):
        if not isinstance(entry, dict):
            continue

        key = _clean_text(entry.get("key"))
        name = _clean_text(entry.get("name"))
        level_raw = _clean_text(entry.get("level"))
        level = level_raw.lower()
        level_label = level_raw.title() if level_raw else "Unknown"
        system_id = _clean_text(entry.get("system_id"))
        mitigations = [
            _clean_text(item)
            for item in _ensure_sequence(entry.get("mitigations"))
            if _clean_text(item)
        ]

        display_name = name or key or "Risk"
        record: Dict[str, Any] = {
            "name": display_name,
            "level": level,
            "level_label": level_label,
        }
        if key:
            record["key"] = key
        if system_id:
            record["system_id"] = system_id
        if mitigations:
            record["mitigations"] = mitigations

        normalised.append(record)

    return normalised


def aggregate_risks_for_system(
    assessments: Iterable[Dict[str, Any]], system_id: str
) -> List[Dict[str, Any]]:
    """Return unique risks assigned to ``system_id`` from ``assessments``."""

    target_id = _clean_text(system_id)
    aggregated: Dict[Tuple[str, str, str], Dict[str, Any]] = {}

    for assessment in assessments:
        if not isinstance(assessment, dict):
            continue

        assessment_system = _clean_text(assessment.get("system_id"))
        for risk in normalise_risk_entries(assessment.get("risks")):
            risk_system = _clean_text(risk.get("system_id")) or assessment_system or target_id
            if target_id and risk_system and risk_system != target_id:
                continue

            dedup_key = (
                risk.get("key") or risk.get("name"),
                risk.get("level", ""),
                risk_system,
            )

            risk_copy = dict(risk)
            if risk_system:
                risk_copy["system_id"] = risk_system

            aggregated.setdefault(dedup_key, risk_copy)

    return list(aggregated.values())


def risks_to_markdown(risks: Iterable[Dict[str, Any]]) -> str:
    """Return a newline-separated summary of ``risks`` with colour icons."""

    lines: List[str] = []
    for risk in normalise_risk_entries(list(risks)):
        emoji, default_label = RISK_LEVEL_EMOJIS.get(
            risk.get("level", ""), ("⚪", "Unknown")
        )
        label = risk.get("level_label") or default_label
        lines.append(f"{emoji} {label} · {risk.get('name')}")

    return "\n".join(lines)


def risks_to_badges_html(risks: Iterable[Dict[str, Any]]) -> str:
    """Return HTML markup representing ``risks`` as styled badges."""

    entries = normalise_risk_entries(list(risks))
    if not entries:
        return ""

    badges: List[str] = []
    for risk in entries:
        css_class = RISK_BADGE_CLASSES.get(
            risk.get("level", ""), "app-risk-badge--unknown"
        )
        level_label = risk.get("level_label") or "Unknown"
        name = risk.get("name") or "Risk"
        badge = (
            "<span class='app-risk-badge {css}'>"
            "<span class='app-risk-badge__level'>{level}</span>"
            "<span class='app-risk-badge__name'>{name}</span>"
            "</span>"
        ).format(css=css_class, level=level_label, name=name)
        badges.append(badge)

    return "<div class='app-risk-badges'>" + "".join(badges) + "</div>"


__all__ = [
    "aggregate_risks_for_system",
    "normalise_risk_entries",
    "risks_to_badges_html",
    "risks_to_markdown",
]
