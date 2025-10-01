"""Utilities for applying a shared visual identity across Streamlit pages."""

from __future__ import annotations

from typing import Any, Optional

import streamlit as st


_THEME_CSS = """
<style>
:root {
    --app-accent: #5145CD;
    --app-accent-dark: #4338CA;
    --app-accent-soft: #E8E7FB;
    --app-surface: rgba(255, 255, 255, 0.92);
    --app-surface-strong: #FFFFFF;
    --app-border: rgba(81, 69, 205, 0.25);
    --app-shadow: 0 18px 40px rgba(15, 23, 42, 0.08);
    --app-text: #1F2933;
    --app-muted: #52606D;
    --app-success: #059669;
    --app-warning: #B45309;
    --app-error: #DC2626;
}

html, body {
    font-family: "Inter", "Segoe UI", system-ui, -apple-system, sans-serif;
    color: var(--app-text);
}

[data-testid="stAppViewContainer"] {
    background: radial-gradient(circle at top right, #F4F2FF 0%, #EEF2FF 35%, #FFFFFF 75%);
}

[data-testid="stHeader"] {
    background: rgba(255, 255, 255, 0.7);
    backdrop-filter: blur(18px);
    border-bottom: 1px solid rgba(81, 69, 205, 0.1);
}

[data-testid="stSidebar"] {
    background: rgba(255, 255, 255, 0.85);
    backdrop-filter: blur(18px);
    border-right: 1px solid rgba(81, 69, 205, 0.12);
}

.block-container {
    padding-top: 2.5rem;
    padding-bottom: 4rem;
}

.app-header {
    display: flex;
    align-items: center;
    gap: 1.5rem;
    padding: 1.75rem 2rem;
    background: var(--app-surface);
    border-radius: 1.75rem;
    border: 1px solid rgba(81, 69, 205, 0.18);
    box-shadow: var(--app-shadow);
    margin-bottom: 2rem;
}

.app-header__icon {
    font-size: 2.75rem;
    line-height: 1;
}

.app-header__title {
    margin: 0;
    font-size: 2.25rem;
    font-weight: 700;
    color: var(--app-text);
}

.app-header__subtitle {
    margin: 0.25rem 0 0 0;
    font-size: 1.05rem;
    color: var(--app-muted);
}

.app-card {
    background: var(--app-surface-strong);
    border-radius: 1.5rem;
    border: 1px solid rgba(81, 69, 205, 0.12);
    box-shadow: 0 16px 36px rgba(15, 23, 42, 0.07);
    padding: 1.75rem 2rem;
    margin-bottom: 1.5rem;
}

.app-card__title {
    margin: 0 0 1rem 0;
    font-size: 1.3rem;
    font-weight: 600;
    color: var(--app-text);
}

.app-card p {
    color: var(--app-muted);
    font-size: 1.02rem;
    line-height: 1.55;
    margin-bottom: 0.85rem;
}

.app-muted {
    color: var(--app-muted);
}

.app-card--compact {
    padding: 1.5rem;
}

.app-card--table {
    padding: 1.5rem 1.5rem 0.75rem 1.5rem;
}

.app-card--table [data-testid="stDataFrameContainer"] {
    border-radius: 1rem;
    overflow: hidden;
}

.app-card--table [data-testid="stStyledDataFrame"] table {
    border-collapse: collapse !important;
}

.app-card--table [data-testid="stStyledDataFrame"] tbody tr {
    border-bottom: 1px solid rgba(81, 69, 205, 0.08);
}

.app-card--table [data-testid="stStyledDataFrame"] tbody tr:hover {
    background: rgba(81, 69, 205, 0.05);
}

.app-checklist {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 0.65rem;
}

.app-checklist li {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.75rem 1rem;
    border-radius: 999px;
    background: var(--app-accent-soft);
    color: var(--app-text);
    font-weight: 600;
}

.app-checklist__badge {
    width: 2rem;
    height: 2rem;
    border-radius: 999px;
    background: var(--app-accent);
    color: white;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-weight: 700;
    font-size: 0.95rem;
}

.app-question-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 1rem;
}

.app-question-list__item {
    padding: 1rem 1.25rem;
    border-radius: 1rem;
    background: rgba(81, 69, 205, 0.05);
    border: 1px solid rgba(81, 69, 205, 0.08);
}

.app-question-list__meta {
    font-size: 0.9rem;
    color: var(--app-muted);
    margin-top: 0.35rem;
}

.app-question-list pre {
    background: rgba(15, 23, 42, 0.85);
    color: #f9fafb;
    padding: 0.75rem 1rem;
    border-radius: 0.75rem;
    overflow-x: auto;
}

.app-risk-badges {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    margin-top: 0.35rem;
}

.app-risk-badge {
    display: inline-flex;
    flex-wrap: nowrap;
    align-items: center;
    gap: 0.45rem;
    padding: 0.35rem 0.9rem;
    border-radius: 999px;
    font-weight: 600;
    font-size: 0.85rem;
    letter-spacing: 0.01em;
    color: white;
    background: var(--app-muted);
    box-shadow: 0 6px 16px rgba(15, 23, 42, 0.12);
}

.app-risk-badge__level {
    text-transform: uppercase;
    font-size: 0.72rem;
    letter-spacing: 0.08em;
    opacity: 0.9;
}

.app-risk-badge__name {
    font-size: 0.9rem;
}

.app-risk-badge--limited {
    background: var(--app-success);
}

.app-risk-badge--high {
    background: var(--app-warning);
}

.app-risk-badge--unacceptable {
    background: var(--app-error);
}

.app-risk-badge--unknown {
    background: var(--app-muted);
}

.stButton>button,
button[kind="primary"],
button[data-baseweb="button"] {
    border-radius: 999px !important;
    font-weight: 600 !important;
    padding: 0.6rem 1.6rem !important;
    border: none !important;
    background: var(--app-accent) !important;
    color: #fff !important;
    box-shadow: 0 10px 30px rgba(81, 69, 205, 0.25) !important;
}

.stButton>button:hover,
button[kind="primary"]:hover,
button[data-baseweb="button"]:hover {
    background: var(--app-accent-dark) !important;
    box-shadow: 0 12px 32px rgba(81, 69, 205, 0.35) !important;
}

.stMetric {
    background: var(--app-surface);
    border-radius: 1.25rem;
    padding: 1.2rem 1.4rem;
    border: 1px solid rgba(81, 69, 205, 0.1);
    box-shadow: 0 10px 26px rgba(15, 23, 42, 0.06);
}

.stMetric label {
    color: var(--app-muted) !important;
    font-weight: 600 !important;
}

.stAlert {
    border-radius: 1.25rem;
    border: 1px solid rgba(81, 69, 205, 0.18);
}

.questionnaire-intro {
    background: linear-gradient(135deg, rgba(81, 69, 205, 0.12), rgba(129, 212, 250, 0.18));
    padding: 1.75rem;
    border-radius: 1.5rem;
    border: 1px solid rgba(81, 69, 205, 0.18);
    margin-bottom: 1.5rem;
}

.questionnaire-intro h2 {
    margin: 0 0 0.75rem 0;
}

.questionnaire-intro p {
    margin-bottom: 0.75rem;
    color: var(--app-muted);
}


.question-block {
    margin-bottom: 1.5rem;
    padding: 1.5rem;
    border-radius: 1.25rem;
    background: var(--app-surface-strong);
    border: 1px solid rgba(81, 69, 205, 0.15);
    box-shadow: 0 16px 32px rgba(15, 23, 42, 0.08);
}

.question-block__header {
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
}

.question-block__step {
    font-size: 0.78rem;
    font-weight: 700;
    color: var(--app-muted);
    text-transform: uppercase;
    letter-spacing: 0.08em;
}

.question-block__title {
    margin: 0;
    font-size: 1.18rem;
    font-weight: 600;
    color: var(--app-text);
    line-height: 1.4;
}

.question-block__title sup {
    color: var(--app-accent);
    margin-left: 0.2rem;
    font-size: 0.85rem;
}

.question-block__help {
    margin: 0.25rem 0 0 0;
    color: var(--app-muted);
    font-size: 0.95rem;
}

[data-testid="stExpander"] {
    border-radius: 1.5rem;
    border: 1px solid rgba(81, 69, 205, 0.12);
    background: rgba(255, 255, 255, 0.92);
    box-shadow: 0 12px 26px rgba(15, 23, 42, 0.06);
}

[data-testid="stExpander"] [data-testid="stMarkdown"] p {
    color: var(--app-muted);
}

form[data-testid="stForm"] {
    padding: 1.5rem;
    border-radius: 1.5rem;
    border: 1px solid rgba(81, 69, 205, 0.12);
    background: rgba(255, 255, 255, 0.9);
    box-shadow: 0 18px 36px rgba(15, 23, 42, 0.08);
    margin-bottom: 1.75rem;
}

form[data-testid="stForm"] .stMarkdown p {
    margin-bottom: 0.5rem;
}

.app-section-card {
    padding: 1.5rem;
    border-radius: 1.5rem;
    border: 1px solid rgba(81, 69, 205, 0.12);
    background: rgba(255, 255, 255, 0.86);
    box-shadow: 0 18px 38px rgba(15, 23, 42, 0.08);
    margin-bottom: 1.5rem;
}

.app-section-card > h3 {
    margin-top: 0;
    margin-bottom: 0.85rem;
    font-size: 1.15rem;
}

.app-section-card__description {
    margin-top: -0.35rem;
    margin-bottom: 1.2rem;
    color: var(--app-muted);
}
</style>
"""


def apply_app_theme(page_title: str, page_icon: Optional[str] = None) -> None:
    """Set up consistent page configuration and inject the shared CSS theme."""

    st.set_page_config(
        page_title=page_title,
        page_icon=page_icon,
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(_THEME_CSS, unsafe_allow_html=True)


def page_header(
    title: str,
    subtitle: Optional[str] = None,
    icon: Optional[str] = None,
    *,
    container: Optional[Any] = None,
) -> None:
    """Render a hero-style header with a title, subtitle, and optional icon."""

    icon_markup = f"<span class='app-header__icon'>{icon}</span>" if icon else ""
    subtitle_markup = (
        f"<p class='app-header__subtitle'>{subtitle}</p>" if subtitle else ""
    )
    target = container.markdown if container is not None else st.markdown
    target(
        f"""
        <div class="app-header">
            {icon_markup}
            <div>
                <h1 class="app-header__title">{title}</h1>
                {subtitle_markup}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_card(content: str, title: Optional[str] = None, *, compact: bool = False, table: bool = False) -> None:
    """Render pre-formatted HTML content inside a themed surface."""

    classes = ["app-card"]
    if compact:
        classes.append("app-card--compact")
    if table:
        classes.append("app-card--table")
    class_attr = " ".join(classes)
    heading = f"<h3 class='app-card__title'>{title}</h3>" if title else ""
    st.markdown(
        f"<div class='{class_attr}'>{heading}{content}</div>",
        unsafe_allow_html=True,
    )
