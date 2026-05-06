"""GitHub ↔ Asana sync reconciliation tool.

Guides the agent through detecting and optionally fixing state drift between
the two systems.
"""

from strands import tool


@tool
def reconcile_sync(project_name: str, dry_run: bool = True) -> str:
    """Reconcile state between GitHub issues and Asana tasks.

    Matches items via custom field linkage (Asana task has 'github_issue_url'
    custom field, GitHub issue has 'tracked-in-asana' label).

    Args:
        project_name: The project to sync (matches Asana project name)
        dry_run: If True, report drift without fixing. If False, fix drift.

    Returns:
        Instructions for the agent to follow when reconciling state.
    """
    mode = "REPORT ONLY — do not make changes" if dry_run else "FIX — apply corrections"

    return (
        f"Reconcile GitHub ↔ Asana sync for project '{project_name}'.\n"
        f"Mode: {mode}\n\n"
        "Matching convention:\n"
        "- Asana tasks have a 'github_issue_url' custom field linking to GitHub\n"
        "- GitHub issues have a 'tracked-in-asana' label\n\n"
        "Check for:\n"
        "1. **Status drift** — GitHub issue closed but Asana task still incomplete "
        "(or vice versa)\n"
        "2. **Missing links** — GitHub issues with 'tracked-in-asana' label but no "
        "matching Asana task (or vice versa)\n"
        "3. **Orphaned items** — Asana tasks with a github_issue_url pointing to a "
        "deleted or transferred issue\n"
        "4. **Assignee mismatch** — different people assigned in each system\n"
        "5. **Label/tag drift** — GitHub labels don't match Asana tags\n\n"
        "Steps:\n"
        "1. Use asana_list_tasks to get all tasks with github_issue_url set.\n"
        "2. For each, use github_get_issue to check current state.\n"
        "3. Use github_list_issues with label 'tracked-in-asana' to find the "
        "GitHub side.\n"
        "4. Compare and report drift.\n"
        "5. If not dry_run, fix: update Asana task status, add missing labels, "
        "post a comment noting the sync correction."
    )
