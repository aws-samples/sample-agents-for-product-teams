---
name: sdlc-agents
description: Use when the user wants to install, configure, or onboard the SDLC Agent Fleet (workitems, researcher, docwriter, and others) into a new project or AWS account. Drives the conversation from tool discovery through agent selection, provisioning, and verification. Delegates each step to the narrower sdlc-agents-* skills.
---

# Install SDLC Agent Fleet in a new project

The SDLC Agent Fleet is a set of autonomous agents that cover the software development lifecycle — project management, documentation, business analysis, and ADR linking. Each agent runs on Amazon Bedrock AgentCore. Shipping agents integrate with **Asana** (PM) and **GitHub** (SCM); additional tools (Jira, GitLab, Slack, Salesforce, Datadog) are planned but not yet supported end-to-end.

**Not every customer uses every agent.** Your job is to have a conversation that:

1. Figures out which tools the customer already uses
2. Matches those tools to the subset of agents that make sense
3. Provisions and configures only those agents

## Installer repo vs. target project

This flow runs from inside a clone of the **installer repo** (the one containing `agents/`, `infra/`, `cedar/`, and these skills). It installs the fleet onto a **target project** — usually a different repository whose CI/CD you are wiring up.

Never assume the cwd is the target. The `/sdlc-agents` slash command resolves a `TARGET_REPO` absolute path (and `TARGET_REMOTE` origin URL) from the user's argument before handing off to this flow — if those aren't set yet, stop and resolve them before Step 1. All target-side filesystem operations (ADR detection, `.sdlc-agents/selection.yaml`, `.github/workflows/` edits, `git` commands for branch/remote checks) use `TARGET_REPO`. All installer-side reads (agent source, templates, skill files, scripts) come from the cwd.

## Golden rules

- **Never assume tool choice.** Ask. Most customers have strong opinions about their PM tool, their source-control host, their chat platform. Don't pick GitHub just because it's the common default.
- **Never provision agents the customer didn't ask for.** More agents = more IAM roles, runtimes, webhooks to manage. Fewer is usually better.
- **One decision at a time.** Don't dump a 20-question survey on the user. Ask one thing, record it, move on.
- **Surface cost and coupling as you go.** Each agent adds an AgentCore Runtime (~$30–100/mo cold), an ECR repo, an IAM role, and one or more webhook integrations. Tell the user what they're opting into before they opt in.
- **Work from the top-level skill, delegate to narrower skills.** Each step has its own skill (see the step list below). When you're ready for that step, invoke the matching skill and follow its checklist. Don't inline its logic here.

## Flow

### Step 1 — Discover the customer's toolchain

Ask, don't scan. Start with the minimum viable set of questions:

1. What do you use for project management? (Asana / Jira / Linear / Trello / Aha! / other / none) — only Asana is supported today
2. What do you use for source control? (GitHub / GitLab / Bitbucket / other) — only GitHub is supported today
3. What AWS account and region do you want the fleet to live in?

Record answers. If the user names a tool that doesn't have a shipping connect skill (e.g. Jira, GitLab), tell them so immediately — don't let the conversation go ten questions deep before surfacing that their PM or SCM isn't supported yet.

### Step 2 — Propose an agent selection

With the tool list in hand, invoke the **sdlc-agents-select** skill. It has the authoritative agent roster + which integrations each agent needs, and it presents the filtered list to the user. The user confirms or edits.

All repo-specific checks inside the select skill (ADR directory detection in particular) must be rooted at `TARGET_REPO`, not the installer cwd.

After selection: write the chosen list to `$TARGET_REPO/.sdlc-agents/selection.yaml`. Later steps read from there so the user can re-run any single step without restating their selection.

### Step 3 — Provision AWS infrastructure

Invoke the **sdlc-agents-provision-aws** skill. For each selected agent it creates:
- IAM runtime role (named `<agent>-agentcore-runtime`) with the specific policies that agent needs
- ECR repo (`sdlc-agents/<agent>`)
- AgentCore Runtime (created on first container push; the deploy workflow handles this)

Idempotent — safe to re-run. Walks the user through prerequisites (Bedrock model access, deploy-role OIDC trust) if they aren't already set up.

### Step 4 — Wire up integrations (per tool)

For each tool the customer uses, invoke the matching connect skill:

- Asana → **sdlc-agents-connect-asana** (OAuth app setup, MCP vs API app, PAT for webhook Lambda)
- GitHub → **sdlc-agents-connect-github** (GitHub App or fine-grained PAT for MCP, deploy-role OIDC for CI)

Other tools (Jira, GitLab, Slack, Salesforce, Datadog) don't have connect skills yet — the shipping agents all work against Asana + GitHub. If the user picked one of those other tools during discovery, tell them honestly that the connect path isn't written yet and point them at the vendor's remote MCP docs; don't fabricate setup steps.

Each connect skill knows the specific pitfalls of its tool (Asana's MCP-app-vs-API-app distinction is the classic one) and walks past them.

### Step 5 — Register webhooks and bot accounts

Invoke **sdlc-agents-register-triggers**. This is the step that turns a provisioned fleet into one that actually reacts to `@agent` mentions:
- Asana webhook → API Gateway endpoint, with handshake secret stored in SSM
- GitHub: `agent-dispatch.yml` workflow enabled, trigger list updated for selected agents
- Slack app event subscriptions, etc.

### Step 6 — Verify

Invoke **sdlc-agents-verify**. Runs a smoke test per agent (health-check invocation + one end-to-end trigger test through the actual integration surface). Reports pass/fail per agent so the user knows exactly which integrations are live.

### Step 7 — (Optional) Enable Claude Code on Bedrock for issue coding + PR review

After the fleet is verified, ask the user:

> Do you want to enable `@claude` in this repo so Claude Code can code against issues and review PRs? It uses the same Amazon Bedrock model as the fleet, authenticated via GitHub Actions OIDC — no Anthropic API key needed.

If yes, invoke **sdlc-agents-setup-claude-code**. It's scoped to GitHub + Bedrock (not tied to the agent fleet's AgentCore runtimes), so users who want `@claude` but not the fleet can also run it standalone.

## When to stop and get help

If any step fails in a way the skill didn't anticipate:
- Capture the exact error (tool name, response body, timestamps)
- Check CloudWatch Logs for the relevant Lambda or runtime
- Don't paper over the error with a retry loop — figure out why before retrying
- If it's an AWS permissions issue (SCPs, org policies), stop and tell the user; you can't fix those from inside the skill

## Reading material

- `docs/agents/<agent>.md` — one file per agent with role, triggers, guardrails, and infra notes. Read the relevant ones before walking a customer through that agent's setup.
- `docs/agent-fleet-implementation-plan.md` — the full multi-phase rollout plan.
- `.dispatch/agents.yaml` — canonical agent registry format. Your end state should match this structure.
- `AGENTS.md` (at repo root) — step-by-step runbook for configuring the fleet manually. Skills automate this; when the skill flow diverges from the runbook, the skill is wrong — update it.
