"""Spec review tool.

Structured task tool — guides the agent through reviewing a user story
or requirements document for completeness, testability, and quality.
"""

from strands import tool


@tool
def review_spec(
    task_gid: str,
) -> str:
    """Review an Asana task's requirements for completeness and quality.

    The agent should use this tool when asked to review a spec, user story,
    or requirements document for quality.

    Args:
        task_gid: Asana task GID to review.

    Returns:
        Instructions for the agent to follow when reviewing the spec.
    """
    return (
        f"Review the requirements on Asana task '{task_gid}'.\n\n"
        "Steps:\n"
        f"1. Read Asana task '{task_gid}' including description and ALL comments.\n"
        "2. Check subtasks if they exist.\n"
        "3. Evaluate against this checklist:\n\n"
        "   ACCEPTANCE CRITERIA:\n"
        "   - Are all AC testable? (no vague terms like 'good', 'fast', 'easy')\n"
        "   - Are AC written as Given/When/Then or clear condition/result?\n"
        "   - Do AC cover the happy path AND error states?\n"
        "   - Are there specific, measurable thresholds where needed?\n\n"
        "   COMPLETENESS:\n"
        "   - Is the target persona specified?\n"
        "   - Is the goal clearly stated?\n"
        "   - Are edge cases listed?\n"
        "   - Are dependencies on other tasks identified?\n"
        "   - Are non-functional requirements stated (performance, security)?\n\n"
        "   AMBIGUITIES:\n"
        "   - Any terms that could be interpreted multiple ways?\n"
        "   - Any implicit assumptions that should be explicit?\n"
        "   - Any 'TBD' or placeholder sections?\n\n"
        "   TESTABILITY:\n"
        "   - Could a QA engineer write test cases from these AC alone?\n"
        "   - Are boundary conditions specified?\n\n"
        "4. Assign a completeness score (1-10).\n"
        "5. For each issue found, suggest a specific fix — don't just flag it.\n"
        "6. Post the review as an Asana comment on the task.\n"
        "7. Be constructive. The goal is to improve the spec, not criticize."
    )
