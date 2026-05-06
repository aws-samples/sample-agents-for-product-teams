"""Risk detection tool.

Guides the agent through a structured scan for project risks across both
GitHub and Asana.
"""

from strands import tool


@tool
def detect_risks(project_name: str) -> str:
    """Scan for project risks across GitHub and Asana.

    The agent should query both systems and check for each risk signal below.
    Report findings grouped by severity (critical, warning, info).

    Args:
        project_name: The project to scan (matches Asana project name)

    Returns:
        Instructions for the agent to follow when scanning for risks.
    """
    return (
        f"Run a risk detection scan for project '{project_name}'.\n\n"
        "Check for these signals:\n\n"
        "CRITICAL:\n"
        "- Asana tasks past due date with no recent activity\n"
        "- Milestones < 50% complete with < 25% time remaining\n"
        "- Issues labeled 'blocked' with no activity in 3+ days\n\n"
        "WARNING:\n"
        "- GitHub issues with no assignee, older than 3 days\n"
        "- PRs open > 48 hours with no review\n"
        "- Asana tasks assigned but not started, due within 3 days\n"
        "- PRs with failing CI checks and no recent commits\n\n"
        "INFO:\n"
        "- Issues opened this week with no labels\n"
        "- Asana tasks missing acceptance criteria in description\n"
        "- PRs with merge conflicts\n\n"
        "Steps:\n"
        "1. Use asana_list_tasks with filters for overdue, upcoming due dates.\n"
        "2. Use github_list_issues for unassigned, blocked, unlabeled issues.\n"
        "3. Use github_list_prs for stale PRs, failing checks, conflicts.\n"
        "4. Group findings by severity. For each, include:\n"
        "   - What: the specific item (link to issue/task)\n"
        "   - Why: why this is a risk\n"
        "   - Recommended action: what a human should do\n"
        "5. If no risks found, say so explicitly."
    )
