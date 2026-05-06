"""Bedrock Guardrails edge check for the Dispatch Router.

Runs the caller-supplied `body` through Bedrock `ApplyGuardrail` before an
agent is invoked. Blocks prompts flagged as prompt-attack patterns
(threat-model T-1, T-2, T-3). See `infra/foundation/template.yaml` for the
guardrail resource definition.

Behavior:
  - Pass  → returns GuardrailPassed, dispatch continues unchanged.
  - Block → returns GuardrailBlocked with reason; Router records assignment
            as blocked_guardrail, posts reply, returns 400 to caller.
  - Error → retried once with short backoff; persistent failure returns
            GuardrailError. Router fails closed and returns 503.

The module never raises: the Router's contract is that guardrail
evaluation either produces a verdict or an explicit error outcome.
"""

import logging
import os
import time
from dataclasses import dataclass
from typing import Literal

import boto3
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger(__name__)

GUARDRAIL_ID_ENV = "BEDROCK_GUARDRAIL_ID"
GUARDRAIL_VERSION_ENV = "BEDROCK_GUARDRAIL_VERSION"
_DEFAULT_VERSION = "DRAFT"
_RETRY_DELAY_SECONDS = 0.25

_bedrock_runtime = boto3.client("bedrock-runtime")


@dataclass(frozen=True)
class GuardrailResult:
    outcome: Literal["passed", "blocked", "error"]
    reason: str = ""


def check_prompt(body: str) -> GuardrailResult:
    """Evaluate `body` against the configured Bedrock Guardrail.

    An empty body short-circuits to passed — nothing for the guardrail to score.
    """
    if not body or not body.strip():
        return GuardrailResult(outcome="passed")

    guardrail_id = os.environ.get(GUARDRAIL_ID_ENV)
    guardrail_version = os.environ.get(GUARDRAIL_VERSION_ENV, _DEFAULT_VERSION)

    if not guardrail_id:
        logger.error(
            "%s is not set; refusing to dispatch without a guardrail check.",
            GUARDRAIL_ID_ENV,
        )
        return GuardrailResult(outcome="error", reason="not_configured")

    try:
        response = _apply_with_retry(
            guardrail_id=guardrail_id,
            guardrail_version=guardrail_version,
            body=body,
        )
    except (ClientError, BotoCoreError) as exc:
        logger.exception("ApplyGuardrail failed after retry: %s", exc)
        return GuardrailResult(outcome="error", reason="api_error")

    action = response.get("action", "NONE")
    if action == "GUARDRAIL_INTERVENED":
        reason = _extract_reason(response)
        logger.warning("Guardrail intervened: reason=%s", reason)
        return GuardrailResult(outcome="blocked", reason=reason)

    return GuardrailResult(outcome="passed")


def _apply_with_retry(*, guardrail_id: str, guardrail_version: str, body: str) -> dict:
    """Call ApplyGuardrail with one retry on transient failure."""
    try:
        return _apply(guardrail_id, guardrail_version, body)
    except (ClientError, BotoCoreError) as first_error:
        logger.warning("ApplyGuardrail first attempt failed, retrying: %s", first_error)
        time.sleep(_RETRY_DELAY_SECONDS)  # nosemgrep: arbitrary-sleep — backoff between ApplyGuardrail retries
        return _apply(guardrail_id, guardrail_version, body)


def _apply(guardrail_id: str, guardrail_version: str, body: str) -> dict:
    return _bedrock_runtime.apply_guardrail(
        guardrailIdentifier=guardrail_id,
        guardrailVersion=guardrail_version,
        source="INPUT",
        content=[{"text": {"text": body}}],
    )


def _extract_reason(response: dict) -> str:
    """Pull a compact reason string out of the guardrail response assessments."""
    assessments = response.get("assessments", [])
    reasons = []
    for assessment in assessments:
        for content_filter in assessment.get("contentPolicy", {}).get("filters", []):
            if content_filter.get("action") == "BLOCKED":
                reasons.append(content_filter.get("type", "unknown"))
    return ",".join(reasons) if reasons else "prompt_attack"
