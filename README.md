# SDLC Agent Fleet

Autonomous AI agents for the software development lifecycle. Each agent handles
a specific role — project management, testing, documentation, business analysis —
and collaborates through a shared dispatch system and memory layer.

Built on [Amazon Bedrock AgentCore](https://aws.amazon.com/bedrock/agentcore/)
with the [Strands Agents SDK](https://github.com/strands-agents/sdk-python).

![SDLC roles, tools, and tasks across the software lifecycle](docs/assets/sdlc-roles-tools-tasks.png)

Software delivery is a team sport played across many tools by people in diverse
roles. The fleet plants an agent in each role's seat so the paperwork
(decomposition, status, docs, ADR tagging) runs itself and the humans stay
focused on the product.

## Agents

These are the agents that are deployed to AgentCore Runtime today. Additional
agents are in design or early development under [`docs/agents/`](docs/agents/);
they'll be listed here once their code ships.

| Agent | Role | Trigger |
|-------|------|---------|
| [**Workitems**](docs/agents/workitems.md) | PO/PM — work decomposition, status reports, risk detection, sync | `@workitems` in Asana/GitHub/Slack |
| [**Researcher**](docs/agents/researcher.md) | Business analyst — research synthesis, competitive intel | `@researcher` |
| [**Docwriter**](docs/agents/docwriter.md) | Technical writer — API docs, user guides, release notes | `@docwriter` |
| [**Adr**](docs/agents/adr.md) | ADR linker — tags issues and reviews PRs against the repo's ADR library | `@adr` on a GitHub issue or PR |

![Workitems decomposing an Asana task after an @mention](docs/assets/at-workitems-mention-asana.png)

![Researcher replying to an @mention on an Asana task](docs/assets/at-researcher-mention-asana.png)

## How It Works

1. A user assigns work via `@agent` mention in Asana, GitHub, or Slack
2. The **Dispatch Router** resolves the mention, checks authorization, and routes to the agent
3. The agent runs on **AgentCore Runtime**, using **Gateway** for GitHub/Asana/Slack access
4. Results are posted back to the originating platform

For Workitems' work decomposition flow:
- User assigns Workitems to an Asana task
- Workitems reads the task, project context, and existing GitHub issues
- Workitems proposes a plan as an Asana comment
- User replies "approved" → Workitems creates the GitHub issues
- User replies with feedback → Workitems revises and re-proposes

![Workitems handing an approved task off to Claude Code on GitHub](docs/assets/workitems-assign-to-claude-github.png)

## Project Structure

```
agents/
  workitems/     Strands agent — PO/PM
  docwriter/     Strands agent — Technical writer
  researcher/    Strands agent — Business analyst
  adr/           Strands agent — ADR linker
  shared/        Shared tools and helpers
infra/
  dispatch/      Dispatch Router + Asana webhook (Lambda)
  foundation/    Shared AWS resources (DynamoDB, S3, IAM)
cedar/           Cedar policy guardrails
skills/          Claude Code skills that drive the Quickstart
scripts/         Operator helpers (OAuth bootstrap, registry sync)
.dispatch/       Agent registry (agents.yaml)
.github/
  workflows/     CI/CD pipelines
docs/            Specs, roadmap, planning docs
```

## Prerequisites

- AWS account with Bedrock model access enabled for `us.anthropic.claude-opus-4-7-v1` in your target region
- AWS CLI configured with appropriate credentials
- [SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html)
- Docker (for building agent containers)
- Python 3.12+

## Quickstart (skill-driven)

The fastest path to a working fleet is to let the bundled Claude Code skill drive
the install. It has a conversation with you to figure out which tools you use
(GitHub/GitLab, Asana/Jira, Slack, etc.), which subset of agents to deploy,
**which AWS account and region to deploy into**, and then walks each provisioning
step end-to-end.

From this repo, in Claude Code:

```
/sdlc-agents
```

The skill will:

1. Ask which PM tool, SCM, and chat platform you use
2. Propose the matching subset of agents (and let you edit)
3. Provision AWS (IAM roles, ECR repos, AgentCore Runtimes) in the account/region you chose
4. Walk through OAuth/App connections for each integration
5. Publish the per-repo config (region, GitHub repo, Asana GIDs) as GitHub Actions Variables so the deploy workflows pick them up automatically
6. Register webhooks and bot accounts
7. Run a smoke test per agent

The region you pick is written to `.sdlc-agents/selection.yaml` and reused by
every downstream step — nothing in the install path is hard-coded to `us-west-2`.

## Setup (manual)

If you'd rather provision by hand, the outline below mirrors what the skill does.
Set `AWS_REGION` (and `AWS_ACCOUNT_ID`) once in your shell and every snippet
below picks it up.

```bash
export AWS_REGION=us-west-2          # pick your region
export AWS_ACCOUNT_ID=123456789012   # your 12-digit account ID
```

### 1. Bootstrap AWS infrastructure

```bash
# Deploy shared resources (DynamoDB, S3, IAM roles)
cd infra/foundation
sam build && sam deploy --guided --region "$AWS_REGION"
```

This creates the `dispatch-router` Lambda, DynamoDB tables, and IAM roles used by all agents.

### 2. Configure GitHub repository secrets

Go to **Settings → Secrets and variables → Actions** and add:

| Secret | Description |
|--------|-------------|
| `AWS_DEPLOY_ROLE_ARN` | ARN of the IAM role for GitHub Actions OIDC (created by `infra/foundation`) |
| `AWS_ACCOUNT_ID` | Your AWS account ID |

The deploy workflows use OIDC — no long-lived credentials needed. The IAM role must have a trust policy allowing `token.actions.githubusercontent.com` for this repository.

### 3. Configure GitHub Actions OIDC trust

The IAM role created in step 1 needs a trust policy like:

```json
{
  "Effect": "Allow",
  "Principal": { "Federated": "arn:aws:iam::YOUR_ACCOUNT:oidc-provider/token.actions.githubusercontent.com" },
  "Action": "sts:AssumeRoleWithWebIdentity",
  "Condition": {
    "StringLike": { "token.actions.githubusercontent.com:sub": "repo:YOUR_ORG/YOUR_REPO:*" }
  }
}
```

### 4. Create ECR repositories

One repository per agent:

```bash
for agent in workitems docwriter researcher adr; do
  aws ecr create-repository --repository-name "sdlc-agents/$agent" --region "$AWS_REGION"
done
```

### 5. Deploy agents

Push to `main` — the per-agent CI/CD workflows build, scan, and deploy automatically when files under `agents/<name>/` change.

To deploy manually (rare — normally CI handles this via `.github/workflows/deploy-agent.yml`):

```bash
cd agents
IMAGE_TAG="$(git rev-parse HEAD)"
IMAGE_URI="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/sdlc-agents/workitems"
docker build -f workitems/Dockerfile -t "${IMAGE_URI}:${IMAGE_TAG}" .
aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "${IMAGE_URI}"
docker push "${IMAGE_URI}:${IMAGE_TAG}"
aws bedrock-agentcore-control update-agent-runtime \
  --agent-runtime-name workitems \
  --agent-runtime-artifact "containerConfiguration={containerUri=${IMAGE_URI}:${IMAGE_TAG}}" \
  --region "$AWS_REGION"
```

ECR repositories are created with `IMMUTABLE` tag mutability — each push must use a fresh tag. The commit SHA is a natural choice. Don't reuse tags across deploys.

### Optional helper scripts

Under `scripts/`:

- `bootstrap_asana_oauth.py` — one-shot OAuth 2.0 dance for the Asana MCP server; stores the refresh token in SSM
- `bootstrap_jira_oauth.py` — same thing for Atlassian/Jira (3LO)
- `bootstrap_asana_webhook.py` — operator-run webhook registration; attaches a temporary `ssm:PutParameter` policy to the webhook Lambda's role so the Asana handshake can persist the shared secret, then removes the policy
- `sync_registry.py` — resolves runtime ARNs in `.dispatch/agents.yaml` and pushes the registry to SSM so the Dispatch Router can read it

Run these only for the integrations you actually use.

## CI/CD Workflows

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| `deploy-workitems.yml` | Push to `main` touching `agents/workitems/**` | Build, scan, deploy Workitems |
| `deploy-docwriter.yml` | Push to `main` touching `agents/docwriter/**` | Build, scan, deploy Docwriter |
| `deploy-researcher.yml` | Push to `main` touching `agents/researcher/**` | Build, scan, deploy Researcher |
| `deploy-adr.yml` | Push to `main` touching `agents/adr/**` | Build, scan, deploy Adr |
| `deploy-agent.yml` | Called by above | Shared build/deploy logic |
| `claude-code.yml` | `@claude` in comments/PRs | Claude Code assistant |
| `agent-dispatch.yml` | `@workitems`, `@docwriter`, etc. in comments | Route mentions to agents |
| `python-lint.yml` | Push/PR to `main` | Ruff lint + format check |
| `ash-security-scan.yml` | Push/PR to `main` | Security scan changed files |
| `ash-security-comment.yml` | After ASH scan | Post scan results to PR |
| `ash-full-repository-scan.yml` | Monthly + manual | Full repo security scan |
| `dependabot.yml` | Dependabot PRs | Auto-merge patch/minor updates |

## Security

This fleet is published as a **reference architecture**, not a turnkey
production system. [`docs/threat-model.md`](docs/threat-model.md) is the
starting place for preparing your own deployment: walk through every
**Accepted** and **Open** finding and make your own risk decisions before
pointing agents at a repository or workspace you care about.

The design assumes a **trusted-contributor** deployment context — issue
authors, task creators, and commenters are already authorized members of the
repository or workspace. Key findings you should understand before shipping:

- **Prompt injection (T-1, T-2, T-3, Partially mitigated)** — LLM agents
  can still be subverted by adversarial issue, task, or comment content, but
  every inbound `@mention` is scored by an
  [Amazon Bedrock Guardrail](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails.html)
  (`PROMPT_ATTACK` filter) at the Dispatch Router edge, and every agent's
  `BedrockModel` runs the same guardrail on its `InvokeModel` calls —
  catching injection in content the agent fetches later via MCP. Guardrails
  is probabilistic, not deterministic; don't treat it as a hard boundary.

  ![Workitems blocking a prompt-attack attempt on an Asana task](docs/assets/workflow-agent-asana-mitigates-prompt-attacks.png)

- **Cedar policies are advisory (T-5, Accepted)** — `cedar/*.cedar` files
  describe per-agent tool allow/deny rules but are not enforced at runtime
  yet. A prompt-injected agent can call any tool its MCP server exposes.
- **Legitimate-path exfiltration (T-15, Accepted)** — a subverted agent can
  leak context through its own write-capable tools (GitHub comment, Asana
  task). Cedar runtime enforcement is the intended control; it is on the
  roadmap.

Mitigated surfaces include Dispatch Router IAM scope (T-6), GitHub OIDC
trust guidance (T-7), ECR image immutability (T-19), fail-closed
authorization defaults (T-4), and Asana webhook credential hygiene
(T-8, T-9). See the threat model for the full matrix.

### Before deploying against real repositories

Two **Open** findings in the threat model do not block the reference
architecture but should be handled before you wire the fleet to a production
repo or workspace:

- **T-11 — GitHub PAT scope.** A classic `repo`-scoped PAT grants write
  access to every repository its owner can reach. Prefer a GitHub App
  installation token scoped to the single repo, or at minimum a fine-grained
  PAT limited to the target repository and the smallest permission set the
  agent actually needs.
- **T-13 — API Gateway throttling.** The Asana webhook endpoint ships
  without usage-plan throttling or WAF. Attach an API Gateway usage plan
  (burst + steady-state limits) and, if the endpoint is discoverable, an AWS
  WAF web ACL with an IP-based rate rule before exposing it to untrusted
  inbound traffic.

## Docs

- [Roadmap](docs/roadmap.md) — shipped, near-term, ideas
- [Threat Model](docs/threat-model.md) — threats, current controls, recommended next work
- [AWS Deploy Surface](docs/aws-deploy.md) — what the project provisions and what's required for a deterministic deploy
- [PRFAQ](docs/01-prfaq-agent-fleet.md) — framing and FAQ
- [PRD](docs/02-prd-agent-fleet.md) — requirements (Shipped vs. Roadmap per item)
- [Design](docs/03-design-agent-fleet.md) — system architecture as shipped
- [Status](docs/agent-fleet-implementation-plan.md) — what shipped, what didn't, what's next
- [Per-agent docs](docs/agents/) — Workitems, Researcher, Docwriter, Adr
- [Specs](docs/specs/) — detailed specs for each shipping agent + the Dispatch routing layer

## Security

See [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications) for more information.

## License

This library is licensed under the MIT-0 License. See the [LICENSE](LICENSE) file.
