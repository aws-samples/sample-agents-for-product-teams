"""Documentation gap detection tool.

Structured task tool — guides the agent through scanning the codebase
for features that lack documentation, and filing issues for gaps found.
"""

from strands import tool


@tool
def detect_doc_gaps(
    scope: str = "full",
    section: str = "",
) -> str:
    """Scan the codebase for undocumented features and file issues.

    The agent should use this tool when asked to find missing docs.
    It returns a structured workflow for discovery and issue creation.

    Args:
        scope: What to scan — 'full' (everything), 'api' (endpoints only),
            'config' (setup and configuration), or 'ui' (user features).
        section: Limit scan to a specific directory or module. Empty means
            scan the entire repo.

    Returns:
        Instructions for the agent to follow when detecting doc gaps.
    """
    scope_guidance = {
        "full": (
            "Scan for ALL gap types: API endpoints, configuration options, "
            "and documented features."
        ),
        "api": (
            "Focus on API endpoints only. Compare route definitions against "
            "API reference docs."
        ),
        "config": (
            "Focus on configuration and setup. Check: environment variables, "
            "config files, deployment steps, and infrastructure setup."
        ),
        "ui": (
            "Focus on user-facing features. Check: documented workflows, "
            "feature guides, and user-facing functionality."
        ),
    }

    section_filter = ""
    if section:
        section_filter = f"\nScope limited to: {section}\n"

    return (
        f"Detect documentation gaps.\n"
        f"Scope: {scope}\n"
        f"{scope_guidance.get(scope, scope_guidance['full'])}\n"
        f"{section_filter}\n"
        "Steps:\n"
        "1. Use github_list_files to enumerate the docs/ directory — build an "
        "inventory of what documentation exists.\n"
        "2. Scan source code for documentable items:\n"
        "   - API: search for route definitions (github_search_code)\n"
        "   - Config: search for env var reads, config file schemas\n"
        "   - Features: read README, check for feature descriptions\n"
        "3. Cross-reference: for each documentable item, check if a "
        "corresponding doc exists.\n"
        "4. For each gap found, classify severity:\n"
        "   - HIGH: public API endpoint with no reference docs\n"
        "   - MEDIUM: configuration option with no setup guide entry\n"
        "   - LOW: internal module with no README\n"
        "5. File a GitHub issue for each HIGH and MEDIUM gap. Include:\n"
        "   - What's missing\n"
        "   - Where the code lives\n"
        "   - Suggested doc structure\n"
        "   - Label: 'documentation', 'docwriter-detected'\n"
        "6. Post a summary report listing all gaps found and issues created."
    )
