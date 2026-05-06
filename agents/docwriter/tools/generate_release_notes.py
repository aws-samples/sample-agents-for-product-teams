"""Release notes generation tool.

Structured task tool — returns a prompt that guides the agent through
listing merged PRs and producing categorized, user-facing release notes.
"""

from strands import tool


@tool
def generate_release_notes(
    since_tag: str = "",
    since_date: str = "",
    audience: str = "end_user",
) -> str:
    """Generate release notes from merged PRs.

    The agent should use this tool when asked to draft a changelog or
    release notes. It returns a structured workflow.

    Args:
        since_tag: Git tag to start from (e.g. 'v2.3.0'). Takes precedence
            over since_date.
        since_date: ISO date to start from (e.g. '2025-01-15'). Used if
            since_tag is empty.
        audience: 'end_user' (what changed for them) or 'developer'
            (technical changes).

    Returns:
        Instructions for the agent to follow when generating release notes.
    """
    if since_tag:
        range_desc = f"since tag '{since_tag}'"
        range_step = (
            f"1. Use github_list_tags or github_get_release to find the date of '{since_tag}'.\n"
            "2. List all PRs merged after that date using github_list_prs with state=closed.\n"
        )
    elif since_date:
        range_desc = f"since {since_date}"
        range_step = (
            f"1. List all PRs merged after {since_date} using github_list_prs with state=closed.\n"
        )
    else:
        range_desc = "for the latest release"
        range_step = (
            "1. Find the two most recent tags using github_list_tags.\n"
            "2. List all PRs merged between those two tags.\n"
        )

    audience_guidance = {
        "end_user": (
            "Write for end users. Translate developer language into user impact:\n"
            "  - 'Refactored query engine' → 'Search results now load faster'\n"
            "  - 'Fixed race condition in session handler' → 'Fixed intermittent logout issue'\n"
            "  - 'Added Elasticsearch 8.x support' → 'Improved search relevance and performance'\n"
            "Skip purely internal changes (CI, refactoring) unless they affect behavior."
        ),
        "developer": (
            "Write for developers. Include technical details:\n"
            "  - What changed in the code and why\n"
            "  - Migration steps for breaking changes\n"
            "  - New configuration options\n"
            "  - Deprecation notices"
        ),
    }

    return (
        f"Generate release notes {range_desc}.\n"
        f"Audience: {audience}\n\n"
        f"{audience_guidance.get(audience, audience_guidance['end_user'])}\n\n"
        f"Steps:\n"
        f"{range_step}"
        "3. Read each PR's title, description, and labels.\n"
        "4. Categorize each as one of:\n"
        "   - New Feature\n"
        "   - Improvement\n"
        "   - Bug Fix\n"
        "   - Breaking Change\n"
        "   - Internal (skip for end_user audience)\n"
        "5. Write a one-line summary for each, tailored to the audience.\n"
        "6. Put Breaking Changes at the top with migration instructions.\n"
        "7. Format as markdown with category headers.\n"
        "8. Include the version number and date at the top."
    )
