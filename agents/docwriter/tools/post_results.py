"""Post results back to the originating platform.

Routes agent output to wherever the work request came from
(Asana comment, GitHub issue comment, or Slack thread).
"""

from strands import tool


@tool
def post_results(
    platform: str,
    target_id: str,
    message: str,
    thread_id: str = "",
) -> str:
    """Post the agent's results back to the platform that requested the work.

    The agent should call this after completing a task to report results to the
    requester. The Dispatch Router populates platform and target_id in the
    invocation payload.

    Args:
        platform: Where to post — 'asana', 'github', or 'slack'
        target_id: The target identifier (Asana task GID, GitHub issue number,
            or Slack channel ID)
        message: The message to post
        thread_id: Optional thread/comment ID for threaded replies

    Returns:
        Instruction for the agent to use the appropriate Gateway tool to post.
    """
    tool_map = {
        "asana": f"Use asana_add_comment on task '{target_id}' with this message.",
        "github": f"Use github_add_comment on issue/PR #{target_id} with this message.",
        "slack": (
            f"Use slack_post_message to channel '{target_id}'"
            + (f" in thread '{thread_id}'" if thread_id else "")
            + " with this message."
        ),
    }

    instruction = tool_map.get(
        platform,
        f"Unknown platform '{platform}'. Post the message as a GitHub issue comment.",
    )

    return f"{instruction}\n\nMessage to post:\n{message}"
