"""Parse GitHub issue-closing references from PR bodies.

GitHub recognizes `Closes #N`, `Fixes #N`, `Resolves #N`, and
cross-repo variants like `Closes owner/repo#N`. This tool extracts the
issue numbers in the same repo so the agent can pull their `adr-*` labels.
"""

import re

from strands import tool

# GitHub's recognized closing keywords — case insensitive.
# See https://docs.github.com/en/issues/tracking-your-work-with-issues/linking-a-pull-request-to-an-issue
_PATTERN = re.compile(
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+(?:(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+))?#(?P<num>\d+)\b",
    re.IGNORECASE,
)


@tool
def find_linked_issues(pr_body: str, repo_owner: str = "", repo_name: str = "") -> list[int]:
    """Extract issue numbers closed by a PR, scoped to the PR's own repo.

    Cross-repo references (`owner/repo#N`) are included only when they
    match the PR's own repo.

    Args:
        pr_body: The PR's body text (usually markdown).
        repo_owner: The PR's repo owner (for cross-repo disambiguation).
        repo_name: The PR's repo name.

    Returns:
        List of issue numbers in the current repo. Empty list if none.
    """
    if not pr_body:
        return []

    found: list[int] = []
    for m in _PATTERN.finditer(pr_body):
        owner = m.group("owner")
        repo = m.group("repo")
        num = int(m.group("num"))

        if owner and repo:
            # Cross-repo reference — include only if it matches our repo
            if owner == repo_owner and repo == repo_name:
                found.append(num)
        else:
            # Bare #N — always same-repo
            found.append(num)

    # dedupe preserving order
    seen = set()
    deduped = []
    for n in found:
        if n not in seen:
            seen.add(n)
            deduped.append(n)
    return deduped
