"""One-shot Asana webhook registration with temporary IAM grant.

Asana's webhook protocol captures a shared secret via a handshake: Asana
generates the secret, POSTs it to the configured webhook URL as an
``X-Hook-Secret`` header, and the receiver echoes it back. The receiver must
then persist the secret so it can validate subsequent HMAC signatures.

In the shipping architecture the asana-webhook Lambda does not hold
``ssm:PutParameter`` in steady state (threat T-9): a Lambda role that can
overwrite the webhook secret is a path an attacker can abuse to replace the
secret with attacker-controlled bytes and validate forged inbound events.

This script mediates the registration window:

    1. Attach a temporary inline ``ssm:PutParameter`` policy to the Lambda's
       role, scoped to the single webhook-secret parameter.
    2. Call the Asana webhooks API to register the webhook. Asana immediately
       POSTs the handshake; the Lambda captures the secret to SSM.
    3. Poll the SSM parameter until the secret lands (or time out).
    4. Detach the inline policy. The Lambda returns to steady state — a
       subsequent ``x-hook-secret`` request receives a 403.

Usage:

    python scripts/bootstrap_asana_webhook.py \\
        --stage dev \\
        --region us-west-2 \\
        --resource-gid <project_or_workspace_gid>

Requires operator AWS credentials with ``iam:PutRolePolicy`` and
``iam:DeleteRolePolicy`` on the Lambda's execution role. The Asana PAT is
read from ``/sdlc-agents/asana-pat``; populate it with
``sdlc-agents-connect-asana`` first.
"""

import argparse
import json
import sys
import time

import boto3
import requests
from botocore.exceptions import ClientError

ASANA_API = "https://app.asana.com/api/1.0"
ASANA_PAT_PARAM = "/sdlc-agents/asana-pat"
WEBHOOK_SECRET_PARAM = "/sdlc-agents/asana-webhook-secret"  # nosec B105 — SSM parameter name, not a credential
INLINE_POLICY_NAME = "TempAsanaWebhookHandshake"
HANDSHAKE_TIMEOUT_SECONDS = 60
HANDSHAKE_POLL_INTERVAL_SECONDS = 2


def get_lambda_role_name(lambda_client, function_name: str) -> str:
    fn = lambda_client.get_function(FunctionName=function_name)
    role_arn = fn["Configuration"]["Role"]
    return role_arn.rsplit("/", 1)[-1]


def webhook_secret_arn(region: str, account_id: str) -> str:
    return f"arn:aws:ssm:{region}:{account_id}:parameter{WEBHOOK_SECRET_PARAM}"


def attach_temporary_policy(iam, role_name: str, region: str, account_id: str) -> None:
    policy_document = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": "ssm:PutParameter",
                "Resource": webhook_secret_arn(region, account_id),
            }
        ],
    }
    iam.put_role_policy(
        RoleName=role_name,
        PolicyName=INLINE_POLICY_NAME,
        PolicyDocument=json.dumps(policy_document),
    )
    print(f"Attached temporary inline policy {INLINE_POLICY_NAME} to {role_name}")


def detach_temporary_policy(iam, role_name: str) -> None:
    try:
        iam.delete_role_policy(RoleName=role_name, PolicyName=INLINE_POLICY_NAME)
        print(f"Removed temporary inline policy from {role_name}")
    except iam.exceptions.NoSuchEntityException:
        print(f"Temporary inline policy already absent on {role_name}")


def read_stored_secret(ssm) -> str | None:
    try:
        resp = ssm.get_parameter(Name=WEBHOOK_SECRET_PARAM, WithDecryption=True)
    except ssm.exceptions.ParameterNotFound:
        return None
    return resp["Parameter"]["Value"]


def register_asana_webhook(pat: str, resource_gid: str, target_url: str) -> dict:
    resp = requests.post(
        f"{ASANA_API}/webhooks",
        headers={"Authorization": f"Bearer {pat}", "Content-Type": "application/json"},
        json={
            "data": {
                "resource": resource_gid,
                "target": target_url,
                "filters": [
                    {"resource_type": "story", "action": "added"},
                    {
                        "resource_type": "task",
                        "action": "changed",
                        "fields": ["assignee", "custom_fields"],
                    },
                ],
            }
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("data", {})


def wait_for_handshake(ssm, baseline: str | None) -> bool:
    deadline = time.time() + HANDSHAKE_TIMEOUT_SECONDS
    while time.time() < deadline:
        current = read_stored_secret(ssm)
        if current and current != baseline:
            return True
        time.sleep(HANDSHAKE_POLL_INTERVAL_SECONDS)  # nosemgrep: arbitrary-sleep — bounded poll for handshake
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stage", required=True, help="e.g. dev, staging, prod")
    parser.add_argument("--region", required=True, help="AWS region of the fleet")
    parser.add_argument(
        "--resource-gid",
        required=True,
        help="Asana project or workspace GID to subscribe to",
    )
    parser.add_argument(
        "--function-name",
        default=None,
        help="Override Lambda name (default: asana-webhook-${stage})",
    )
    parser.add_argument(
        "--stack-name",
        default=None,
        help="Override CloudFormation stack name (default: sdlc-agents-${stage})",
    )
    args = parser.parse_args()

    function_name = args.function_name or f"asana-webhook-{args.stage}"
    stack_name = args.stack_name or f"sdlc-agents-{args.stage}"

    session = boto3.Session(region_name=args.region)
    lambda_client = session.client("lambda")
    iam = session.client("iam")
    ssm = session.client("ssm")
    cfn = session.client("cloudformation")
    sts = session.client("sts")

    account_id = sts.get_caller_identity()["Account"]

    stack = cfn.describe_stacks(StackName=stack_name)["Stacks"][0]
    webhook_url = next(
        (o["OutputValue"] for o in stack.get("Outputs", []) if o["OutputKey"] == "WebhookEndpoint"),
        None,
    )
    if not webhook_url:
        print(f"WebhookEndpoint output not found on stack {stack_name}", file=sys.stderr)
        return 1

    pat = ssm.get_parameter(Name=ASANA_PAT_PARAM, WithDecryption=True)["Parameter"]["Value"]
    role_name = get_lambda_role_name(lambda_client, function_name)
    baseline_secret = read_stored_secret(ssm)

    print(f"Target Lambda role : {role_name}")
    print(f"Target webhook URL : {webhook_url}")
    print(f"Asana resource GID : {args.resource_gid}")

    attach_temporary_policy(iam, role_name, args.region, account_id)
    try:
        # IAM propagation is eventually consistent; give it a beat before
        # Asana sends the handshake.
        time.sleep(5)  # nosemgrep: arbitrary-sleep — IAM propagation delay before Asana handshake
        webhook = register_asana_webhook(pat, args.resource_gid, webhook_url)
        webhook_gid = webhook.get("gid", "<unknown>")
        print(f"Asana webhook registered: gid={webhook_gid}")

        if not wait_for_handshake(ssm, baseline_secret):
            print(
                "Timed out waiting for handshake to populate "
                f"{WEBHOOK_SECRET_PARAM}. Check Lambda CloudWatch logs for "
                "the handshake attempt and delete the webhook before retrying.",
                file=sys.stderr,
            )
            return 2
        stored = read_stored_secret(ssm)
        if not stored:
            print(
                f"Handshake write to {WEBHOOK_SECRET_PARAM} returned an empty "
                "value. Refusing to finish — the webhook Lambda fails closed on "
                "empty secrets. Delete the Asana webhook and retry.",
                file=sys.stderr,
            )
            return 4
        print(f"Handshake captured; {WEBHOOK_SECRET_PARAM} updated")
    except ClientError as e:
        print(f"Bootstrap failed: {e}", file=sys.stderr)
        return 3
    finally:
        detach_temporary_policy(iam, role_name)

    print("Done. Verify with: aws asana webhooks GET or via the fleet's verify skill.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
