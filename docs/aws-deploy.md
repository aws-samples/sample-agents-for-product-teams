# AWS Deploy Surface

What this project provisions in AWS, and what inputs you need to make a deploy deterministic from scratch.

## 1. What gets deployed

Everything lives in a single AWS account + region. There are three layers of resources:

### 1.1 Foundation stack (`infra/foundation/template.yaml`)

Deployed once per stage with `sam deploy`. Creates:

| Resource | Logical name | Purpose |
|---|---|---|
| DynamoDB table | `dispatch-assignments-${Stage}` | Assignment tracking (PK `assignment_id`; GSIs on `agent_id+status`, `source+created_at`); 30-day TTL |
| S3 bucket | `sdlc-agent-artifacts-${AWS::AccountId}-${Stage}` | Agent output artifacts (screenshots, test results); SSE-AES256; lifecycle rules on `screenshots/` (90d) and `test-results/` (180d) |
| Lambda | `dispatch-router-${Stage}` | Parses `@mentions`, checks auth, invokes the right AgentCore Runtime, writes assignment to DynamoDB |
| Lambda | `asana-webhook-${Stage}` | Verifies Asana webhook signatures, normalizes events, invokes Dispatch Router async |
| API Gateway | `WebhookApi` | Fronts the Asana webhook Lambda at `/asana/webhook` |
| SSM parameter | `/sdlc-agents/${Stage}/registry` | Agent registry, populated by `scripts/sync_registry.py` from `.dispatch/agents.yaml` |
| CloudWatch alarms | Three alarms | Dispatch error rate, webhook error rate, dispatch p99 duration |

**Outputs:** `AssignmentsTableName`, `ArtifactsBucketName`, `DispatchRouterArn`, `WebhookEndpoint` (Asana webhook URL), `WebhookApiId`.

### 1.2 Per-agent runtime (created by the deploy pipeline, not SAM)

Each agent creates its own AWS resources when its deploy workflow runs for the first time:

| Resource | Logical name pattern | Created by |
|---|---|---|
| ECR repository | `sdlc-agents/<agent>` | `.github/workflows/deploy-agent.yml` (idempotent `ecr describe-repositories` or `create-repository`) |
| IAM role | `<agent>-agentcore-runtime` | **Not automated today.** Must be created manually or via the `sdlc-agents-provision-aws` skill. |
| AgentCore Runtime | `<agent>` | `.github/workflows/deploy-agent.yml` on first push |
| Container image | `sdlc-agents/<agent>:<commit-sha>` in ECR (repos are `IMMUTABLE` — one tag per build, no `:latest`) | `.github/workflows/deploy-agent.yml` |

Four agents ship today, so the per-agent surface is **four of each** of the above: `workitems`, `researcher`, `docwriter`, `adr`.

### 1.3 OIDC + deploy role (one-time, manual)

The GitHub Actions workflows assume an IAM role via OIDC. This is **not created by the foundation stack.** You must create it yourself (the `sdlc-agents-provision-aws` skill walks through it). The role needs:

- Trust policy allowing `token.actions.githubusercontent.com`, with `sub` restricted via `StringEquals` to the exact subjects your workflows use. For this repo that's two subjects: `repo:<your-org>/<your-repo>:ref:refs/heads/main` (covers `push`-to-main events for the deploy workflows, and comment-driven triggers like `issue_comment` / `pull_request_review_comment` in `agent-dispatch.yml` and `claude-code.yml` — all of which run on the default branch) and `repo:<your-org>/<your-repo>:pull_request` (covers the `pull_request: [opened, synchronize]` trigger in `claude-code.yml`, which auto-reviews new PRs). Do **not** use `StringLike: "repo:<org>/<repo>:*"` — that allows any branch, tag, or environment in the repo to assume the role, including feature branches a contributor can push without review. Re-check this list if you add workflows that use `workflow_dispatch`, `schedule`, or `workflow_call` from a different repo — those may emit different `sub` claims.
- `AdministratorAccess` or a tighter scoped policy covering: ECR push, `bedrock-agentcore:*`, Lambda invoke on the Dispatch Router, CloudFormation/SAM operations for the foundation stack
- OIDC provider for `token.actions.githubusercontent.com` with `sts.amazonaws.com` audience and the GitHub thumbprint

The role ARN goes into the target repo's GitHub Actions secrets as `AWS_DEPLOY_ROLE_ARN`.

### 1.4 Optional: Claude Code on Bedrock (one-time, per repo)

If you use the `sdlc-agents-setup-claude-code` skill, it creates:

- IAM role `ClaudeCodeBedrockRole` with `bedrock:InvokeModel` on Opus 4.7's inference profile
- Secret `CLAUDE_CODE_ROLE_ARN` + variable `CLAUDE_CODE_AWS_REGION` on the target repo

Independent of the fleet — you can deploy it or not.

## 2. Inputs required for a deterministic deploy

### 2.1 AWS account + region

- **`AWS_ACCOUNT_ID`** — 12-digit account ID, stored as a GitHub Actions secret.
- **`AWS_REGION`** — deployment region, stored as a GitHub Actions variable. Must have Bedrock model access enabled for `us.anthropic.claude-opus-4-7-v1`.

### 2.2 Bedrock model access

Enabled in the Bedrock console → Model access. Required in the same region as `AWS_REGION`. Without this, agent invocations return `AccessDeniedException`.

### 2.3 SAM parameters (for the foundation stack)

Passed to `sam deploy --parameter-overrides`:

- **`Stage`** — `dev` / `staging` / `prod`. Embedded in every resource name.
- **`WorkitemsBotGID`** — Asana user GID that tasks are assigned to to trigger Workitems.
- **`AgentFieldGID`** — Asana custom field GID for the "Agent" dropdown (optional — empty string is fine if you're not using custom-field triggers).

### 2.4 SSM SecureString parameters (populated by connect skills)

The shipping code expects these. Each is written by the corresponding skill or bootstrap script; no agent creates them.

| Parameter | Written by | Consumed by |
|---|---|---|
| `/sdlc-agents/asana-pat` | `sdlc-agents-connect-asana` (Step 1) | `asana-webhook-${Stage}` Lambda (REST calls) |
| `/sdlc-agents/asana-webhook-secret` | `scripts/bootstrap_asana_webhook.py` (operator-run; attaches a temporary inline `ssm:PutParameter` policy to the Lambda role for the handshake window) | `asana-webhook-${Stage}` Lambda (signature verify) |
| `/sdlc-agents/asana-mcp-client-id` | `sdlc-agents-connect-asana` (Step 2) | Agent runtimes reading Asana |
| `/sdlc-agents/asana-mcp-client-secret` | `sdlc-agents-connect-asana` (Step 2) | Agent runtimes reading Asana |
| `/sdlc-agents/asana-mcp-refresh-token` | `scripts/bootstrap_asana_oauth.py` (Step 3 of connect-asana) | Agent runtimes reading Asana |
| `/sdlc-agents/github-mcp-token` | `sdlc-agents-connect-github` (PAT path) | Agent runtimes reading GitHub |
| `/sdlc-agents/github-app-id` / `...-installation-id` / `...-private-key` | `sdlc-agents-connect-github` (App path) | Agent runtimes reading GitHub (App auth alternative to PAT) |
| `/sdlc-agents/researcher-tavily-api-key` | Manual | Researcher's `web_search` tool |
| `/sdlc-agents/${Stage}/registry` | `scripts/sync_registry.py` (writes resolved ARNs) | Dispatch Router Lambda |

Missing any required parameter produces a clear error at invocation time (not at deploy time). The deploy workflow's guard catches missing GitHub Actions **variables**, not SSM parameters.

### 2.5 GitHub Actions repository variables

Per `deploy-agent.yml`'s `env_vars` input, the following are baked into each AgentCore Runtime's environment and the workflow fails fast if any required value is empty:

| Variable | Required by | Notes |
|---|---|---|
| `AWS_REGION` | All deploy workflows | Falls back to `us-west-2` if unset |
| `TARGET_REPO` | `deploy-workitems.yml`, `deploy-docwriter.yml`, `deploy-adr.yml` | Format `<owner>/<repo>`. GitHub rejects user-defined variables starting with `GITHUB_`, so the repo variable is `TARGET_REPO` and the deploy workflow passes it through to the container as env var `GITHUB_REPO`. |
| `ASANA_PROJECT_GID` | `deploy-workitems.yml`, `deploy-docwriter.yml`, `deploy-researcher.yml` | |
| `ASANA_WORKSPACE_GID` | same three | |
| `ASANA_PROJECT_NAME` | optional | Cosmetic label in system prompts |
| `CLAUDE_CODE_AWS_REGION` | `claude-code.yml` (optional) | Defaults to `us-east-1` |

### 2.6 GitHub Actions repository secrets

| Secret | Consumed by |
|---|---|
| `AWS_DEPLOY_ROLE_ARN` | All deploy workflows, `agent-dispatch.yml` |
| `AWS_ACCOUNT_ID` | All deploy workflows |
| `CLAUDE_CODE_ROLE_ARN` | `claude-code.yml` (optional — only if using Claude Code on Bedrock) |

## 3. Ordering for a first-time deploy

Top-to-bottom, no skipping.

1. **Enable Bedrock model access** (console) for `us.anthropic.claude-opus-4-7-v1` in `$AWS_REGION`.
2. **Create the OIDC provider and deploy role** (skill: `sdlc-agents-provision-aws`, Step 0 prereqs). Capture the role ARN.
3. **Set GitHub Actions secrets** (`AWS_DEPLOY_ROLE_ARN`, `AWS_ACCOUNT_ID`) and variables (`AWS_REGION`, plus per-agent vars).
4. **Deploy the foundation stack** with `sam deploy` — this is how you get the Dispatch Router, webhook Lambda, API Gateway, DynamoDB, S3, SSM registry parameter, and CloudWatch alarms.
5. **Connect integrations** — run `sdlc-agents-connect-asana` and/or `sdlc-agents-connect-github` to populate SSM parameters.
6. **Provision per-agent IAM runtime roles** — `sdlc-agents-provision-aws` creates one per agent, attaches the per-agent SSM-read policy.
7. **Push to `main`** — this is the first time `deploy-agent.yml` runs for each agent. It creates the ECR repo, builds the image, creates the AgentCore Runtime, syncs the registry to SSM, and smoke-tests.
8. **Register the Asana webhook** — `sdlc-agents-register-triggers` calls the Asana API with the `WebhookEndpoint` stack output.
9. **Verify** — `sdlc-agents-verify` runs layered smoke tests (runtime health → credential freshness → end-to-end mention).

Steps 2, 6 are the two that are **not** covered by SAM or CI/CD. The rest are automated once prerequisites are in place.

## 4. What a "deterministic" deploy requires that we don't have today

Gaps to close before a clean `sam deploy && gh workflow run` from a fresh clone produces a live fleet:

1. **Foundation stack doesn't create the OIDC provider or deploy role.** You create them by hand (or via the skill) before the first SAM deploy. These should be part of a bootstrap stack (`infra/bootstrap/template.yaml`) that runs once per account, using long-lived credentials.
2. **Per-agent IAM runtime roles aren't in SAM.** They're created ad-hoc by the skill. They should live in the foundation stack (or a per-agent sub-stack) so `sam deploy` produces them deterministically. Bonus: Cedar policies could move from `cedar/*.cedar` files into the IAM role definition too, or into a dedicated Cedar-authorization resource.
3. **SSM parameter creation is manual.** The secure parameters (Asana PAT, MCP credentials, GitHub PAT, Tavily key) are one-shot bootstraps. That's fine — they're secrets — but today the deploy pipeline can't tell at-deploy-time whether they're present. Adding a pre-deploy check (similar to the `env_vars` guard) would catch this earlier.
4. **AgentCore Memory isn't provisioned.** Agents honor `AGENTCORE_MEMORY_ID` if set; if you want Memory, you create the resource and set the env var yourself. Should be an opt-in parameter on the foundation stack.
5. **No Cedar evaluator in the invocation path.** The `cedar/*.cedar` files are advisory — a deterministic deploy includes a verifier step that fails if Cedar syntax is broken. (Today we could pass syntactically invalid Cedar without noticing.)
6. **Registry sync runs as a deploy-time side effect of each agent push.** `sync_registry.py` requires every agent referenced in `.dispatch/agents.yaml` to have a runtime ARN already resolvable. First-time deploys that touch multiple agents can race. Either serialize agent deploys or teach `sync_registry.py` to tolerate unresolved placeholders.

None of these block adoption today — they're roughness that a team running the fleet at volume will hit first.

## 5. Resources you destroy for a clean teardown

Rough shutdown order:

1. De-register the Asana webhook (`curl DELETE https://app.asana.com/api/1.0/webhooks/<id>`).
2. Delete the four AgentCore Runtimes (`bedrock-agentcore-control delete-agent-runtime`).
3. Delete the four IAM runtime roles.
4. Delete the four ECR repositories (including all images).
5. Delete the foundation CloudFormation stack (`sam delete`). This removes the Dispatch Router, webhook Lambda, API Gateway, DynamoDB table, S3 bucket (must be empty first), SSM registry parameter, and CloudWatch alarms.
6. Delete the SSM SecureString parameters (`asana-*`, `github-*`, `researcher-tavily-api-key`).
7. Delete the OIDC provider and deploy role (if not needed for another stack).
8. Disable Bedrock model access (optional).

S3 bucket deletion blocks on non-empty. Explicit empty before destroy is required.
