"""Project configuration for the Adr agent.

Unlike the other agents, Adr's scope is GitHub-only and its per-repo
behavior (which ADR directory to read, which statuses count) comes from
`.sdlc-agents/adr.yaml` at read time, not from startup config.
"""

import os

# GitHub — Adr's only platform. Set `GITHUB_REPO` to `<owner>/<repo>` at runtime.
GITHUB_REPO = os.environ["GITHUB_REPO"]
GITHUB_REPO_OWNER, GITHUB_REPO_NAME = GITHUB_REPO.split("/", 1)

# ADR discovery — search these paths in order when the repo has no
# `.sdlc-agents/adr.yaml` override. First hit wins.
DEFAULT_ADR_DIRS = ["docs/adrs", "adrs", "ADRs", "docs/decisions", "architecture/decisions"]

# Matching thresholds — overridable per repo via config file
DEFAULT_CONFIDENCE_THRESHOLD = 0.65
DEFAULT_REQUIRE_STATUS = "accepted"  # or "any"


def build_project_context() -> str:
    """Build a project context block for injection into the system prompt."""
    return f"""\

## Project Resources

GitHub:
- Repository: {GITHUB_REPO}
- Owner: {GITHUB_REPO_OWNER}
- Repo name: {GITHUB_REPO_NAME}

ADR discovery (in order):
- `.sdlc-agents/adr.yaml` → `adr_dir` key (if the file exists)
- Otherwise try these paths and use the first one that exists:
  {", ".join(DEFAULT_ADR_DIRS)}

If no ADR directory is found, post a single "no ADRs found" comment and stop.
Do not try to operate without ADRs.
"""
