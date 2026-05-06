# PDLC Agent Fleet

Autonomous AI agents for the software development lifecycle, deployed on
Amazon Bedrock AgentCore.

## Project Structure

```
agents/           — Agent code (Strands SDK, containerized, deployed to AgentCore Runtime)
  workitems/      — PO/PM agent: work decomposition, status, risk, sync
  researcher/     — BA agent: research synthesis, competitive intel, backlog
  docwriter/      — Tech-writer agent: API docs, guides, release notes
  shared/         — Shared tools and helpers used by all agents
infra/            — AWS infrastructure (SAM/CloudFormation)
  dispatch/       — Dispatch Router + Asana webhook receiver (Lambda)
  foundation/     — Shared resources (DynamoDB, S3, IAM, CloudWatch)
cedar/            — Cedar policies (guardrails for agent tool access)
docs/             — Planning docs, specs, roadmap
  specs/          — Individual agent and system specs
.dispatch/        — Agent registry (agents.yaml)
.github/workflows — CI/CD pipelines and GitHub event triggers
```

## Tech Stack

- **Language**: Python 3.12
- **Agent Framework**: Strands Agents SDK
- **Model**: Claude Opus 4.7 via Amazon Bedrock
- **Runtime**: Amazon Bedrock AgentCore Runtime (containerized)
- **Tool Access**: Direct MCP (`mcp.asana.com/v2/mcp`, `api.githubcopilot.com/mcp/`) via Strands' `streamablehttp_client`. AgentCore Gateway is a planned upgrade.
- **Auth**: Credentials in SSM Parameter Store (SecureString) — per-agent runtime role has narrow `ssm:GetParameter` access. AgentCore Identity is a planned upgrade.
- **Memory**: Agents honor `AGENTCORE_MEMORY_ID` via Strands' `AgentCoreMemoryToolProvider`. No Memory resource is provisioned by the fleet's infra template today; this is a roadmap item.
- **Policy**: Cedar policy files under `cedar/<agent>.cedar` (currently advisory; runtime enforcement is a roadmap item).
- **Infra**: AWS SAM (CloudFormation) — see `docs/aws-deploy.md` for the full surface.
- **CI/CD**: GitHub Actions → ECR → AgentCore Runtime

## Conventions

- Agents NEVER close issues, merge PRs, or delete tasks. Cedar policies enforce this.
- Work decomposition uses the approval pattern: agent proposes → human approves → agent executes.
- Custom tools are structured task prompts, not business logic. They return instructions that guide the agent's reasoning. The LLM does the actual orchestration.
- System prompts live in `prompts.py` alongside agent code, not in separate config.
- Agent registry lives in `.dispatch/agents.yaml` and is synced to SSM on deploy.

## Working with Agents

Each agent under `agents/` is self-contained:
- `agent.py` — Strands agent entry point with `@app.entrypoint`
- `prompts.py` — System prompt (versioned with code)
- `tools/` — Custom `@tool` functions
- `tests/eval_dataset.json` — Golden set for quality evaluation
- `Dockerfile` + `requirements.txt` — Container deployment

## Current Focus

Building the Workitems agent (MLP). See `docs/roadmap.md` for the full plan.
