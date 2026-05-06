"""Dispatch Router Lambda.

Single entry point for all agent work assignments. Receives normalized events
from GitHub Actions, Asana webhook receiver, and Slack, then:

1. Resolves @mention → agent ID (including aliases)
2. Checks authorization
3. Checks concurrency limits
4. Records assignment in DynamoDB
5. Invokes AgentCore Runtime
6. Returns acknowledgment to caller

The router is intentionally simple — all intelligence lives in the agents.
Adding a new agent is a config change in .dispatch/agents.yaml, not a code change.
"""

import json
import logging
import os
import re
import time
import uuid
from decimal import Decimal

import boto3
from botocore.config import Config

import guardrail
import reply

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# --- Clients -----------------------------------------------------------------

dynamodb = boto3.resource("dynamodb")
assignments_table = dynamodb.Table(os.environ.get("ASSIGNMENTS_TABLE", "dispatch-assignments"))
ssm = boto3.client("ssm")
cloudwatch = boto3.client("cloudwatch")
agentcore = boto3.client(
    "bedrock-agentcore",
    config=Config(read_timeout=900, connect_timeout=10, retries={"max_attempts": 0}),
)

CLOUDWATCH_NAMESPACE = os.environ.get("CLOUDWATCH_NAMESPACE", "SDLCAgents/Dispatch")
STAGE = os.environ.get("STAGE", "dev")

BLOCKED_MESSAGE_TEMPLATE = (
    "This request was blocked by a prompt-injection safety filter"
    "{reason_suffix}. No agent was invoked. If you believe this is a "
    "false positive, an operator can inspect assignment `{assignment_id}` "
    "in CloudWatch and re-dispatch manually."
)

GUARDRAIL_ERROR_MESSAGE_TEMPLATE = (
    "The prompt-injection safety check is temporarily unavailable; your "
    "request was not dispatched. Please try again in a few minutes. "
    "Assignment `{assignment_id}`."
)

# --- Agent Registry ----------------------------------------------------------
# Loaded from SSM Parameter Store (synced from .dispatch/agents.yaml on deploy).
# Cached for the lifetime of the Lambda execution environment.

_registry_cache = None


def load_registry():
    """Load agent registry from SSM Parameter Store."""
    global _registry_cache
    if _registry_cache is not None:
        return _registry_cache

    param = ssm.get_parameter(
        Name=os.environ.get("REGISTRY_PARAM", "/dispatch/agents"),
        WithDecryption=False,
    )
    import yaml

    _registry_cache = yaml.safe_load(param["Parameter"]["Value"])
    return _registry_cache


# --- Mention Parsing ---------------------------------------------------------

MENTION_PATTERN = re.compile(
    r"@(\w+)",
    re.IGNORECASE,
)


def resolve_agent(mention: str, registry: dict) -> dict | None:
    """Resolve a mention string to an agent config, checking aliases."""
    mention = mention.lower()
    agents = registry.get("agents", {})

    # Direct match
    if mention in agents:
        return {**agents[mention], "agent_id": mention}

    # Alias match
    for agent_id, config in agents.items():
        if mention in config.get("aliases", []):
            return {**config, "agent_id": agent_id}

    return None


def extract_mention_and_instruction(body: str, registry: dict) -> tuple[dict | None, str]:
    """Extract the first recognized @agent mention and the instruction text."""
    for match in MENTION_PATTERN.finditer(body):
        agent = resolve_agent(match.group(1), registry)
        if agent is not None:
            instruction = body[match.end() :].strip()
            return agent, instruction
    return None, ""


# --- Authorization -----------------------------------------------------------


_UNRESOLVED_SENDERS = {"", "unknown"}


def check_authorization(agent_config: dict, sender: str, source: str) -> bool:
    """Check if this user is authorized to invoke this agent from this source.

    Fails closed:
    - an empty `authorization.users` list rejects every sender
    - an empty or "unknown" sender is never allowlistable — these sentinel
      values indicate the upstream receiver couldn't resolve a stable identity,
      and allowing them would turn a misconfigured allowlist into a universal
      bypass.

    The wildcard `"*"` remains supported for operators who explicitly opt into
    an open-by-default posture, but it is not the shipping default.
    """
    auth = agent_config.get("authorization", {})
    allowed_users = auth.get("users", [])

    if not allowed_users:
        logger.warning(
            "Agent '%s' has an empty authorization.users list; rejecting sender '%s'. "
            "Populate .dispatch/agents.yaml and re-run scripts/sync_registry.py.",
            agent_config.get("agent_id", "?"),
            sender,
        )
        return False

    if not sender or sender in _UNRESOLVED_SENDERS:
        logger.warning(
            "Agent '%s' received an unresolved sender (%r); rejecting.",
            agent_config.get("agent_id", "?"),
            sender,
        )
        return False

    if "*" in allowed_users:
        return True

    return sender in allowed_users


# --- Concurrency -------------------------------------------------------------


def check_concurrency(agent_id: str, max_concurrent: int) -> bool:
    """Check if the agent has capacity for another assignment."""
    response = assignments_table.query(
        IndexName="agent_id-status-index",
        KeyConditionExpression="agent_id = :aid AND #s = :status",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":aid": agent_id,
            ":status": "dispatched",
        },
    )
    active_count = response.get("Count", 0)
    return active_count < max_concurrent


# --- Assignment Tracking -----------------------------------------------------


def create_assignment(
    agent_id: str,
    source: str,
    trigger_type: str,
    requester: str,
    instruction: str,
    source_context: dict,
) -> str:
    """Record a new assignment in DynamoDB. Returns assignment_id."""
    assignment_id = str(uuid.uuid4())
    now = int(time.time())
    ttl = now + (30 * 24 * 60 * 60)  # 30 days

    assignments_table.put_item(
        Item={
            "assignment_id": assignment_id,
            "agent_id": agent_id,
            "source": source,
            "trigger_type": trigger_type,
            "requester": requester,
            "instruction": instruction,
            "status": "dispatched",
            "source_context": source_context,
            "created_at": now,
            "completed_at": None,
            "duration_seconds": None,
            "result_summary": None,
            "token_usage": None,
            "cost_estimate_usd": None,
            "ttl": ttl,
        }
    )
    return assignment_id


def update_assignment(assignment_id: str, **kwargs):
    """Update fields on an existing assignment."""
    update_parts = []
    attr_names = {}
    attr_values = {}

    for key, value in kwargs.items():
        placeholder = f"#{key}"
        value_placeholder = f":{key}"
        update_parts.append(f"{placeholder} = {value_placeholder}")
        attr_names[placeholder] = key
        if isinstance(value, float):
            attr_values[value_placeholder] = Decimal(str(value))
        else:
            attr_values[value_placeholder] = value

    assignments_table.update_item(
        Key={"assignment_id": assignment_id},
        UpdateExpression="SET " + ", ".join(update_parts),
        ExpressionAttributeNames=attr_names,
        ExpressionAttributeValues=attr_values,
    )


# --- Agent Invocation --------------------------------------------------------


def invoke_agent(agent_config: dict, instruction: str, source: str, source_context: dict, assignment_id: str):
    """Invoke an AgentCore Runtime agent."""
    runtime_arn = agent_config["runtime_arn"]

    if "${" in runtime_arn or not runtime_arn.startswith("arn:"):
        raise ValueError(
            f"Agent '{agent_config.get('agent_id', '?')}' has an unresolved runtime_arn "
            f"({runtime_arn!r}). Run scripts/sync_registry.py to substitute placeholders."
        )

    payload = json.dumps({
        "prompt": instruction,
        "session_id": assignment_id,
        "source": source,
        "source_context": source_context,
        "assignment_id": assignment_id,
    }).encode("utf-8")

    agentcore.invoke_agent_runtime(
        agentRuntimeArn=runtime_arn,
        qualifier="DEFAULT",
        contentType="application/json",
        accept="application/json",
        payload=payload,
    )


# --- Guardrail Block Handling ------------------------------------------------


def _put_metric(name: str, dimensions: dict | None = None, value: float = 1.0):
    """Emit a CloudWatch metric. Swallows errors — observability is best-effort."""
    dims = [{"Name": "Stage", "Value": STAGE}]
    if dimensions:
        dims.extend({"Name": k, "Value": v} for k, v in dimensions.items())
    try:
        cloudwatch.put_metric_data(
            Namespace=CLOUDWATCH_NAMESPACE,
            MetricData=[{"MetricName": name, "Dimensions": dims, "Value": value, "Unit": "Count"}],
        )
    except Exception as exc:
        logger.warning("Failed to emit metric %s: %s", name, exc)


def _post_block_reply(source: str, source_context: dict, message: str) -> bool:
    """Post the block-notice message to the originating thread. Returns True on success."""
    if source == "github":
        return reply.post_github_comment(
            repo=source_context.get("repo", ""),
            issue_number=source_context.get("issue_number", ""),
            body=message,
        )
    if source == "asana":
        return reply.post_asana_comment(
            task_gid=source_context.get("task_gid", ""),
            body=message,
        )
    logger.warning("No reply channel for source=%s — block notice not posted", source)
    return False


# --- Lambda Handler ----------------------------------------------------------


def handler(event, context):
    """Dispatch Router Lambda entry point.

    Receives normalized events from:
    - GitHub Actions (via AWS CLI lambda invoke)
    - Asana webhook receiver Lambda (via direct invoke)
    - Slack Events API (via API Gateway)

    Expected event shape:
    {
        "source": "github" | "asana" | "slack",
        "trigger_type": "comment_mention" | "assignment" | "custom_field" | "slash_command",
        "body": "the comment/message text",
        "sender": "username",
        "context": {
            // source-specific context
            "repo": "owner/repo",           // github
            "issue_number": "123",          // github
            "task_gid": "12345",            // asana
            "task_name": "...",             // asana
            "task_notes": "...",            // asana
            "channel_id": "C123",           // slack
            "thread_ts": "...",             // slack
        }
    }
    """
    logger.info("Dispatch event: %s", json.dumps(event))

    registry = load_registry()

    source = event.get("source", "unknown")
    trigger_type = event.get("trigger_type", "comment_mention")
    body = event.get("body", "")
    sender = event.get("sender", "unknown")
    source_context = event.get("context", {})

    # --- Resolve agent ---
    # If agent_id is pre-resolved (e.g. by Asana webhook receiver), use it directly.
    # Otherwise, parse @mention from body.
    pre_resolved_id = event.get("agent_id")
    if pre_resolved_id:
        agents = registry.get("agents", {})
        if pre_resolved_id not in agents:
            return _error(404, f"unknown agent: {pre_resolved_id}")
        agent_config = {**agents[pre_resolved_id], "agent_id": pre_resolved_id}
        instruction = event.get("instruction", body or f"You have been assigned to task: {source_context.get('task_name', 'unknown')}")
    else:
        # --- Parse @mention from body ---
        agent_config, instruction = extract_mention_and_instruction(body, registry)
        if agent_config is None:
            return _error(400, "no recognized @agent mention found")

    agent_id = agent_config["agent_id"]

    # --- Authorization ---
    if not check_authorization(agent_config, sender, source):
        return _error(403, f"user '{sender}' not authorized to invoke @{agent_id}")

    # --- Concurrency ---
    max_concurrent = agent_config.get("limits", {}).get("max_concurrent", 5)
    if not check_concurrency(agent_id, max_concurrent):
        return _error(429, f"@{agent_id} is at capacity ({max_concurrent} active). Try again later.")

    # --- Guardrail (prompt-injection edge check, T-1/T-2/T-3) ---
    # Score the raw `body` — the text the user typed plus any surrounding
    # context that reached this Lambda. We run the check before creating an
    # assignment so a block is cheap and doesn't pollute concurrency counts
    # with aborted dispatches.
    guardrail_input = body or instruction
    guardrail_result = guardrail.check_prompt(guardrail_input)

    if guardrail_result.outcome == "blocked":
        assignment_id = create_assignment(
            agent_id=agent_id,
            source=source,
            trigger_type=trigger_type,
            requester=sender,
            instruction=instruction,
            source_context=source_context,
        )
        update_assignment(
            assignment_id,
            status="blocked_guardrail",
            result_summary=f"guardrail intervened: {guardrail_result.reason}",
            completed_at=int(time.time()),
        )
        _put_metric("GuardrailTripped", dimensions={"Source": source, "AgentId": agent_id})
        reason_suffix = f" ({guardrail_result.reason})" if guardrail_result.reason else ""
        message = BLOCKED_MESSAGE_TEMPLATE.format(
            reason_suffix=reason_suffix,
            assignment_id=assignment_id,
        )
        if not _post_block_reply(source, source_context, message):
            _put_metric("GuardrailReplyFailed", dimensions={"Source": source})
        return _error(400, f"@{agent_id} request blocked by guardrail: {guardrail_result.reason}")

    if guardrail_result.outcome == "error":
        assignment_id = create_assignment(
            agent_id=agent_id,
            source=source,
            trigger_type=trigger_type,
            requester=sender,
            instruction=instruction,
            source_context=source_context,
        )
        update_assignment(
            assignment_id,
            status="blocked_guardrail_error",
            result_summary=f"guardrail check failed: {guardrail_result.reason}",
            completed_at=int(time.time()),
        )
        _put_metric("GuardrailError", dimensions={"Source": source, "Reason": guardrail_result.reason})
        message = GUARDRAIL_ERROR_MESSAGE_TEMPLATE.format(assignment_id=assignment_id)
        if not _post_block_reply(source, source_context, message):
            _put_metric("GuardrailReplyFailed", dimensions={"Source": source})
        return _error(503, f"guardrail check failed: {guardrail_result.reason}")

    # --- Record assignment ---
    assignment_id = create_assignment(
        agent_id=agent_id,
        source=source,
        trigger_type=trigger_type,
        requester=sender,
        instruction=instruction,
        source_context=source_context,
    )

    # --- Invoke agent ---
    try:
        invoke_agent(agent_config, instruction, source, source_context, assignment_id)
    except Exception as e:
        logger.error("Failed to invoke agent %s: %s", agent_id, e)
        update_assignment(assignment_id, status="failed", result_summary=str(e))
        return _error(500, f"failed to invoke @{agent_id}: {e}")

    logger.info("Dispatched assignment %s to %s", assignment_id, agent_id)

    return {
        "statusCode": 200,
        "body": json.dumps(
            {
                "assignment_id": assignment_id,
                "agent_id": agent_id,
                "status": "dispatched",
                "message": f"@{agent_id} is on it. Assignment: {assignment_id}",
            }
        ),
    }


def _error(status: int, message: str) -> dict:
    logger.warning("Dispatch error %d: %s", status, message)
    return {
        "statusCode": status,
        "body": json.dumps({"error": message}),
    }
