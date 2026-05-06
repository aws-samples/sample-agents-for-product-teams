"""User story drafting tool.

Structured task tool — guides the agent through creating user stories
from research findings, product direction, or identified gaps.
"""

from strands import tool


@tool
def draft_user_stories(
    input_source: str,
    task_gid: str = "",
    count: str = "",
) -> str:
    """Generate user stories from research findings or product direction.

    The agent should use this tool when asked to create requirements,
    write user stories, or translate findings into actionable work items.

    Args:
        input_source: Description of what to write stories for. Can reference
            research findings, competitive gaps, or product direction.
        task_gid: Asana task GID with the source material. Empty means
            use the current task context.
        count: Maximum number of stories to generate. Empty means generate
            as many as the input warrants.

    Returns:
        Instructions for the agent to follow when drafting user stories.
    """
    task_step = ""
    if task_gid:
        task_step = f"1. Read Asana task '{task_gid}' and all comments for source material.\n"
    else:
        task_step = "1. Read the current Asana task and all comments for source material.\n"

    count_note = ""
    if count:
        count_note = f"\nLimit: Generate at most {count} stories.\n"

    return (
        f"Draft user stories based on: {input_source}\n"
        f"{count_note}\n"
        "Steps:\n"
        f"{task_step}"
        "2. Recall domain knowledge and user personas from memory.\n"
        "3. Identify the distinct user needs or capabilities implied by\n"
        "   the source material.\n"
        "4. For EACH story, produce:\n"
        "   - Title: 'As a [persona], I want [goal] so that [benefit]'\n"
        "   - Description: context and motivation\n"
        "   - Acceptance criteria: Given/When/Then format, testable,\n"
        "     covering happy path and error states\n"
        "   - Edge cases: at least 2-3 per story\n"
        "   - Dependencies: other tasks that must be done first\n"
        "   - RICE estimate: Reach * Impact * Confidence / Effort\n"
        "5. Check the existing backlog (asana_search) for overlap.\n"
        "   Flag any stories that duplicate existing tasks.\n"
        "6. Create the stories as new Asana tasks in the project.\n"
        "   - Tag each with 'researcher-generated'\n"
        "   - Set custom fields for RICE score if available\n"
        "7. Post a summary comment on the originating task listing\n"
        "   all stories created with links."
    )
