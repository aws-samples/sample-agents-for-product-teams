"""Post results back to Asana.

Researcher works exclusively through Asana, so this is a simplified version
that always routes output to an Asana task comment.
"""

from strands import tool


@tool
def post_results(
    task_gid: str,
    message: str,
) -> str:
    """Post the agent's results back to an Asana task.

    The agent should call this after completing analysis to report results
    to the requester.

    Args:
        task_gid: The Asana task GID to comment on
        message: The message to post

    Returns:
        Instruction for the agent to use the Asana MCP tool to post.
    """
    return (
        f"Use asana_add_comment on task '{task_gid}' with this message.\n\n"
        f"Message to post:\n{message}"
    )
