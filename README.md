# 🎈 Blank app template

A simple Streamlit app template for you to modify!

[![Open in Streamlit](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://blank-app-template.streamlit.app/)

### How to run it on your own machine

1. Install the requirements

   ```
   $ pip install -r requirements.txt
   ```

2. Run the app

   ```
   $ streamlit run streamlit_app.py
   ```

### Configuring Streamlit Cloud secrets

When deploying on Streamlit Cloud, define the following entries in the **Secrets** manager:

```toml
[secrets]
github_token = "<your-personal-access-token>"
github_repo = "<owner>/<repository>"
github_branch = "<branch-name>"
github_file_path = "<path/to/file.json>"
editor_password_hash = "<sha256-hex-digest>"
```

- **`github_token`** — A GitHub personal access token with the `repo:contents` and `pull_request` scopes so the app can read the form schema and open pull requests with updates.
- **`github_repo`**, **`github_branch`**, **`github_file_path`** — Identify the repository, branch, and file that hold the schema the app reads from (and writes back to).
- **`editor_password_hash`** — The SHA-256 hash of the password required to edit content inside the app.

Generate the password hash with a one-liner such as:

```bash
python -c "import hashlib; print(hashlib.sha256('your-password'.encode()).hexdigest())"
```

For public repositories, the app can read file contents using a token that only has `repo:contents` (even unauthenticated reads are possible for fully public data). Private repositories always require a token; ensure the PAT you provide includes the listed scopes so the app can fetch contents and submit pull requests securely.
