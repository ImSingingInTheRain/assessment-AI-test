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
editor_password_hash = "<sha256-hex-digest>"

[github]
token = "<your-personal-access-token>"
repo = "<owner>/<repository>"
branch = "<branch-name>"  # optional, defaults to "main"
path = "<path/to/file.json>"  # optional, defaults to "form_schema.json"
```

- **`github.token`** — A GitHub personal access token with the `repo:contents` and `pull_request` scopes so the app can read the form schema and open pull requests with updates.
- **`github.repo`**, **`github.branch`**, **`github.path`** — Identify the repository, branch, and file that hold the schema the app reads from (and writes back to). Only `repo` is required; the other keys fall back to sensible defaults when omitted.
- **`editor_password_hash`** — The SHA-256 hash of the password required to edit content inside the app.

### Troubleshooting “GitHub not configured”

If you see a banner stating that GitHub is not configured when you try to publish or save a draft, double-check the following:

1. **Secrets formatting** — The `[github]` table must contain at least `token` and `repo`. Optional values include `branch`, `path`, and `api_url`. The `editor_password_hash` entry belongs at the **top level** of your `secrets.toml`, not inside the `[github]` block.
2. **Personal access token scopes** — The token needs `repo` access (or, for public repositories, the more granular `contents` scope plus `pull_request`). Without the correct scopes GitHub API calls will fail.
3. **Streamlit restart** — Secrets are cached in deployed apps. After editing them, stop and restart the Streamlit session so the new values are picked up.

When secrets are missing the editor falls back to saving `form_schema.json` locally, which triggers the “GitHub not configured” message you are seeing. Once the required entries are present the editor will push commits and pull requests to the configured repository instead of writing to the local file.

For backwards compatibility the application also understands the previous flat keys (`github_token`, `github_repo`, `github_branch`, `github_file_path`, and `github_api_url`). Streamlit Cloud merges entries defined at the top level with nested sections, so you can continue using the older naming convention if you already have it saved.

Generate the password hash with a one-liner such as:

```bash
python -c "import hashlib; print(hashlib.sha256('your-password'.encode()).hexdigest())"
```

For public repositories, the app can read file contents using a token that only has `repo:contents` (even unauthenticated reads are possible for fully public data). Private repositories always require a token; ensure the PAT you provide includes the listed scopes so the app can fetch contents and submit pull requests securely.
