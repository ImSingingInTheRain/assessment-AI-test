from __future__ import annotations

import importlib


def test_normalise_risk_entries_standardises_fields() -> None:
    module = importlib.import_module("lib.risk_display")

    entries = module.normalise_risk_entries(
        {"name": "Privacy", "level": "High", "system_id": "sys-1"}
    )

    assert entries == [
        {
            "name": "Privacy",
            "level": "high",
            "level_label": "High",
            "system_id": "sys-1",
        }
    ]


def test_aggregate_risks_for_system_filters_and_deduplicates() -> None:
    module = importlib.import_module("lib.risk_display")

    assessments = [
        {"system_id": "alpha", "risks": [{"key": "r1", "level": "high", "name": "One"}]},
        {"system_id": "beta", "risks": [{"key": "r1", "level": "high", "name": "One"}]},
        {"system_id": "alpha", "risks": [{"key": "r2", "level": "limited", "name": "Two"}]},
        {"system_id": "alpha", "risks": [{"key": "r1", "level": "high", "name": "One"}]},
    ]

    aggregated = module.aggregate_risks_for_system(assessments, "alpha")

    assert {risk["key"] for risk in aggregated} == {"r1", "r2"}
    assert {risk.get("system_id") for risk in aggregated} == {"alpha"}


def test_risks_to_markdown_adds_colour_icons() -> None:
    module = importlib.import_module("lib.risk_display")

    text = module.risks_to_markdown(
        [
            {
                "name": "Critical",
                "level": "unacceptable",
                "level_label": "Unacceptable",
            }
        ]
    )

    assert "🔴" in text
    assert "Critical" in text
