"""Default values shared between the questionnaire and editor."""

from __future__ import annotations

from typing import List

DEFAULT_PAGE_TITLE = "Questionnaire"
DEFAULT_INTRO_HEADING = "👋 Welcome!"
DEFAULT_INTRO_PARAGRAPHS: tuple[str, ...] = (
    "Please answer the questions below so we can tailor the experience to you.",
    "Questions may appear or disappear automatically depending on your responses.",
)
DEFAULT_SUBMIT_LABEL = "Submit questionnaire"
DEFAULT_SUBMIT_SUCCESS_MESSAGE = "Responses captured. Persistence will be wired via GitHub."
DEFAULT_DEBUG_LABEL = "Debug: current answers"
DEFAULT_SHOW_INTRODUCTION = True
DEFAULT_SHOW_DEBUG = True
DEFAULT_SHOW_ANSWERS_SUMMARY = True


def intro_paragraphs_list() -> List[str]:
    """Return a mutable list of the default introduction paragraphs."""

    return list(DEFAULT_INTRO_PARAGRAPHS)
