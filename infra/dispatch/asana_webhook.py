"""Asana Webhook Receiver Lambda.

Handles incoming Asana webhook events and forwards recognized agent triggers
to the Dispatch Router. Sits behind API Gateway with a public HTTPS endpoint.

Three trigger types:
1. Comment mention — user comments "@workitems break this into issues" on a task
2. Task assignment — user assigns a task to a bot account (e.g. workitems-bot)
3. Custom field — user sets the "Agent" dropdown to "Workitems"

Also handles the Asana handshake protocol for webhook registration.
"""

import hashlib
import hmac
import json
import logging
import os
import re

import boto3
import requests

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# --- Configuration -----------------------------------------------------------

DISPATCH_FUNCTION = os.environ.get("DISPATCH_FUNCTION", "dispatch-router")

# Secrets are fetched at invocation time, not at cold start. Retaining the
# Asana PAT in a module-level global across invocations widens the exposure
# window of a memory-disclosure or verbose-log incident (threat T-8).
_ssm = boto3.client("ssm")


def _get_ssm_param(name: str) -> str:
    resp = _ssm.get_parameter(Name=name, WithDecryption=True)
    return resp["Parameter"]["Value"]


ASANA_PAT_PARAM = os.environ.get("ASANA_PAT_PARAM", "/sdlc-agents/asana-pat")
ASANA_WEBHOOK_SECRET_PARAM = os.environ.get("ASANA_WEBHOOK_SECRET_PARAM", "/sdlc-agents/asana-webhook-secret")
ASANA_BASE_URL = "https://app.asana.com/api/1.0"

lambda_client = boto3.client("lambda")

# --- Agent Resolution --------------------------------------------------------

MENTION_PATTERN = re.compile(
    r"@(workitems|uat|researcher|docwriter|feedback|merge|triage|adr|pm|status|plan|qa|test|ba|research|analyze|docs|doc|writer)\b",
    re.IGNORECASE,
)

ALIAS_MAP = {
    "pm": "workitems",
    "status": "workitems",
    "plan": "workitems",
    "qa": "uat",
    "test": "uat",
    "ba": "researcher",
    "research": "researcher",
    "analyze": "researcher",
    "docs": "docwriter",
    "doc": "docwriter",
    "writer": "docwriter",
}

# Bot user GIDs in Asana — set via environment variables
BOT_USERS = {
    os.environ.get("WORKITEMS_BOT_GID", ""): "workitems",
    os.environ.get("UAT_BOT_GID", ""): "uat",
    os.environ.get("RESEARCHER_BOT_GID", ""): "researcher",
    os.environ.get("DOCWRITER_BOT_GID", ""): "docwriter",
}

# Custom field GID for the "Agent" dropdown
AGENT_FIELD_GID = os.environ.get("AGENT_FIELD_GID", "")

AGENT_FIELD_VALUES = {
    "workitems": "workitems",
    "uat": "uat",
    "researcher": "researcher",
    "docwriter": "docwriter",
}


# --- Asana API Helpers -------------------------------------------------------


def asana_get(path: str, invocation_state: dict) -> dict:
    """Make an authenticated GET request to the Asana API.

    The PAT is fetched once per Lambda invocation and held only in the
    `invocation_state` dict, which goes out of scope when the handler returns.
    """
    pat = invocation_state.get("asana_pat")
    if pat is None:
        pat = _get_ssm_param(ASANA_PAT_PARAM)
        invocation_state["asana_pat"] = pat

    resp = requests.get(
        f"{ASANA_BASE_URL}{path}",
        headers={"Authorization": f"Bearer {pat}"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json().get("data", {})


def get_task(task_gid: str, invocation_state: dict) -> dict:
    return asana_get(f"/tasks/{task_gid}", invocation_state)


def get_story(story_gid: str, invocation_state: dict) -> dict:
    return asana_get(f"/stories/{story_gid}", invocation_state)


# --- Dispatch ----------------------------------------------------------------


def dispatch(agent_id: str, trigger_type: str, instruction: str, context: dict, sender: str):
    """Forward a resolved event to the Dispatch Router Lambda."""
    payload = {
        "source": "asana",
        "trigger_type": trigger_type,
        "agent_id": agent_id,
        "body": instruction,
        "instruction": instruction,
        "sender": sender,
        "context": context,
    }

    logger.info("Dispatching to %s: %s", agent_id, trigger_type)

    lambda_client.invoke(
        FunctionName=DISPATCH_FUNCTION,
        InvocationType="Event",  # async — don't block the webhook response
        Payload=json.dumps(payload).encode(),
    )


# --- Event Processors --------------------------------------------------------


def process_comment_mention(event_data: dict, invocation_state: dict):
    """Handle a new comment (story) on a task. Check for @agent mention."""
    story_gid = event_data.get("resource", {}).get("gid")
    parent_gid = event_data.get("parent", {}).get("gid")

    if not story_gid or not parent_gid:
        return

    story = get_story(story_gid, invocation_state)
    text = story.get("text", "")
    # sender must be a stable, non-editable identifier — Asana display names are
    # self-editable and non-unique, so matching on .name in the allowlist would
    # be an auth bypass. .gid is immutable per user. (Threat T-4.)
    sender = story.get("created_by", {}).get("gid", "")

    match = MENTION_PATTERN.search(text)
    if not match:
        return

    agent_id = match.group(1).lower()
    agent_id = ALIAS_MAP.get(agent_id, agent_id)
    instruction = text[match.end() :].strip()

    # If no explicit instruction, the instruction is "you were mentioned on this task"
    if not instruction:
        instruction = f"You were mentioned on Asana task. Review it and determine what action to take."

    task = get_task(parent_gid, invocation_state)

    dispatch(
        agent_id=agent_id,
        trigger_type="comment_mention",
        instruction=instruction,
        sender=sender,
        context=_build_task_context(task, parent_gid),
    )


def process_assignment(event_data: dict, invocation_state: dict):
    """Handle a task being assigned to a bot user account."""
    task_gid = event_data.get("resource", {}).get("gid")
    if not task_gid:
        return

    task = get_task(task_gid, invocation_state)
    assignee_gid = task.get("assignee", {}).get("gid", "")
    agent_id = BOT_USERS.get(assignee_gid)

    if not agent_id:
        return  # Not assigned to a known bot

    dispatch(
        agent_id=agent_id,
        trigger_type="assignment",
        instruction=f"You have been assigned to this Asana task. Read it and take appropriate action.",
        # sender matches the allowlist — must be the immutable .gid, not .name
        sender=assignee_gid,
        context=_build_task_context(task, task_gid),
    )


def process_custom_field(event_data: dict, invocation_state: dict):
    """Handle the 'Agent' custom field being set on a task."""
    task_gid = event_data.get("resource", {}).get("gid")
    if not task_gid:
        return

    task = get_task(task_gid, invocation_state)

    # Find the Agent custom field value
    agent_id = None
    for field in task.get("custom_fields", []):
        if field.get("gid") == AGENT_FIELD_GID:
            enum_value = field.get("enum_value", {})
            if enum_value:
                field_name = enum_value.get("name", "").lower()
                agent_id = AGENT_FIELD_VALUES.get(field_name)
            break

    if not agent_id:
        return

    dispatch(
        agent_id=agent_id,
        trigger_type="custom_field",
        instruction=f"The Agent field was set to '{agent_id}' on this Asana task. Read it and take appropriate action.",
        sender="asana_rule",
        context=_build_task_context(task, task_gid),
    )


def _build_task_context(task: dict, task_gid: str) -> dict:
    """Build a standardized context dict from an Asana task."""
    projects = task.get("projects", [])
    assignee = task.get("assignee") or {}
    return {
        "task_gid": task_gid,
        "task_name": task.get("name", ""),
        "task_notes": task.get("notes", ""),
        "task_assignee_gid": assignee.get("gid") or None,
        "task_assignee_name": assignee.get("name") or None,
        "task_due_on": task.get("due_on"),
        "task_custom_fields": [
            {"name": f.get("name"), "value": f.get("display_value")}
            for f in task.get("custom_fields", [])
            if f.get("display_value")
        ],
        "project_gid": projects[0].get("gid") if projects else None,
        "project_name": projects[0].get("name") if projects else None,
    }


# --- Lambda Handler ----------------------------------------------------------


def handler(event, context):
    """Asana Webhook Receiver Lambda entry point.

    Fronted by API Gateway. Handles:
    1. Webhook handshake (X-Hook-Secret header) — only succeeds when the
       Lambda role has been temporarily granted ssm:PutParameter by the
       operator running scripts/bootstrap_asana_webhook.py (threat T-9).
    2. Event delivery (signed payload with events array)
    """
    # Secrets and derived state live on this dict, not on module globals.
    # It goes out of scope when the handler returns (threat T-8).
    invocation_state: dict = {}

    headers = event.get("headers", {})
    # Normalize header keys to lowercase
    headers = {k.lower(): v for k, v in headers.items()}
    body = event.get("body", "")

    # --- Asana handshake protocol ---
    hook_secret = headers.get("x-hook-secret")
    if hook_secret:
        logger.info("Asana webhook handshake received")
        try:
            _ssm.put_parameter(
                Name=ASANA_WEBHOOK_SECRET_PARAM,
                Value=hook_secret,
                Type="SecureString",
                Overwrite=True,
            )
        except _ssm.exceptions.ClientError as e:
            # The Lambda role lacks ssm:PutParameter in steady state. The
            # operator must run scripts/bootstrap_asana_webhook.py to attach
            # a temporary inline grant for the registration window.
            logger.error(
                "Handshake PutParameter denied: %s. Run scripts/bootstrap_asana_webhook.py "
                "with operator credentials to register the webhook.",
                e,
            )
            return {"statusCode": 403, "body": "handshake not permitted in steady state"}
        return {
            "statusCode": 200,
            "headers": {"X-Hook-Secret": hook_secret},
            "body": "",
        }

    # --- Verify webhook signature ---
    # Hard-fail on missing/empty secret. SSM SecureString rejects empty values
    # in practice, but contracting on it here keeps a misconfigured stage from
    # silently accepting unsigned events.
    try:
        webhook_secret = _get_ssm_param(ASANA_WEBHOOK_SECRET_PARAM)
    except _ssm.exceptions.ParameterNotFound:
        logger.error(
            "Webhook secret parameter %s not found. Run "
            "scripts/bootstrap_asana_webhook.py to register the webhook.",
            ASANA_WEBHOOK_SECRET_PARAM,
        )
        return {"statusCode": 503, "body": "webhook not registered"}
    if not webhook_secret:
        logger.error("Webhook secret %s is empty; refusing to process events.", ASANA_WEBHOOK_SECRET_PARAM)
        return {"statusCode": 503, "body": "webhook not registered"}
    signature = headers.get("x-hook-signature", "")
    expected = hmac.new(
        webhook_secret.encode(), body.encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        logger.warning("Invalid webhook signature")
        return {"statusCode": 401, "body": "invalid signature"}

    # --- Process events ---
    try:
        payload = json.loads(body) if isinstance(body, str) else body
    except json.JSONDecodeError:
        return {"statusCode": 400, "body": "invalid JSON"}

    events = payload.get("events", [])
    logger.info("Processing %d Asana events", len(events))

    failures: list[str] = []
    for event_data in events:
        resource_type = event_data.get("resource", {}).get("resource_type")
        action = event_data.get("action")
        change_field = event_data.get("change", {}).get("field", "")

        try:
            if resource_type == "story" and action == "added":
                process_comment_mention(event_data, invocation_state)
            elif resource_type == "task" and action == "changed":
                if change_field == "assignee":
                    process_assignment(event_data, invocation_state)
                elif change_field == "custom_fields":
                    process_custom_field(event_data, invocation_state)
        except Exception as e:
            logger.exception("Error processing event: %s", json.dumps(event_data))
            failures.append(f"{resource_type}/{action}: {e}")

    if failures:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "one or more events failed", "failures": failures}),
        }
    return {"statusCode": 200, "body": "ok"}
