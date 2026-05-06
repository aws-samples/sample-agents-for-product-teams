"""Researcher — Autonomous Business Analyst agent.

Performs research synthesis, competitive intelligence, requirements drafting,
backlog analysis, and impact estimation. Works exclusively through Asana.

Deployed to Amazon Bedrock AgentCore Runtime.
Uses Claude Opus 4.7 via Bedrock and Asana's official MCP server.
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
from tools.synthesize_research import synthesize_research
from tools.competitive_scan import competitive_scan
from tools.review_spec import review_spec
from tools.analyze_backlog import analyze_backlog
from tools.draft_user_stories import draft_user_stories
from tools.post_results import post_results
from tools.web_search import web_search
from tools.asana_mcp import get_access_token, ASANA_MCP_URL

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
ACTOR_ID = "researcher"

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
    source = payload.get("source", "unknown")
    source_context = payload.get("source_context", {})

    # Dispatch context lives in the system prompt, not in the user message —
    # the "[Dispatch Context] ... [User Request]" wrapper trips Bedrock
    # Guardrails' PROMPT_ATTACK filter because it mirrors the canonical
    # injection shape. Researcher only operates through Asana today.
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

    # Build system prompt with project context + dispatch context.
    system_prompt = SYSTEM_PROMPT.format(
        project_context=build_project_context(),
    ) + dispatch_context_block

    model = build_model()
    tools = [
        synthesize_research,
        competitive_scan,
        review_spec,
        analyze_backlog,
        draft_user_stories,
        post_results,
        web_search,
    ]

    # Memory — optional until Memory resource is created
    if MEMORY_ID:
        memory_provider = AgentCoreMemoryToolProvider(
            memory_id=MEMORY_ID,
            actor_id=ACTOR_ID,
            session_id=session_id,
            namespace=f"/agents/researcher/{session_id}",
        )
        tools.extend(memory_provider.tools)

    # Asana MCP — official server with OAuth (Researcher's only external platform)
    asana_token = get_access_token()
    asana_client = MCPClient(
        lambda: streamablehttp_client(
            ASANA_MCP_URL,
            headers={"Authorization": f"Bearer {asana_token}"},
        )
    )

    with asana_client:
        asana_tools = asana_client.list_tools_sync()
        all_tools = [*asana_tools, *tools]

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
