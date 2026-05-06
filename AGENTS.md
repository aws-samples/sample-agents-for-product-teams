# PDLC Agent Fleet — Setup Guide for AI Agents

This guide is written for an AI agent tasked with deploying this fleet into a new repository and AWS environment. Follow it top to bottom. Where a decision is required, stop and ask the user before proceeding.

---

## Step 0 — Understand what this fleet is

This repo contains autonomous AI agents for the software development lifecycle, deployed as containers on **Amazon Bedrock AgentCore Runtime**. A **Dispatch Router** Lambda receives `@mention` events from GitHub, Asana, and Slack, resolves them to agents, and invokes the appropriate AgentCore Runtime.

**Agents available:**

| Agent | Role | Trigger aliases |
|-------|------|-----------------|
| `workitems` | PO/PM — work decomposition, status reports, risk | `@pm`, `@status`, `@plan` |
| `docwriter` | Technical writer — API docs, guides, release notes | `@docs`, `@doc`, `@writer` |
| `researcher` | Business analyst — research, competitive intel | `@ba`, `@research`, `@analyze` |
| `adr` | ADR linker — tags issues and reviews PRs against the ADR library | `@decisions`, `@architecture` |

Each deployed agent requires: an ECR repository, an AgentCore Runtime, and an entry in `.dispatch/agents.yaml`.

---

## Step 1 — Ask the user which agents to deploy

**Stop here. Ask the user:**

> Which agents do you want to deploy? Options are:
> - `workitems` (PO/PM assistant)
> - `docwriter` (technical writer)
> - `researcher` (business analyst)
> - `adr` (ADR linker)
>
> You can deploy any combination. Each one adds an ECR repo, an AgentCore Runtime, a deploy workflow, and an entry in the agent registry.

Record the user's answer. For the rest of this guide, replace `<AGENTS>` with the chosen list (e.g. `workitems docwriter`).

---

## Step 2 — Collect required values

Before touching any AWS resources, collect the following. Ask the user for any you don't have.

**AWS:**
- `AWS_ACCOUNT_ID` — 12-digit AWS account ID
- `AWS_REGION` — deployment region (default: `us-west-2`; must have Bedrock model access)
- `GITHUB_ORG` and `GITHUB_REPO` — used to scope the OIDC trust policy
- `STAGE` — environment name: `dev`, `staging`, or `prod` (default: `dev`)

**Asana** (only if the user wants Asana triggers — ask):
- `ASANA_PAT` — Personal Access Token for the Asana service account
- `ASANA_WORKSPACE_GID` — Workspace GID (find at `app.asana.com/api/1.0/workspaces`)
- `WORKITEMS_BOT_GID` — Asana user GID for the Workitems bot account (if deploying Workitems)
- `AGENT_FIELD_GID` — GID of the "Agent" custom field on Asana tasks (create it if it doesn't exist)
- Bot GIDs for any other agents being deployed (`DOCWRITER_BOT_GID`, `RESEARCHER_BOT_GID`)

**Confirm before proceeding.** Summarize what you collected and ask: "Does this look right?"

---

## Step 3 — Bootstrap AWS infrastructure

### 3a. Verify Bedrock model access

```bash
aws bedrock get-foundation-model \
  --model-identifier us.anthropic.claude-opus-4-7-v1 \
  --region $AWS_REGION
```

If this returns a `ResourceNotFoundException`, the user must request access in the AWS Bedrock console under **Model access** before continuing.

### 3b. Deploy shared infrastructure (SAM)

```bash
cd infra/foundation
sam build

sam deploy \
  --stack-name sdlc-agents-${STAGE} \
  --parameter-overrides \
    Stage=${STAGE} \
    WorkitemsBotGID=${WORKITEMS_BOT_GID:-""} \
    AgentFieldGID=${AGENT_FIELD_GID:-""} \
  --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM \
  --region $AWS_REGION \
  --guided   # remove --guided on subsequent deploys
```

This creates:
- DynamoDB table `dispatch-assignments-${STAGE}`
- S3 bucket `sdlc-agent-artifacts-${AWS_ACCOUNT_ID}-${STAGE}`
- Lambda `dispatch-router-${STAGE}`
- Lambda `asana-webhook-${STAGE}` + API Gateway endpoint (for Asana)
- IAM role `GitHubActionsDeployRole` with OIDC trust (used by all deploy workflows)

After deploy, capture these outputs:
```bash
sam list stack-outputs --stack-name sdlc-agents-${STAGE} --region $AWS_REGION
```

Key outputs to save:
- `DeployRoleArn` → set as `AWS_DEPLOY_ROLE_ARN` GitHub secret
- `AsanaWebhookUrl` → register with Asana in Step 6

### 3c. Store secrets in SSM

```bash
# Asana PAT (if using Asana triggers)
aws ssm put-parameter \
  --name /sdlc-agents/asana-pat \
  --value "$ASANA_PAT" \
  --type SecureString \
  --region $AWS_REGION

# Webhook secret is auto-populated by the Lambda on first Asana handshake
```

### 3d. Create ECR repositories

One per agent being deployed:

```bash
for agent in <AGENTS>; do
  aws ecr create-repository \
    --repository-name sdlc-agents/${agent} \
    --region $AWS_REGION
done
```

---

## Step 4 — Register the agent registry in SSM

The Dispatch Router reads agent configuration from SSM at runtime. After editing `.dispatch/agents.yaml` (Step 5), sync it:

```bash
aws ssm put-parameter \
  --name /sdlc-agents/${STAGE}/registry \
  --value "$(cat .dispatch/agents.yaml)" \
  --type String \
  --overwrite \
  --region $AWS_REGION
```

---

## Step 5 — Configure .dispatch/agents.yaml

Edit `.dispatch/agents.yaml`. For each agent being deployed:

1. Uncomment or add its entry
2. Set `runtime_arn` to `"${AGENT_RUNTIME_ARN}"` — this is a placeholder; the actual ARN is filled in after the first deploy (Step 7)
3. Set `authorization.users` to `["*"]` for open access, or list specific GitHub/Asana usernames

**Remove or comment out agents that are NOT being deployed.** The Dispatch Router will return a 404 for any mention of an unregistered agent.

For agents using Asana assignment triggers, set the bot GID environment variables in `infra/foundation/template.yaml`:
```yaml
Environment:
  Variables:
    WORKITEMS_BOT_GID: !Ref WorkitemsBotGID
    DOCWRITER_BOT_GID: !Ref DocwriterBotGID   # add parameter if needed
```

---

## Step 6 — Configure GitHub repository secrets

Go to the repo **Settings → Secrets and variables → Actions** and add:

| Secret | Value | Required |
|--------|-------|----------|
| `AWS_DEPLOY_ROLE_ARN` | ARN from SAM output `DeployRoleArn` | Always |
| `AWS_ACCOUNT_ID` | 12-digit account ID | Always |

The deploy workflows use OIDC — no long-lived AWS credentials are stored in GitHub.

**Verify OIDC is configured.** The SAM template creates the OIDC provider and trust policy automatically, scoped to this repo. If you're deploying to an account where the OIDC provider already exists, the CloudFormation create will fail — check the SAM template and handle accordingly (the provider is idempotent with `AWS::IAM::OIDCProvider` using `DeletionPolicy: Retain`).

---

## Step 7 — Add deploy workflows for chosen agents

For each agent in `<AGENTS>`, verify a deploy workflow exists at `.github/workflows/deploy-<agent>.yml`. If one is missing, create it by copying the pattern:

```yaml
name: Deploy <Agent> Agent

on:
  push:
    branches: [main]
    paths:
      - "agents/<agent>/**"
      - "agents/shared/**"

jobs:
  deploy:
    uses: ./.github/workflows/deploy-agent.yml
    with:
      agent_name: <agent>
    secrets: inherit
```

The shared `deploy-agent.yml` workflow:
1. Builds the container from `agents/<agent>/Dockerfile`
2. Pushes to ECR (`sdlc-agents/<agent>`)
3. Runs Amazon Inspector security scan
4. Calls `aws bedrock-agentcore-control update-agent-runtime` to deploy
5. Waits for the runtime to become active
6. Runs a smoke test (`{"prompt": "health check"}`)

The deploy workflow (`.github/workflows/deploy-agent.yml`) creates the AgentCore Runtime on the first push and updates it on subsequent pushes — no manual `create-agent-runtime` step is needed. It uses the commit SHA as the image tag (ECR repositories are `IMMUTABLE` in this fleet). The runtime ARN is written back to `.dispatch/agents.yaml` by `scripts/sync_registry.py`, which runs as part of the deploy workflow.

To inspect an agent's runtime ARN later (e.g. for debugging):

```bash
aws bedrock-agentcore-control get-agent-runtime \
  --agent-runtime-name <agent> \
  --region $AWS_REGION \
  --query 'agentRuntimeArn' --output text
```

---

## Step 8 — Configure Asana integration (if applicable)

**Ask the user:** "Do you want Asana triggers? This lets users assign tasks to agents or mention them in Asana comments."

If yes:

### 8a. Create bot accounts in Asana

For each agent being deployed with Asana triggers, create a dedicated Asana user account (e.g. `workitems-bot@yourorg.com`). These are the accounts users will "assign" tasks to in order to trigger agents.

Retrieve each bot's GID:
```bash
curl -s "https://app.asana.com/api/1.0/users/workitems-bot@yourorg.com" \
  -H "Authorization: Bearer $ASANA_PAT" | jq -r '.data.gid'
```

### 8b. Create the "Agent" custom field (for custom_field triggers)

In Asana, create an Enum custom field called **Agent** with values matching each deployed agent name (`workitems`, `docwriter`, `researcher`). Retrieve its GID from the workspace:

```bash
curl -s "https://app.asana.com/api/1.0/workspaces/$ASANA_WORKSPACE_GID/custom_fields" \
  -H "Authorization: Bearer $ASANA_PAT" | jq '.data[] | select(.name=="Agent") | .gid'
```

### 8c. Register the webhook

The Asana webhook URL is the API Gateway endpoint from Step 3b (`AsanaWebhookUrl` output).

```bash
curl -X POST "https://app.asana.com/api/1.0/webhooks" \
  -H "Authorization: Bearer $ASANA_PAT" \
  -H "Content-Type: application/json" \
  -d "{
    \"data\": {
      \"resource\": \"$ASANA_WORKSPACE_GID\",
      \"target\": \"$ASANA_WEBHOOK_URL\",
      \"filters\": [
        {\"resource_type\": \"story\", \"action\": \"added\"},
        {\"resource_type\": \"task\", \"action\": \"changed\", \"fields\": [\"assignee\", \"custom_fields\"]}
      ]
    }
  }"
```

Asana will send a handshake request immediately. The Lambda handles it automatically and stores the webhook secret in SSM. Verify in CloudWatch Logs for the `asana-webhook-${STAGE}` function.

---

## Step 9 — Configure GitHub @claude integration (optional)

**Ask the user:** "Do you want `@claude` to work in GitHub comments and PRs? This uses the `claude-code.yml` workflow."

If yes, no extra setup is needed — the workflow uses the same `AWS_DEPLOY_ROLE_ARN` secret and Bedrock OIDC access that was already configured. The IAM role needs `bedrock:InvokeModel` for `us.anthropic.claude-opus-4-7-v1`.

To verify the permission is in place:
```bash
aws iam simulate-principal-policy \
  --policy-source-arn $DEPLOY_ROLE_ARN \
  --action-names bedrock:InvokeModel \
  --resource-arns "arn:aws:bedrock:${AWS_REGION}::foundation-model/us.anthropic.claude-opus-4-7-v1"
```

---

## Step 10 — Trigger first deploy

Commit all changes and push to `main`. The deploy workflows will trigger for each agent whose files changed.

```bash
git add .dispatch/agents.yaml .github/workflows/ infra/
git commit -m "Configure agent fleet for deployment"
git push origin main
```

Monitor the Actions tab. Each agent deploy runs: build → scan → deploy → smoke test.

After all deploys succeed:
1. Update `.dispatch/agents.yaml` with the real `runtime_arn` values (from Step 7)
2. Re-sync the registry: `aws ssm put-parameter --name /sdlc-agents/${STAGE}/registry --value "$(cat .dispatch/agents.yaml)" --type String --overwrite`
3. Test end-to-end by commenting `@workitems health check` on a GitHub issue

---

## Verification checklist

Before reporting the setup as complete, confirm each of the following:

- [ ] `sam deploy` completed without errors
- [ ] ECR repos exist for all chosen agents
- [ ] AgentCore Runtimes are in `ACTIVE` state
- [ ] `.dispatch/agents.yaml` has real `runtime_arn` values (no `${...}` placeholders)
- [ ] SSM parameter `/sdlc-agents/${STAGE}/registry` is populated
- [ ] GitHub secrets `AWS_DEPLOY_ROLE_ARN` and `AWS_ACCOUNT_ID` are set
- [ ] At least one deploy workflow has run and passed
- [ ] Smoke test passed (the deploy workflow runs it automatically)
- [ ] If Asana: webhook registered and handshake logged in CloudWatch
- [ ] If Asana: bot GIDs stored in SSM / Lambda environment variables
- [ ] `@claude` works on a test comment (if configured)

---

## Troubleshooting

**Deploy workflow fails at "Deploy to AgentCore Runtime"**
The Runtime must be created manually before the first CI deploy — `update-agent-runtime` cannot create a new one. Run the `create-agent-runtime` command from Step 7.

**Dispatch Router returns 404 for a known agent**
The SSM registry is stale or missing the agent entry. Re-run the `ssm put-parameter` command from Step 4.

**Asana webhook not triggering**
Check CloudWatch Logs for `asana-webhook-${STAGE}`. Common causes: webhook not registered, signature mismatch (SSM secret out of sync), or the Lambda's API Gateway URL changed after a stack update.

**Smoke test fails with "no recognized @agent mention"**
The registry doesn't include the agent yet, or the runtime ARN is still a placeholder. Check `.dispatch/agents.yaml` and re-sync SSM.

**`@claude` workflow fails with access denied on Bedrock**
The IAM role needs `bedrock:InvokeModel` permission. Check the SAM template's `GitHubActionsDeployRole` policy and redeploy if needed.
