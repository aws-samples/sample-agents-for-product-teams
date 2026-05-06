"""Post "blocked by safety filter" replies back to the originating thread.

When the Dispatch Router's guardrail check blocks a request, we post a
short note back to the GitHub issue or Asana task that originated the
mention so the sender sees what happened (no silent failures).

Both helpers return a bool instead of raising: the block decision has
already been made by the time we call these, and a failed reply must
not revert that decision. Reply failures emit a CloudWatch metric so
operators can alarm separately (`GuardrailReplyFailed`).
"""

import logging
import os
from typing import Optional

import boto3
import requests
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
ASANA_API = "https://app.asana.com/api/1.0"

GITHUB_PAT_PARAM_ENV = "GITHUB_PAT_PARAM"
ASANA_PAT_PARAM_ENV = "ASANA_PAT_PARAM"

_ssm = boto3.client("ssm")


def post_github_comment(repo: str, issue_number: str | int, body: str) -> bool:
    """Post a comment to a GitHub issue or PR. Returns True on success."""
    if not repo or not issue_number:
        logger.error("post_github_comment missing repo or issue_number")
        return False

    token = _get_secret(os.environ.get(GITHUB_PAT_PARAM_ENV, "/sdlc-agents/github-pat"))
    if not token:
        return False

    url = f"{GITHUB_API}/repos/{repo}/issues/{issue_number}/comments"
    try:
        response = requests.post(
            url,
            json={"body": body},
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=10,
        )
        response.raise_for_status()
        return True
    except requests.RequestException as exc:
        logger.error("Failed to post GitHub comment to %s#%s: %s", repo, issue_number, exc)
        return False


def post_asana_comment(task_gid: str, body: str) -> bool:
    """Post a story (comment) to an Asana task. Returns True on success."""
    if not task_gid:
        logger.error("post_asana_comment missing task_gid")
        return False

    token = _get_secret(os.environ.get(ASANA_PAT_PARAM_ENV, "/sdlc-agents/asana-pat"))
    if not token:
        return False

    url = f"{ASANA_API}/tasks/{task_gid}/stories"
    try:
        response = requests.post(
            url,
            json={"data": {"text": body}},
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            timeout=10,
        )
        response.raise_for_status()
        return True
    except requests.RequestException as exc:
        logger.error("Failed to post Asana comment to task %s: %s", task_gid, exc)
        return False


def _get_secret(param_name: str) -> Optional[str]:
    try:
        resp = _ssm.get_parameter(Name=param_name, WithDecryption=True)
        return resp["Parameter"]["Value"]
    except (ClientError, BotoCoreError) as exc:
        logger.error("Failed to fetch SSM parameter %s: %s", param_name, exc)
        return None
