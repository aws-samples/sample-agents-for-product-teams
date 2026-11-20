"""Memory and MCP client setup shared by every agent in the fleet.

Each agent builds its AgentCore memory and its remote MCP clients the same
way; only the agent name and the MCP server differ. Keeping the construction
here means the next SDK change is fixed once, not four times.
"""

from __future__ import annotations

from typing import Any

from bedrock_agentcore.memory.integrations.strands.memorystore import (
    AgentCoreMemoryStore,
)
from strands.memory import MemoryManager
from strands.tools.mcp import MCPClient


class RecordingAgentCoreMemoryStore(AgentCoreMemoryStore):
    """AgentCoreMemoryStore that also implements ``add``.

    ``AgentCoreMemoryStore`` only implements ``add_messages`` (conversation
    events picked up by automatic extraction). ``MemoryManager`` needs ``add``
    to offer the model an ``add_memory`` tool, which the agent prompts rely on
    to record state explicitly (for example adr's applied/removed labels).

    ``add`` writes the entry as one assistant event, the same kind of event the
    old ``strands_tools`` ``AgentCoreMemoryToolProvider`` "record" action
    created, so the configured extraction strategies process it as before.
    ``metadata`` is accepted for the ``MemoryStore`` contract but not sent;
    the ``add_memory`` tool never passes it.
    """

    async def add(self, content: str, metadata: dict[str, Any] | None = None) -> None:
        await self.add_messages([{"role": "assistant", "content": [{"text": content}]}])


def build_memory_manager(
    memory_id: str | None, agent_name: str, session_id: str
) -> MemoryManager | None:
    """Return the agent's MemoryManager, or None when memory is not configured.

    The model gets two tools: ``search_memory`` and ``add_memory``. Conversation
    turns are also written automatically for extraction.
    """
    if not memory_id:
        return None
    return MemoryManager(
        stores=[
            RecordingAgentCoreMemoryStore(
                memory_id=memory_id,
                actor_id=agent_name,
                session_id=session_id,
                namespace=f"/agents/{agent_name}/{session_id}",
                writable=True,
                extraction=True,
            )
        ],
        add_tool_config=True,
        injection=False,
    )


def build_mcp_client(url: str, token: str) -> MCPClient:
    """Return a streamable-HTTP MCP client that sends ``token`` as a bearer token."""
    return MCPClient(url=url, headers={"Authorization": f"Bearer {token}"})
