"""Workitems — PO/PM autonomous agent.

Bridges Asana (planning) and GitHub (development). Assigned work via Asana
tasks, reasons about decomposition, proposes plans for approval, then creates
GitHub issues on approval.

Deployed to Amazon Bedrock AgentCore Runtime.
Uses Claude Opus 4.6 via Bedrock, Asana's official MCP server, and
GitHub's official remote MCP server.
"""

import logging
import os
import sys

from strands import Agent
from strands.tools.mcp import MCPClient
from mcp.client.streamable_http import streamablehttp_client
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands_tools.agent_core_memory import AgentCoreMemoryToolProvider

from shared.assignment import complete_assignment, fail_assignment
from shared.bedrock import build_model
from prompts import SYSTEM_PROMPT
from project_config import build_project_context
from tools.status_report import generate_status_report
from tools.risk_detection import detect_risks
from tools.sync import reconcile_sync
from tools.post_results import post_results
from tools.asana_mcp import get_access_token, ASANA_MCP_URL
from tools.github_mcp import get_github_token, GITHUB_MCP_URL

# --- Logging -----------------------------------------------------------------
# Configure root logger to emit to stdout so AgentCore's OTel sidecar captures
# application logs alongside traces and metrics.

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

# --- Configuration -----------------------------------------------------------

MEMORY_ID = os.environ.get("AGENTCORE_MEMORY_ID")
ACTOR_ID = "workitems"

# --- App ---------------------------------------------------------------------

app = BedrockAgentCoreApp()


@app.entrypoint
def invoke(payload, context=None):
    """Main agent entry point. Receives instruction from Dispatch or schedule."""

    if isinstance(payload, str):
        import json
        try:
            payload = json.loads(payload)
        except (json.JSONDecodeError, TypeError):
            payload = {"prompt": payload}

    if not isinstance(payload, dict):
        payload = {"prompt": str(payload)}

    user_input = payload.get("prompt", payload.get("user_input", ""))
    ctx = context if isinstance(context, dict) else {}
    session_id = payload.get("session_id", ctx.get("session_id", "default"))
    assignment_id = payload.get("assignment_id", "")
    source_context = payload.get("source_context", {})

    # Dispatch context lives in the system prompt, not in the user message.
    # Structured "[Dispatch Context] ... [User Request] ..." wrappers look
    # like the canonical prompt-injection shape and trip Bedrock Guardrails'
    # PROMPT_ATTACK filter even at MEDIUM strength. Keeping the user-supplied
    # content as the only user-role message lets the guardrail evaluate what
    # actually came from outside the trust boundary.
    source = payload.get("source", "unknown")
    dispatch_context_block = ""
    if source_context and source == "asana":
        dispatch_context_block = (
            "\n\n## Current Dispatch\n\n"
            f"Source: asana\n"
            f"Task GID: {source_context.get('task_gid', 'unknown')}\n"
            f"Task: {source_context.get('task_name', 'unknown')}\n"
            f"Task Notes: {source_context.get('task_notes', '')}\n"
            f"Project: {source_context.get('project_name', 'unknown')} ({source_context.get('project_gid', '')})\n"
            f"Reply to: Asana task {source_context.get('task_gid', 'unknown')}\n"
        )
    elif source_context and source == "github":
        dispatch_context_block = (
            "\n\n## Current Dispatch\n\n"
            f"Source: github\n"
            f"Repository: {source_context.get('repo', 'unknown')}\n"
            f"Issue: #{source_context.get('issue_number', 'unknown')}\n"
            f"Issue Title: {source_context.get('issue_title', 'unknown')}\n"
            f"Issue Body:\n{source_context.get('issue_body', '')}\n"
            f"Comments:\n{source_context.get('issue_comments', '(not loaded)')}\n"
            f"Reply to: GitHub issue #{source_context.get('issue_number', 'unknown')} "
            f"on {source_context.get('repo', 'unknown')}\n"
        )

    model = build_model()
    tools = [generate_status_report, detect_risks, reconcile_sync, post_results]

    # Memory — optional until Memory resource is created
    if MEMORY_ID:
        memory_provider = AgentCoreMemoryToolProvider(
            memory_id=MEMORY_ID,
            actor_id=ACTOR_ID,
            session_id=session_id,
            namespace=f"/agents/workitems/{session_id}",
        )
        tools.extend(memory_provider.tools)

    # Asana MCP — official server with OAuth (required)
    asana_token = get_access_token()
    asana_client = MCPClient(
        lambda: streamablehttp_client(
            ASANA_MCP_URL,
            headers={"Authorization": f"Bearer {asana_token}"},
        )
    )

    # GitHub MCP — official remote server with OAuth (required)
    github_token = get_github_token()
    github_client = MCPClient(
        lambda: streamablehttp_client(
            GITHUB_MCP_URL,
            headers={"Authorization": f"Bearer {github_token}"},
        )
    )

    with asana_client, github_client:
        asana_tools = asana_client.list_tools_sync()
        github_tools = github_client.list_tools_sync()

        # Drop GitHub tools that collide with Asana tool names
        # (e.g. both servers expose get_me — keep the Asana version)
        asana_names = {t.tool_name for t in asana_tools}
        github_tools = [gt for gt in github_tools if gt.tool_name not in asana_names]

        all_tools = [*asana_tools, *github_tools, *tools]

        system_prompt = SYSTEM_PROMPT.format(project_context=build_project_context()) + dispatch_context_block

        agent = Agent(
            model=model,
            system_prompt=system_prompt,
            tools=all_tools,
        )
        try:
            result = agent(user_input)
        except Exception as agent_error:
            try:
                fail_assignment(assignment_id, error=str(agent_error))
            except Exception:
                logger.exception("fail_assignment also failed for %s", assignment_id)
            raise
        complete_assignment(assignment_id, result_summary=str(result)[:500])

    return {"result": str(result)}


if __name__ == "__main__":
    app.run()
