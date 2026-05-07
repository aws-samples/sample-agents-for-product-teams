---
name: sdlc-agents-register-triggers
description: Use when the user's agents are provisioned and integrations are connected, and they need to enable the event triggers that make agents actually respond to @mentions. Registers Asana webhooks, enables the GitHub Actions dispatch workflow, configures Slack app event subscriptions, and updates the dispatch router Lambda environment for the selected agents. Invoked by sdlc-agents after the connect skills finish.
---

# Wire up event triggers so agents respond to mentions

## Prerequisites

- `.sdlc-agents/selection.yaml` has the agent list, toolchain, and GIDs captured by the connect skills
- The shared foundation stack is deployed (`dispatch-router-${STAGE}` Lambda + `asana-webhook-${STAGE}` Lambda + API Gateway exist)
- The first successful CI deploy of each selected agent has completed — `deploy-agent.yml` creates the AgentCore Runtime and then runs `scripts/sync_registry.py` automatically, so at this point `.dispatch/agents.yaml` has the runtime ARNs and the SSM registry is current. If you're re-running this skill after changing the agent selection, re-run `python scripts/sync_registry.py --stage $STAGE --region $REGION` manually before proceeding.

## Per-integration wiring

### Asana

#### 1. Update the webhook Lambda's environment

The Lambda reads the "Agent" custom field GID and bot user GIDs from its environment. Swap them to the customer's values:

```bash
aws lambda update-function-configuration \
  --function-name "asana-webhook-${STAGE}" \
  --environment "Variables={
    ASANA_WEBHOOK_SECRET_PARAM=/sdlc-agents/asana-webhook-secret,
    ASANA_PAT_PARAM=/sdlc-agents/asana-pat,
    DISPATCH_FUNCTION=dispatch-router-${STAGE},
    AGENT_FIELD_GID=<from selection.yaml asana.agent_field_gid>,
    WORKITEMS_BOT_GID=<asana user gid the Workitems agent should act as>
    }" \
  --region "$REGION"
```

If the user has agents beyond workitems (`docwriter`, `researcher`) and wants assignment-based triggers for them, add `DOCWRITER_BOT_GID` and `RESEARCHER_BOT_GID` as separate bot users. For dev/demo, the user's own Asana GID is fine for all of them.

#### 2. Redeploy the Lambda code if this is a fresh install

If the webhook Lambda was deployed before your agent list or alias map changed, rebuild its zip and push:

```bash
cd infra/dispatch
pip install --quiet --target /tmp/lambda-build -r requirements.txt
cp asana_webhook.py router.py /tmp/lambda-build/
(cd /tmp/lambda-build && zip -rq /tmp/asana-webhook.zip . -x '*.pyc' -x '__pycache__/*')
aws lambda update-function-code \
  --function-name "asana-webhook-${STAGE}" \
  --zip-file fileb:///tmp/asana-webhook.zip \
  --region "$REGION"
```

Wait for `LastUpdateStatus=Successful` before proceeding.

#### 3. Register the Asana webhook

Registration is handled by `scripts/bootstrap_asana_webhook.py`. The script mediates the Asana handshake: in steady state the webhook Lambda's IAM role does **not** hold `ssm:PutParameter` on the webhook-secret parameter (threat T-9 — a Lambda that can overwrite the secret is a foothold for an attacker who can replay the handshake). The script attaches a temporary inline policy for the registration window, calls the Asana webhooks API, waits for the handshake to populate the secret in SSM, and removes the inline policy.

Choose a scope:

- **Workspace-scoped** (all tasks across all projects): pass the workspace GID. Filters must match Asana's whitelist — `story.added` and `task.changed[assignee, custom_fields]` are known to work.
- **Project-scoped** (one specific project): pass the project GID. Recommended for demos. If the user has multiple projects, register one webhook per project.

Run the script with operator credentials (needs `iam:PutRolePolicy` / `iam:DeleteRolePolicy` on the Lambda's execution role):

```bash
python scripts/bootstrap_asana_webhook.py \
  --stage "$STAGE" \
  --region "$REGION" \
  --resource-gid <project_or_workspace_gid>
```

The script prints the Asana webhook GID on success. If the handshake times out, inspect the Lambda's CloudWatch logs — the most common cause is IAM propagation lag, and a retry usually succeeds. Do NOT re-run the Asana API call by hand with a long-lived elevated Lambda role; that is exactly the posture T-9 closes off.

### GitHub

#### 1. Enable the agent-dispatch workflow

`.github/workflows/agent-dispatch.yml` already exists in the repo. Ensure its trigger list covers the user's selected agents — it's a hardcoded `if:` block:

```yaml
if: |
  contains(github.event.comment.body, '@workitems') ||
  contains(github.event.comment.body, '@docwriter') ||
  ...
```

Add a line for each agent in `.sdlc-agents/selection.yaml`. Commit.

#### 2. Confirm the deploy role OIDC trust is scoped to the target repo

The trust policy for the deploy role is created manually (or via `sdlc-agents-provision-aws`) when you first set up the account — see `docs/aws-deploy.md` §1.3. It should use `StringEquals` on `sub` with two explicit subjects: `repo:<ORG>/<REPO>:ref:refs/heads/main` (covers deploy workflows on `push` to main AND the dispatch workflow's `issue_comment` / `pull_request_review_comment` events, which run in the default-branch context) and `repo:<ORG>/<REPO>:pull_request` (covers `claude-code.yml`'s `pull_request: [opened, synchronize]` trigger — the only true "pull request event" in OIDC terms). If the user is bringing a brand-new repo, the role's trust policy was scoped to a different `<ORG>/<REPO>` — update the role directly (`aws iam update-assume-role-policy`) to add their repo's two subjects, or create a fresh role for them.

### Slack (gap — not yet supported end-to-end)

Slack triggers aren't wired up in the foundation stack or the Dispatch Router yet. If the user has Slack in their toolchain and selected agents that advertise Slack triggers in `.dispatch/agents.yaml`, tell them:

> Slack triggers aren't implemented in this fleet yet. The registry advertises the trigger shape but the foundation stack has no Slack event receiver, and the router has no signature verifier. You can still use your selected agents via Asana/GitHub; the Slack path can be added later.

When support lands, this section should cover:

- Creating a Slack app from a manifest (scopes: `app_mentions:read`, `chat:write`; events: `app_mention`)
- Installing to the workspace and storing the bot token at `/sdlc-agents/slack-bot-token`
- Storing `SLACK_SIGNING_SECRET` for inbound event verification
- Pointing event subscriptions at a new `slack-webhook-${STAGE}` Lambda URL (not yet in the foundation stack)

Don't try to paper over the gap by writing a partial integration — leave it clean so the user knows what does and doesn't work.

## Verify the pipeline

Run `sdlc-agents-verify` to smoke-test each enabled trigger path.

## What this skill does NOT do

- Create Asana bot accounts (those are users, not API resources — user has to invite them manually)
- Configure Asana's "Agent" custom field enum options (that was done in `sdlc-agents-connect-asana`)
- Wire up webhooks for tools the user doesn't have (skip non-selected integrations cleanly)
