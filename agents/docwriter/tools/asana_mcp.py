"""Asana MCP server connection.

Connects to Asana's official MCP server (https://mcp.asana.com/v2/mcp)
using OAuth tokens. Handles automatic token refresh when the access token
expires (1 hour lifetime).

Credentials are loaded from SSM Parameter Store in production or
environment variables for local development.
"""

import logging
import os
import time

import boto3
import requests

logger = logging.getLogger(__name__)

TOKEN_URL = "https://app.asana.com/-/oauth_token"  # nosec B105 — OAuth endpoint URL, not a credential

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


def get_access_token() -> str:
    """Get a valid Asana MCP access token. Refreshes automatically when expired."""
    global _cached_access_token, _token_expiry

    if _cached_access_token and time.time() < _token_expiry - 60:
        return _cached_access_token

    client_id = _get_credential("ASANA_MCP_CLIENT_ID", "/sdlc-agents/asana-mcp-client-id")
    client_secret = _get_credential("ASANA_MCP_CLIENT_SECRET", "/sdlc-agents/asana-mcp-client-secret")
    refresh_token = _get_credential("ASANA_MCP_REFRESH_TOKEN", "/sdlc-agents/asana-mcp-refresh-token")

    resp = requests.post(TOKEN_URL, data={
        "grant_type": "refresh_token",
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
    }, timeout=15)

    resp.raise_for_status()
    tokens = resp.json()

    _cached_access_token = tokens["access_token"]
    _token_expiry = time.time() + tokens.get("expires_in", 3600)

    # If Asana rotated the refresh token, update SSM
    new_refresh = tokens.get("refresh_token")
    if new_refresh and new_refresh != refresh_token:
        try:
            _get_ssm().put_parameter(
                Name="/sdlc-agents/asana-mcp-refresh-token",
                Value=new_refresh,
                Type="SecureString",
                Overwrite=True,
            )
        except Exception:
            logger.exception(
                "Failed to persist rotated Asana refresh token to SSM. "
                "Access token works for this session, but the next cold-start "
                "will retry rotation from the stale token — fix IAM/SSM if this recurs."
            )

    return _cached_access_token


ASANA_MCP_URL = "https://mcp.asana.com/v2/mcp"
