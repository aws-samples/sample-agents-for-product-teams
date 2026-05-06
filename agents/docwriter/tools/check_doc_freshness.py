"""Documentation freshness checking tool.

Structured task tool — guides the agent through comparing documentation
against recent code changes to identify stale or drifted docs.
"""

from strands import tool


@tool
def check_doc_freshness(
    doc_path: str = "",
    project: str = "",
) -> str:
    """Check if existing documentation is stale relative to the code.

    The agent should use this tool when asked to audit doc freshness
    or when a code PR merges that might affect docs.

    Args:
        doc_path: Specific doc file to check (e.g. 'docs/api/auth.md').
            Empty means check all docs.
        project: Limit to docs related to a specific feature or project.

    Returns:
        Instructions for the agent to follow when checking freshness.
    """
    if doc_path:
        target = f"Check freshness of '{doc_path}'."
        scan_step = (
            f"1. Use github_get_file to read '{doc_path}'.\n"
            "2. Identify what code/feature this doc covers.\n"
            "3. Use github_list_commits or github_list_prs to find recent changes "
            "to the related code files.\n"
        )
    elif project:
        target = f"Check freshness of all docs related to '{project}'."
        scan_step = (
            "1. Use github_list_files to enumerate docs/ directory.\n"
            f"2. Filter to docs that relate to '{project}' (by path or content).\n"
            "3. For each doc, identify the related code and check for recent changes.\n"
        )
    else:
        target = "Check freshness of all documentation."
        scan_step = (
            "1. Use github_list_files to enumerate the full docs/ directory.\n"
            "2. For each doc file, identify what code/feature it documents.\n"
            "3. Compare the doc's last commit date against the related code's last commit date.\n"
        )

    return (
        f"{target}\n\n"
        f"Steps:\n"
        f"{scan_step}"
        "4. For each doc, classify freshness:\n"
        "   - STALE: code behavior changed since doc was last updated. "
        "Doc is likely WRONG.\n"
        "   - DRIFT: minor code changes (renamed params, new optional fields). "
        "Doc is imprecise but not wrong.\n"
        "   - CURRENT: no relevant code changes since doc was last updated.\n"
        "5. For STALE docs: open a doc PR with fixes, or file an issue if the "
        "change is too complex to auto-fix.\n"
        "6. For DRIFT docs: file a low-priority issue.\n"
        "7. Generate a freshness report:\n"
        "   - Total docs checked\n"
        "   - Count by status (STALE / DRIFT / CURRENT)\n"
        "   - List of STALE docs with what changed and when\n"
        "   - PRs or issues created"
    )
