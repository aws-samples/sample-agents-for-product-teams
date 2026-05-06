"""Unit tests for the block-reply helpers used by the Dispatch Router."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import reply  # noqa: E402


@pytest.fixture(autouse=True)
def _mock_ssm():
    with patch.object(reply, "_ssm") as mock:
        mock.get_parameter.return_value = {"Parameter": {"Value": "fake-token"}}
        yield mock


def _mock_response(status_code: int = 200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.raise_for_status = MagicMock()
    return resp


def test_github_comment_hits_expected_url():
    with patch.object(reply.requests, "post", return_value=_mock_response()) as mock_post:
        ok = reply.post_github_comment("acme/web", 42, "blocked")
    assert ok is True
    url = mock_post.call_args.args[0]
    assert url == "https://api.github.com/repos/acme/web/issues/42/comments"
    assert mock_post.call_args.kwargs["json"] == {"body": "blocked"}
    assert mock_post.call_args.kwargs["headers"]["Authorization"] == "Bearer fake-token"


def test_github_comment_swallows_http_error():
    import requests
    err = requests.RequestException("boom")
    with patch.object(reply.requests, "post", side_effect=err):
        ok = reply.post_github_comment("acme/web", 42, "blocked")
    assert ok is False


def test_github_comment_rejects_missing_identifiers():
    with patch.object(reply.requests, "post") as mock_post:
        assert reply.post_github_comment("", 42, "x") is False
        assert reply.post_github_comment("acme/web", "", "x") is False
    mock_post.assert_not_called()


def test_asana_comment_hits_expected_url():
    with patch.object(reply.requests, "post", return_value=_mock_response()) as mock_post:
        ok = reply.post_asana_comment("12345", "blocked")
    assert ok is True
    url = mock_post.call_args.args[0]
    assert url == "https://app.asana.com/api/1.0/tasks/12345/stories"
    assert mock_post.call_args.kwargs["json"] == {"data": {"text": "blocked"}}


def test_asana_comment_swallows_http_error():
    import requests
    err = requests.RequestException("boom")
    with patch.object(reply.requests, "post", side_effect=err):
        ok = reply.post_asana_comment("12345", "blocked")
    assert ok is False
