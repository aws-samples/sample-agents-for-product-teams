"""Project configuration for the Docwriter agent.

Maps project resources so the agent always knows where to find things.
Loaded at startup and injected into the system prompt.
"""

import os

# GitHub — Docwriter's primary workspace (reads code, opens doc PRs).
# Set `GITHUB_REPO` to `<owner>/<repo>` at runtime.
GITHUB_REPO = os.environ["GITHUB_REPO"]
GITHUB_REPO_OWNER, GITHUB_REPO_NAME = GITHUB_REPO.split("/", 1)

# Asana — reads tasks for feature context, posts doc status.
# Set these at runtime; no defaults.
ASANA_PROJECT_GID = os.environ["ASANA_PROJECT_GID"]
ASANA_PROJECT_NAME = os.environ.get("ASANA_PROJECT_NAME", "")
ASANA_WORKSPACE_GID = os.environ["ASANA_WORKSPACE_GID"]


def build_project_context() -> str:
    """Build a project context block for injection into the system prompt."""
    project_line = f"- Project: {ASANA_PROJECT_NAME}\n" if ASANA_PROJECT_NAME else ""
    return f"""\

## Project Resources

These are YOUR project resources. Use them directly — never ask the user
for repo URLs or project IDs.

GitHub:
- Repository: {GITHUB_REPO}
- Owner: {GITHUB_REPO_OWNER}
- Repo name: {GITHUB_REPO_NAME}

Asana:
{project_line}- Project GID: {ASANA_PROJECT_GID}
- Workspace GID: {ASANA_WORKSPACE_GID}

When opening doc PRs, ALWAYS target repo "{GITHUB_REPO}".
When reading Asana tasks for feature context, use project "{ASANA_PROJECT_GID}".
Do NOT ask the user for these — you already have them.
"""
