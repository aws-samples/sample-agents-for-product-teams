---
name: sdlc-agents-provision-aws
description: Use when the user is ready to provision AWS infrastructure for their selected SDLC agents — IAM runtime roles, ECR repositories, and Bedrock AgentCore Runtimes. Reads the agent selection from .sdlc-agents/selection.yaml. Idempotent. Invoked by sdlc-agents after the user confirms their agent list.
---

# Provision AWS infrastructure for selected agents

## Prerequisites

- `.sdlc-agents/selection.yaml` exists and lists the agents, AWS account ID, region, and stage
- The user's current AWS credentials can reach the target account (`aws sts get-caller-identity` shows the right account)
- Bedrock model access is enabled for the Opus 4.7 cross-region inference profile in the target region (check: `aws bedrock get-inference-profile --inference-profile-identifier us.anthropic.claude-opus-4-7 --region $REGION`). If the call 404s, stop and tell the user to request access in the Bedrock console before continuing.
- The shared foundation stack (`infra/foundation/template.yaml` → `sdlc-agents-${STAGE}`) is deployed. Check by listing the stack; deploy with SAM if missing.

## Step 0 — OIDC provider and deploy role (one-time per AWS account)

The foundation stack does **not** create the GitHub Actions OIDC provider or the deploy role — `docs/aws-deploy.md` §1.3 is the source of truth on this. You create them by hand here the first time the fleet is set up in a given AWS account. Skip this step if the account already has both (common when a different repo in the org previously onboarded).

### 0a. OIDC provider

```bash
aws iam list-open-id-connect-providers \
  | grep -q 'token.actions.githubusercontent.com' \
  || aws iam create-open-id-connect-provider \
       --url https://token.actions.githubusercontent.com \
       --client-id-list sts.amazonaws.com \
       --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1
```

### 0b. Deploy role

Trust policy uses `StringEquals` on two explicit `sub` values — see `docs/aws-deploy.md` §1.3 for the reasoning (do **not** use `StringLike: "repo:<org>/<repo>:*"`, it lets any branch assume the role).

```bash
GH_OWNER=$(yq '.github.owner // ""' "$TARGET_REPO/.sdlc-agents/selection.yaml")
GH_REPO=$(yq '.github.repo // ""' "$TARGET_REPO/.sdlc-agents/selection.yaml")
ACCOUNT_ID=$(yq '.aws.account_id' "$TARGET_REPO/.sdlc-agents/selection.yaml")
# If github.owner/repo aren't in selection.yaml yet (connect-github hasn't
# run), derive them from git -C "$TARGET_REPO" remote get-url origin and
# confirm with the user before writing the trust policy.

cat > /tmp/deploy-trust.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {
      "Federated": "arn:aws:iam::${ACCOUNT_ID}:oidc-provider/token.actions.githubusercontent.com"
    },
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": {
        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
        "token.actions.githubusercontent.com:sub": [
          "repo:${GH_OWNER}/${GH_REPO}:ref:refs/heads/main",
          "repo:${GH_OWNER}/${GH_REPO}:pull_request"
        ]
      }
    }
  }]
}
EOF

aws iam create-role \
  --role-name sdlc-agents-deploy \
  --assume-role-policy-document file:///tmp/deploy-trust.json \
  --description "Assumed by GitHub Actions via OIDC to deploy SDLC agent fleet" \
  || echo "(role exists — if it was created for a different repo, update trust policy)"

rm /tmp/deploy-trust.json
```

Attach the permissions the deploy workflow actually needs. `AdministratorAccess` is the fastest demo path; for production scope down to ECR push, `bedrock-agentcore-control:*` on the specific runtimes, `iam:PassRole` on `<agent>-agentcore-runtime`, and `cloudformation:DescribeStacks` on the foundation stack. See `docs/aws-deploy.md` for the full policy surface.

```bash
aws iam attach-role-policy \
  --role-name sdlc-agents-deploy \
  --policy-arn arn:aws:iam::aws:policy/AdministratorAccess
```

Capture the role ARN — it goes into GitHub Secrets as `AWS_DEPLOY_ROLE_ARN` in Step 5.

```bash
DEPLOY_ROLE_ARN=$(aws iam get-role --role-name sdlc-agents-deploy --query 'Role.Arn' --output text)
echo "$DEPLOY_ROLE_ARN"
```

If the role already existed but was scoped to a different repo, update its trust policy with `aws iam update-assume-role-policy` — or create a fresh role per repo for cleaner blast radius. Never fall back to `StringLike` wildcards.

## For each selected agent, do the following — in order, idempotently

### 1. IAM runtime role

Role name convention: `<agent>-agentcore-runtime`. Trust policy: `bedrock-agentcore.amazonaws.com`.

```bash
aws iam create-role \
  --role-name "${AGENT}-agentcore-runtime" \
  --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"bedrock-agentcore.amazonaws.com"},"Action":"sts:AssumeRole"}]}' \
  --description "AgentCore runtime role for ${AGENT}" \
  || echo "(role already exists, skipping create)"
```

Attach `AmazonBedrockFullAccess` (the runtime needs to invoke Bedrock models):

```bash
aws iam attach-role-policy \
  --role-name "${AGENT}-agentcore-runtime" \
  --policy-arn arn:aws:iam::aws:policy/AmazonBedrockFullAccess
```

Attach the per-agent inline policies matching the agent's tool footprint. Minimum set (all agents):
- `cloudwatch-logs` — create and write to `/aws/bedrock-agentcore/runtimes/*`
- `dynamodb-assignments` — read/write the `dispatch-assignments-${STAGE}` table
- `ecr-pull` — pull the agent's own image

Plus per-agent (shipping agents only):

| Agent | Additional inline policies (name: resources read) |
|---|---|
| `workitems` | `ssm-read-asana-mcp` (`/sdlc-agents/asana-mcp-*`), `ssm-read-asana-pat` (`/sdlc-agents/asana-pat`), `ssm-read-github-mcp` (`/sdlc-agents/github-mcp-*`) |
| `researcher` | `ssm-read-asana-mcp`, `ssm-read-tavily` (`/sdlc-agents/researcher-tavily-api-key`) |
| `docwriter` | `ssm-read-asana-mcp`, `ssm-read-github-mcp` |
| `adr` | `ssm-read-github-mcp` |

Author each policy inline from the scopes above — don't guess at resource ARNs if the agent reads something else. If `sdlc-agents-select` proposed an agent that isn't in this table, stop and tell the user (it means the agent is planned but not shipping, and shouldn't have been selected).

### 2. ECR repository

```bash
aws ecr describe-repositories --repository-names "sdlc-agents/${AGENT}" --region "${REGION}" >/dev/null 2>&1 \
  || aws ecr create-repository \
       --repository-name "sdlc-agents/${AGENT}" \
       --region "${REGION}" \
       --image-scanning-configuration scanOnPush=true \
       --image-tag-mutability IMMUTABLE
```

### 3. AgentCore Runtime

The shared deploy workflow (`.github/workflows/deploy-agent.yml`) does create-or-update when it runs, and it's the only supported path for creating a runtime in this fleet. Confirm the current state before handing off to CI.

Check if it exists:

```bash
aws bedrock-agentcore-control list-agent-runtimes \
  --region "${REGION}" \
  --query "agentRuntimes[?agentRuntimeName=='${AGENT}'].agentRuntimeId | [0]" \
  --output text
```

If it doesn't exist, skip runtime creation here — the deploy workflow (`.github/workflows/deploy-agent.yml`) creates the runtime on first push, pinned to the commit SHA. ECR repositories in this fleet are `IMMUTABLE`, so there is no mutable tag to bootstrap from manually; the only way a runtime gets created is through the deploy pipeline.

### 4. Record the runtime ARN in the dispatch registry

Read `.dispatch/agents.yaml` in the target project. For each provisioned agent, set `runtime_arn` to the value returned by the `list-agent-runtimes` check above if the runtime already exists, or leave it as the `"${<AGENT>_RUNTIME_ARN}"` placeholder if it doesn't — the registry sync will resolve it after the first deploy creates the runtime.

### 5. Publish the per-repo config as GitHub Actions Variables and Secrets

The deploy workflows (`deploy-<agent>.yml`) read several **repository variables** and bake them into the AgentCore Runtime as environment variables. Skipping this step will produce a runtime that starts but `KeyError`s on the first invocation.

All `gh` commands in this step target the **target repo** — run them inside `$TARGET_REPO` or pass `--repo "$GH_OWNER/$GH_REPO"`. Do not set these on the installer repo.

#### Variables

| Variable | Source | Consumed by | Required? |
|---|---|---|---|
| `AWS_REGION` | `selection.yaml → aws.region` | All deploy workflows, `agent-dispatch.yml` | Yes |
| `TARGET_REPO` | `github.yaml → owner` + `repo` (joined as `<owner>/<repo>`) — baked into the runtime as env var `GITHUB_REPO` | `workitems`, `docwriter`, `adr` | Yes, if any of those agents are selected |
| `ASANA_WORKSPACE_GID` | `asana.yaml → workspace_gid` | `workitems`, `docwriter`, `researcher` | Yes, if any of those agents are selected |
| `ASANA_PROJECT_GID` | `asana.yaml → project_gid` | same | Yes, if any of those agents are selected |
| `ASANA_PROJECT_NAME` | `asana.yaml → project_name` | same (cosmetic, shown in prompts) | No |
| `CLAUDE_CODE_AWS_REGION` | operator preference (defaults to `us-east-1`) | `claude-code.yml` | No |

Why `TARGET_REPO` (not `GITHUB_REPO`) is the variable name: GitHub reserves the `GITHUB_` prefix and silently rejects user-defined variables that start with it. Setting a variable named `GITHUB_REPO` with `gh variable set` fails with `422 Variable names cannot start with GITHUB_`. The deploy workflows read `vars.TARGET_REPO` and pass it through to the container as `GITHUB_REPO=...` — the agent Python still reads `os.environ["GITHUB_REPO"]` at runtime.

The deploy workflows reject empty values for the vars listed in `env_vars` — if a required variable isn't set, the workflow fails with a clear `::error::` line telling you which one. Don't add optional vars to `env_vars` unless they're set.

Set each with `gh variable set` (uses the operator's GitHub auth, no PAT required):

```bash
# Read selection.yaml into shell vars (requires yq)
SELECTION="$TARGET_REPO/.sdlc-agents/selection.yaml"
REGION=$(yq '.aws.region' "$SELECTION")
ACCOUNT_ID=$(yq '.aws.account_id' "$SELECTION")
GH_OWNER=$(yq '.github.owner' "$SELECTION")
GH_REPO=$(yq '.github.repo' "$SELECTION")
AS_WORKSPACE=$(yq '.asana.workspace_gid' "$SELECTION")
AS_PROJECT=$(yq '.asana.project_gid' "$SELECTION")
AS_NAME=$(yq '.asana.project_name // ""' "$SELECTION")

# Write them to the target repo's Actions Variables
cd "$TARGET_REPO"
gh variable set AWS_REGION          --body "$REGION"
gh variable set TARGET_REPO         --body "${GH_OWNER}/${GH_REPO}"
gh variable set ASANA_WORKSPACE_GID --body "$AS_WORKSPACE"
gh variable set ASANA_PROJECT_GID   --body "$AS_PROJECT"
[ -n "$AS_NAME" ] && gh variable set ASANA_PROJECT_NAME --body "$AS_NAME"
```

Verify: `gh variable list`. Confirm all required rows are present. If `gh` isn't installed, fall back to the UI: **Repo → Settings → Secrets and variables → Actions → Variables tab**.

Skip any variable whose source is empty (e.g. if the user isn't deploying Asana-using agents, skip the `ASANA_*` trio).

#### Secrets

```bash
gh secret set AWS_DEPLOY_ROLE_ARN --body "$DEPLOY_ROLE_ARN"   # from Step 0b
gh secret set AWS_ACCOUNT_ID      --body "$ACCOUNT_ID"
```

Both are required — the deploy workflow's `aws-actions/configure-aws-credentials` call fails without `AWS_DEPLOY_ROLE_ARN`, and the container build uses `AWS_ACCOUNT_ID` to compose the ECR URI.

## AWS org gotchas to flag

AgentCore is new and AWS org-level SCPs sometimes block `bedrock-agentcore:*` actions even with AdministratorAccess on the role. If `update-agent-runtime` or `delete-agent-runtime` returns `AccessDeniedException`:

- Simulate the policy: `aws iam simulate-principal-policy --policy-source-arn <role> --action-names bedrock-agentcore:UpdateAgentRuntime`
- If simulate shows allowed but the API returns denied, it's an SCP. Tell the user — you can't fix org SCPs from here.
- Workaround: create a new runtime under a different name (e.g. `<agent>_v2`) and update the registry to point at the new ARN. The old runtime stays orphaned until the org unblocks delete.

## When you're done

Output a summary:

```
Provisioned 3 agents in <REGION>:
  workitems:  arn:aws:bedrock-agentcore:<REGION>:…:runtime/workitems-XYZ
  researcher: arn:aws:bedrock-agentcore:<REGION>:…:runtime/researcher-XYZ
  docwriter:  arn:aws:bedrock-agentcore:<REGION>:…:runtime/docwriter-XYZ

GitHub Actions Variables written: AWS_REGION, TARGET_REPO, ASANA_WORKSPACE_GID, ASANA_PROJECT_GID, ASANA_PROJECT_NAME
GitHub Actions Secrets written:   AWS_DEPLOY_ROLE_ARN, AWS_ACCOUNT_ID

Next: connect integrations. Run the matching connect skills for your tools:
  sdlc-agents-connect-asana (your PM)
  sdlc-agents-connect-github (your SCM)
```
