"""Project configuration for the Researcher agent.

Maps project resources so the agent always knows where to find things.
Loaded at startup and injected into the system prompt.
"""

import os

# Asana — Researcher's primary (and only) workspace.
# Set these at runtime; no defaults (each deployment targets a different project).
ASANA_PROJECT_GID = os.environ["ASANA_PROJECT_GID"]
ASANA_PROJECT_NAME = os.environ.get("ASANA_PROJECT_NAME", "")
ASANA_WORKSPACE_GID = os.environ["ASANA_WORKSPACE_GID"]


def build_project_context() -> str:
    """Build a project context block for injection into the system prompt."""
    project_line = f"- Project: {ASANA_PROJECT_NAME}\n" if ASANA_PROJECT_NAME else ""
    return f"""\

## Project Resources

These are YOUR project resources. Use them directly — never ask the user
for project IDs.

Asana:
{project_line}- Project GID: {ASANA_PROJECT_GID}
- Workspace GID: {ASANA_WORKSPACE_GID}

When reading or creating tasks, ALWAYS use project "{ASANA_PROJECT_GID}".
Do NOT ask the user for these — you already have them.
"""
