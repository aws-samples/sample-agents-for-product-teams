"""Backlog analysis tool.

Structured task tool — guides the agent through analyzing the product
backlog for duplicates, gaps, prioritization, and overall health.
"""

from strands import tool


@tool
def analyze_backlog(
    analysis_type: str = "full",
) -> str:
    """Analyze the Asana project backlog for quality and prioritization.

    The agent should use this tool when asked to review the backlog,
    find duplicates, compute priorities, or assess backlog health.

    Args:
        analysis_type: What to analyze —
            'duplicates' (find overlapping tasks),
            'gaps' (identify missing stories for known features),
            'priority' (compute RICE scores and suggest ordering),
            'health' (overall backlog health report),
            'full' (all of the above).

    Returns:
        Instructions for the agent to follow when analyzing the backlog.
    """
    analyses = {
        "duplicates": (
            "DUPLICATE DETECTION:\n"
            "1. Read all open tasks in the project using asana_list_tasks.\n"
            "2. Identify pairs of tasks with overlapping scope by comparing\n"
            "   titles and descriptions.\n"
            "3. For each pair, explain why they might be duplicates and\n"
            "   recommend: merge, differentiate, or keep both."
        ),
        "gaps": (
            "GAP ANALYSIS:\n"
            "1. Read all tasks and group by feature area or section.\n"
            "2. Recall domain knowledge and feature areas from memory.\n"
            "3. For each known feature area, check if stories exist for:\n"
            "   - Core functionality\n"
            "   - Error handling\n"
            "   - Edge cases\n"
            "   - Performance requirements\n"
            "4. Report gaps with suggested stories to fill them."
        ),
        "priority": (
            "PRIORITIZATION (RICE):\n"
            "1. Read all open tasks with their custom fields.\n"
            "2. For each task, estimate RICE components:\n"
            "   - Reach: how many users affected (from task context)\n"
            "   - Impact: how much it moves the needle (1-3 scale)\n"
            "   - Confidence: how sure are we (0.0-1.0)\n"
            "   - Effort: estimated weeks of work\n"
            "3. Compute RICE = (Reach * Impact * Confidence) / Effort for each.\n"
            "4. Present 2-3 prioritization options with different weighting.\n"
            "5. Explain trade-offs for each option."
        ),
        "health": (
            "BACKLOG HEALTH:\n"
            "1. Read all tasks in the project.\n"
            "2. Summarize:\n"
            "   - Total open tasks, grouped by section/status\n"
            "   - Age distribution (tasks by creation date)\n"
            "   - Tasks without acceptance criteria\n"
            "   - Tasks without assignees\n"
            "   - Overdue tasks\n"
            "   - Tasks with no activity in 30+ days\n"
            "3. Generate a health score and trend if prior data in memory.\n"
            "4. Recommend specific cleanup actions."
        ),
    }

    if analysis_type == "full":
        steps = "\n\n".join(analyses.values())
    else:
        steps = analyses.get(analysis_type, analyses["health"])

    return (
        f"Analyze the project backlog.\n"
        f"Analysis type: {analysis_type}\n\n"
        f"{steps}\n\n"
        "Post results as an Asana comment with clear sections and\n"
        "actionable recommendations. Include data citations."
    )
