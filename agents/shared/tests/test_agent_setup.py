"""Unit tests for `agents.shared.agent_setup`."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shared.agent_setup import (
    RecordingAgentCoreMemoryStore,
    build_memory_manager,
)


def test_no_memory_id_means_no_memory():
    assert build_memory_manager(None, "adr", "s1") is None
    assert build_memory_manager("", "adr", "s1") is None


def test_memory_manager_gives_the_model_search_and_add(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-west-2")
    manager = build_memory_manager("mem-123", "adr", "s1")
    names = sorted(t.tool_name for t in manager.tools)
    assert names == ["add_memory", "search_memory"]


def test_store_is_scoped_to_agent_and_session(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-west-2")
    manager = build_memory_manager("mem-123", "researcher", "s9")
    (store,) = manager._stores
    assert isinstance(store, RecordingAgentCoreMemoryStore)
    assert store.writable


def test_add_writes_one_assistant_event(monkeypatch):
    import asyncio

    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-west-2")
    manager = build_memory_manager("mem-123", "adr", "s1")
    (store,) = manager._stores
    sent = []

    async def fake_add_messages(messages, context=None):
        sent.append(messages)

    monkeypatch.setattr(store, "add_messages", fake_add_messages)
    asyncio.run(store.add("adr applied org/repo#7: adr-0003"))
    assert sent == [
        [
            {
                "role": "assistant",
                "content": [{"text": "adr applied org/repo#7: adr-0003"}],
            }
        ]
    ]
