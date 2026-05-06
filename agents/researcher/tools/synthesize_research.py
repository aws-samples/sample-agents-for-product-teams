"""Research synthesis tool.

Structured task tool — guides the agent through processing qualitative
research inputs into structured findings with themes, severity, and frequency.
"""

from strands import tool


@tool
def synthesize_research(
    input_type: str,
    task_gid: str = "",
    output_format: str = "structured",
) -> str:
    """Synthesize qualitative research inputs into structured findings.

    The agent should use this tool when asked to process interview transcripts,
    survey responses, support tickets, or other qualitative data.

    Args:
        input_type: Type of input — 'transcript', 'survey', 'support_tickets',
            'app_reviews', or 'feedback'.
        task_gid: Asana task GID where the raw data is attached or described.
            Empty means use the current task context.
        output_format: 'structured' (themes with counts), 'narrative' (prose
            summary), or 'user_stories' (ready-to-create Asana tasks).

    Returns:
        Instructions for the agent to follow when synthesizing research.
    """
    input_guidance = {
        "transcript": (
            "Read the interview transcript carefully. Look for:\n"
            "- Explicit pain points and frustrations\n"
            "- Workarounds the user has built\n"
            "- Feature requests (stated and implied)\n"
            "- Moments of delight or satisfaction\n"
            "- Comparisons to competitors or alternatives"
        ),
        "survey": (
            "Process the survey responses. Summarize distributions for\n"
            "quantitative questions and group open-ended responses by theme."
        ),
        "support_tickets": (
            "Analyze the support tickets. Categorize by issue type, count the\n"
            "frequency of each category, and identify the highest-impact issues\n"
            "by volume and severity."
        ),
        "app_reviews": (
            "Analyze app store reviews. Separate positive and negative themes,\n"
            "estimate overall sentiment distribution, and identify trending\n"
            "topics compared to earlier reviews."
        ),
        "feedback": (
            "Process the raw feedback. Identify themes, group similar items,\n"
            "and quantify frequency."
        ),
    }

    task_step = ""
    if task_gid:
        task_step = f"1. Read Asana task '{task_gid}' and all its comments to get the raw data.\n"
    else:
        task_step = "1. Read the current Asana task and all its comments to get the raw data.\n"

    output_guidance = {
        "structured": (
            "Format output as structured findings:\n"
            "- Theme name\n"
            "- Frequency (how many sources mentioned it)\n"
            "- Severity (high / medium / low)\n"
            "- Representative quotes\n"
            "- Affected personas\n"
            "- Suggested action\n"
            "- Related existing backlog items (if any)"
        ),
        "narrative": (
            "Write a prose summary that a product leader can read in 2 minutes.\n"
            "Lead with the top 3 findings, then supporting detail."
        ),
        "user_stories": (
            "For each major finding, draft a user story:\n"
            "- Title: As a [persona], I want [goal]\n"
            "- Acceptance criteria with testable conditions\n"
            "- Edge cases\n"
            "- Dependencies\n"
            "- RICE estimate"
        ),
    }

    return (
        f"Synthesize {input_type} research.\n\n"
        f"{input_guidance.get(input_type, input_guidance['feedback'])}\n\n"
        f"Steps:\n"
        f"{task_step}"
        "2. Extract and organize the raw data.\n"
        "3. Identify themes and rank by frequency and severity.\n"
        "4. Cross-reference findings against the existing backlog using\n"
        "   asana_search to find related tasks.\n"
        f"5. {output_guidance.get(output_format, output_guidance['structured'])}\n"
        "6. Post results as an Asana comment on the originating task.\n"
        "7. Include methodology notes and confidence level."
    )
