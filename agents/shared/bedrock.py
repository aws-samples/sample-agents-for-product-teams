"""Bedrock model construction with shared guardrail configuration.

Every agent in the fleet builds its `BedrockModel` through this helper so
that the same prompt-injection guardrail is attached to every Claude call
across every agent. See `infra/foundation/template.yaml` for the
`PromptInjectionGuardrail` resource (threat-model T-1, T-2, T-3).

Env vars injected by each agent's AgentCore runtime:
  BEDROCK_MODEL_ID           — model identifier (defaults to Opus 4.7)
  BEDROCK_GUARDRAIL_ID       — guardrail identifier from foundation stack
  BEDROCK_GUARDRAIL_VERSION  — guardrail version (typically "DRAFT")

Fail-closed posture: if ``BEDROCK_GUARDRAIL_ID`` is unset, ``build_model``
raises. This is the runtime half of the T-1 defense — an agent that ships
without the guardrail bypasses the only layer that sees indirect injection
in MCP-fetched content (edge guardrail at the Router only sees the user
comment). Tests and local dev can opt out by setting
``SDLC_ALLOW_MISSING_GUARDRAIL=1``.
"""

import logging
import os

from strands.models import BedrockModel

logger = logging.getLogger(__name__)

DEFAULT_MODEL_ID = "us.anthropic.claude-opus-4-7"
_ALLOW_MISSING_GUARDRAIL_ENV = "SDLC_ALLOW_MISSING_GUARDRAIL"


def build_model(**extra) -> BedrockModel:
    """Construct a `BedrockModel` with the fleet's prompt-injection guardrail attached.

    Extra keyword arguments (e.g. ``max_tokens``) are forwarded to ``BedrockModel``.

    Raises:
        RuntimeError: if ``BEDROCK_GUARDRAIL_ID`` is unset and the explicit
            ``SDLC_ALLOW_MISSING_GUARDRAIL=1`` escape hatch is not set.
    """
    model_id = os.environ.get("BEDROCK_MODEL_ID", DEFAULT_MODEL_ID)
    guardrail_id = os.environ.get("BEDROCK_GUARDRAIL_ID")
    guardrail_version = os.environ.get("BEDROCK_GUARDRAIL_VERSION", "DRAFT")

    if not guardrail_id:
        if os.environ.get(_ALLOW_MISSING_GUARDRAIL_ENV) == "1":
            logger.warning(
                "BEDROCK_GUARDRAIL_ID is not set and %s=1 — constructing "
                "BedrockModel without the prompt-injection guardrail. This "
                "escape hatch is intended for local dev and unit tests only.",
                _ALLOW_MISSING_GUARDRAIL_ENV,
            )
            return BedrockModel(model_id=model_id, **extra)
        raise RuntimeError(
            "BEDROCK_GUARDRAIL_ID is not set. Deployed runtimes must have this "
            "env var injected from the foundation stack's GuardrailId output "
            "(threat-model T-1). Set SDLC_ALLOW_MISSING_GUARDRAIL=1 only for "
            "local development or unit tests."
        )

    return BedrockModel(
        model_id=model_id,
        guardrail_id=guardrail_id,
        guardrail_version=guardrail_version,
        guardrail_trace="enabled",
        **extra,
    )
