"""Tests for the Dispatch Router's authorization check.

Focuses on the fail-closed semantics around unresolved sender identities
(empty string, "unknown") and the empty-allowlist rejection, which together
prevent a misconfigured allowlist from becoming a universal bypass when the
upstream event receiver fails to resolve a stable identity (threat T-4).
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def router_module(monkeypatch):
    monkeypatch.setenv("BEDROCK_GUARDRAIL_ID", "gr-test")
    monkeypatch.setenv("ASSIGNMENTS_TABLE", "t")
    with patch("boto3.resource"), patch("boto3.client"):
        for name in ("router", "guardrail", "reply"):
            sys.modules.pop(name, None)
        import router as router_mod
    yield router_mod


def test_empty_allowlist_rejects_all(router_module):
    agent_config = {"agent_id": "workitems", "authorization": {"users": []}}
    assert router_module.check_authorization(agent_config, "alice", "github") is False


def test_missing_authorization_key_rejects_all(router_module):
    agent_config = {"agent_id": "workitems"}
    assert router_module.check_authorization(agent_config, "alice", "github") is False


def test_wildcard_allows_resolved_sender(router_module):
    agent_config = {"agent_id": "workitems", "authorization": {"users": ["*"]}}
    assert router_module.check_authorization(agent_config, "alice", "github") is True


@pytest.mark.parametrize("sender", ["", "unknown"])
def test_wildcard_does_not_allow_unresolved_sender(router_module, sender):
    agent_config = {"agent_id": "workitems", "authorization": {"users": ["*"]}}
    assert router_module.check_authorization(agent_config, sender, "asana") is False


@pytest.mark.parametrize("sender", ["", "unknown"])
def test_explicit_allowlist_does_not_allow_unresolved_sender(router_module, sender):
    agent_config = {
        "agent_id": "workitems",
        "authorization": {"users": [sender, "1202334567890123"]},
    }
    assert router_module.check_authorization(agent_config, sender, "asana") is False


def test_asana_gid_match(router_module):
    agent_config = {
        "agent_id": "workitems",
        "authorization": {"users": ["1202334567890123"]},
    }
    assert router_module.check_authorization(
        agent_config, "1202334567890123", "asana"
    ) is True
    assert router_module.check_authorization(
        agent_config, "9999999999999999", "asana"
    ) is False
