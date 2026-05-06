"""Project configuration for the Workitems agent.

Maps project resources so the agent always knows where to find things.
Loaded at startup and injected into the system prompt.
"""

import os

# Asana — set these at runtime (deploy workflow / .env / AgentCore env config).
# No defaults: each deployment targets a different project.
ASANA_PROJECT_GID = os.environ["ASANA_PROJECT_GID"]
ASANA_PROJECT_NAME = os.environ.get("ASANA_PROJECT_NAME", "")
ASANA_WORKSPACE_GID = os.environ["ASANA_WORKSPACE_GID"]

# GitHub — set `GITHUB_REPO` to `<owner>/<repo>` at runtime.
GITHUB_REPO = os.environ["GITHUB_REPO"]
GITHUB_REPO_OWNER, GITHUB_REPO_NAME = GITHUB_REPO.split("/", 1)


def build_project_context() -> str:
    """Build a project context block for injection into the system prompt."""
    project_line = f"- Project: {ASANA_PROJECT_NAME}\n" if ASANA_PROJECT_NAME else ""
    return f"""\

## Project Resources

These are YOUR project resources. Use them directly — never ask the user
for repo URLs or project IDs.

Asana:
{project_line}- Project GID: {ASANA_PROJECT_GID}
- Workspace GID: {ASANA_WORKSPACE_GID}

GitHub:
- Repository: {GITHUB_REPO}
- Owner: {GITHUB_REPO_OWNER}
- Repo name: {GITHUB_REPO_NAME}

When creating GitHub issues, ALWAYS use repo "{GITHUB_REPO}".
When reading Asana tasks, ALWAYS use project "{ASANA_PROJECT_GID}".
Do NOT ask the user for these — you already have them.
"""
