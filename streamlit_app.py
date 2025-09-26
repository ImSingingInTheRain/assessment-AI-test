"""Streamlit entrypoint delegating to the Home page."""

from importlib import import_module

import streamlit as st


def main() -> None:
    """Render the Home page when the app entrypoint is loaded."""

    try:
        home_module = import_module("Home")
    except ModuleNotFoundError:
        st.error("Home page module not found.")
        return

    if not hasattr(home_module, "main"):
        st.error("Home page is missing a main() function.")
        return

    home_module.main()


if __name__ == "__main__":
    main()
