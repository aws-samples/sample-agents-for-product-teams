"""Status report generation tool.

This is a structured task tool — when the agent calls it, the tool returns a
prompt that guides the agent through multi-step data gathering and synthesis.
The actual GitHub/Asana queries happen via Gateway MCP tools that the agent
already has access to.
"""

from strands import tool


@tool
def generate_status_report(
    project_name: str,
    audience: str = "team",
    format: str = "markdown",
) -> str:
    """Generate a project status report by pulling data from GitHub and Asana.

    This tool structures the report generation process. The agent should:
    1. Query GitHub for PRs merged, issues opened/closed since last report
    2. Query Asana for task progress, section distribution, due dates
    3. Synthesize findings into a report tailored to the audience

    Args:
        project_name: The project to report on (matches Asana project name)
        audience: One of 'team', 'leadership', 'stakeholder' — controls detail level
        format: Output format — 'markdown', 'slack', 'asana'

    Returns:
        Instructions for the agent to follow when generating the report.
    """
    audience_guidance = {
        "team": (
            "Include: what shipped (PRs merged), what's in progress (open PRs), "
            "what's blocked, what needs review. Be specific — link to issues and PRs."
        ),
        "leadership": (
            "Include: milestone progress (% complete), key deliverables shipped, "
            "risks and mitigations, next week's priorities. Keep it concise — "
            "bullet points, no implementation detail."
        ),
        "stakeholder": (
            "Include: features delivered (user-facing language), timeline status "
            "(on track / at risk / behind), upcoming milestones. No technical detail."
        ),
    }

    format_guidance = {
        "markdown": "Use markdown with headers, bullet points, and tables.",
        "slack": "Use Slack Block Kit formatting. Keep under 3000 chars.",
        "asana": "Use Asana-compatible rich text. Post as a project status update.",
    }

    return (
        f"Generate a status report for project '{project_name}'.\n\n"
        f"Audience: {audience}\n"
        f"{audience_guidance.get(audience, audience_guidance['team'])}\n\n"
        f"Format: {format}\n"
        f"{format_guidance.get(format, format_guidance['markdown'])}\n\n"
        "Steps:\n"
        "1. Use asana_list_tasks to get current sprint/section task counts and statuses.\n"
        "2. Use github_list_prs to get recently merged and open PRs.\n"
        "3. Use github_list_issues to get recently opened, closed, and blocked issues.\n"
        "4. Cross-reference: which Asana tasks have linked PRs? Which are stale?\n"
        "5. Synthesize into the report format above.\n"
        "6. Always include the reporting period and data sources at the bottom."
    )
