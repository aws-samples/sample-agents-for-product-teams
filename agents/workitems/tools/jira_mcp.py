"""Jira/Atlassian MCP server connection.

Connects to Atlassian's official Remote MCP Server
(https://mcp.atlassian.com/v1/mcp) using OAuth 3LO tokens. Handles automatic
access-token refresh (1-hour lifetime) and rotating-refresh-token rotation
(~90-day lifetime).

Credentials are loaded from SSM Parameter Store in production or
environment variables for local development.
"""

import logging
import os
import time

import boto3
import requests

logger = logging.getLogger(__name__)

TOKEN_URL = "https://auth.atlassian.com/oauth/token"  # nosec B105 — OAuth endpoint URL, not a credential
JIRA_MCP_URL = "https://mcp.atlassian.com/v1/mcp"

_ssm = None
_cached_access_token = None
_token_expiry = 0


def _get_ssm():
    global _ssm
    if _ssm is None:
        _ssm = boto3.client("ssm")
    return _ssm


def _get_ssm_param(name: str) -> str:
    resp = _get_ssm().get_parameter(Name=name, WithDecryption=True)
    return resp["Parameter"]["Value"]


def _get_credential(env_var: str, ssm_param: str) -> str:
    """Try env var first (local dev), then SSM (production)."""
    val = os.environ.get(env_var)
    if val:
        return val
    return _get_ssm_param(ssm_param)


def get_cloud_id() -> str:
    """Return the Atlassian cloud ID for the configured tenant."""
    return _get_credential("JIRA_CLOUD_ID", "/sdlc-agents/jira-cloud-id")


def get_access_token() -> str:
    """Get a valid Jira MCP access token. Refreshes automatically when expired."""
    global _cached_access_token, _token_expiry

    if _cached_access_token and time.time() < _token_expiry - 60:
        return _cached_access_token

    client_id = _get_credential("JIRA_MCP_CLIENT_ID", "/sdlc-agents/jira-mcp-client-id")
    client_secret = _get_credential("JIRA_MCP_CLIENT_SECRET", "/sdlc-agents/jira-mcp-client-secret")
    refresh_token = _get_credential("JIRA_MCP_REFRESH_TOKEN", "/sdlc-agents/jira-mcp-refresh-token")

    resp = requests.post(
        TOKEN_URL,
        json={
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
        },
        timeout=15,
    )
    resp.raise_for_status()
    tokens = resp.json()

    _cached_access_token = tokens["access_token"]
    _token_expiry = time.time() + tokens.get("expires_in", 3600)

    # Atlassian uses rotating refresh tokens — every refresh returns a new one
    # and invalidates the old. Persist immediately so the next cold start
    # doesn't try to reuse the dead token.
    new_refresh = tokens.get("refresh_token")
    if new_refresh and new_refresh != refresh_token:
        try:
            _get_ssm().put_parameter(
                Name="/sdlc-agents/jira-mcp-refresh-token",
                Value=new_refresh,
                Type="SecureString",
                Overwrite=True,
            )
        except Exception:
            logger.exception(
                "Failed to persist rotated Jira refresh token to SSM. "
                "Access token works for this session, but the next cold-start "
                "will retry rotation from the stale token — fix IAM/SSM if this recurs."
            )

    return _cached_access_token
