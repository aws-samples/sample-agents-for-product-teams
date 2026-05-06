"""Integration-ish unit tests for Router's guardrail handling.

These exercise the handler end-to-end with the Bedrock client mocked.
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


REGISTRY = {
    "agents": {
        "workitems": {
            "runtime_arn": "arn:aws:bedrock-agentcore:us-west-2:123:runtime/wi",
            "authorization": {"users": ["alice"]},
            "limits": {"max_concurrent": 5},
        }
    }
}


@pytest.fixture
def router(monkeypatch):
    """Import router with env primed and external clients mocked."""
    monkeypatch.setenv("BEDROCK_GUARDRAIL_ID", "gr-test")
    monkeypatch.setenv("BEDROCK_GUARDRAIL_VERSION", "DRAFT")
    monkeypatch.setenv("ASSIGNMENTS_TABLE", "t")
    monkeypatch.setenv("STAGE", "dev")

    with patch("boto3.resource"), patch("boto3.client"):
        if "router" in sys.modules:
            del sys.modules["router"]
        if "guardrail" in sys.modules:
            del sys.modules["guardrail"]
        if "reply" in sys.modules:
            del sys.modules["reply"]
        import router as router_mod  # noqa: E402
    router_mod._registry_cache = REGISTRY
    # Avoid real DynamoDB calls:
    router_mod.assignments_table = MagicMock()
    router_mod.assignments_table.query.return_value = {"Count": 0}
    yield router_mod


def _event_github(body="hello"):
    return {
        "source": "github",
        "trigger_type": "comment_mention",
        "body": f"@workitems {body}",
        "sender": "alice",
        "context": {"repo": "acme/web", "issue_number": 7},
    }


def test_guardrail_pass_dispatches(router):
    with patch("guardrail.check_prompt") as mock_check, \
         patch.object(router, "invoke_agent") as mock_invoke:
        mock_check.return_value = MagicMock(outcome="passed", reason="")
        resp = router.handler(_event_github(), None)
    assert resp["statusCode"] == 200
    mock_invoke.assert_called_once()


def test_guardrail_block_posts_reply_and_returns_400(router):
    with patch("guardrail.check_prompt") as mock_check, \
         patch("reply.post_github_comment", return_value=True) as mock_reply, \
         patch.object(router, "invoke_agent") as mock_invoke:
        mock_check.return_value = MagicMock(outcome="blocked", reason="PROMPT_ATTACK")
        resp = router.handler(_event_github(), None)
    assert resp["statusCode"] == 400
    assert "blocked" in json.loads(resp["body"])["error"].lower()
    mock_reply.assert_called_once()
    mock_invoke.assert_not_called()
    # The blocked assignment row was written and updated with blocked_guardrail status
    calls = router.assignments_table.update_item.call_args_list
    joined = "".join(str(c) for c in calls)
    assert "blocked_guardrail" in joined


def test_guardrail_error_posts_reply_and_returns_503(router):
    with patch("guardrail.check_prompt") as mock_check, \
         patch("reply.post_github_comment", return_value=True) as mock_reply, \
         patch.object(router, "invoke_agent") as mock_invoke:
        mock_check.return_value = MagicMock(outcome="error", reason="api_error")
        resp = router.handler(_event_github(), None)
    assert resp["statusCode"] == 503
    mock_reply.assert_called_once()
    mock_invoke.assert_not_called()
    calls = router.assignments_table.update_item.call_args_list
    joined = "".join(str(c) for c in calls)
    assert "blocked_guardrail_error" in joined


def test_reply_failure_does_not_revert_block(router):
    with patch("guardrail.check_prompt") as mock_check, \
         patch("reply.post_github_comment", return_value=False), \
         patch.object(router, "_put_metric") as mock_metric, \
         patch.object(router, "invoke_agent") as mock_invoke:
        mock_check.return_value = MagicMock(outcome="blocked", reason="PROMPT_ATTACK")
        resp = router.handler(_event_github(), None)
    assert resp["statusCode"] == 400
    mock_invoke.assert_not_called()
    # Both trip and reply-failed metrics were emitted
    names = [c.args[0] for c in mock_metric.call_args_list]
    assert "GuardrailTripped" in names
    assert "GuardrailReplyFailed" in names
