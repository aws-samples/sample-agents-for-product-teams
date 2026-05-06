# Agent Fleet: Implementation Status and Next Steps

This document replaces the earlier 438-line epic/story plan. That plan laid out an 18-week build of five agents plus a Feedback learning agent plus cross-agent A2A orchestration. Reality is simpler, which is why this document is shorter.

## What shipped

Four agents are live on AgentCore Runtime today. Each has code under `agents/<name>/`, a Cedar policy in `cedar/<name>.cedar`, and a deploy workflow at `.github/workflows/deploy-<name>.yml`.

| Agent | Role | Trigger surface |
|---|---|---|
| **Workitems** | PO/PM — work decomposition (approval pattern), status, risk | `@workitems` in Asana/GitHub; Asana task assignment |
| **Researcher** | Business analyst — synthesis, competitive scans, story drafting, spec review | `@researcher` in Asana; Asana task assignment |
| **Docwriter** | Technical writer — API docs, release notes, doc PRs | `@docwriter` in GitHub/Asana |
| **Adr** | ADR linker — tags issues, reviews PRs against governing ADRs | `@adr` on GitHub issues or PRs |

The **Dispatch Router** Lambda routes mentions from GitHub + Asana to the right runtime. **Asana webhook receiver** + **GitHub Actions workflow** (`agent-dispatch.yml`) are the two event sources. State tracks in DynamoDB (`dispatch-assignments-${STAGE}`). Credentials live in SSM (SecureString, per-path narrow IAM).

All agents run **Claude Opus 4.7** via Bedrock.

## What's intentionally *not* shipped

These were in the original plan. Each is cleanly deferrable and none blocks adoption.

- **AgentCore Identity** — we use SSM directly. Identity is a natural upgrade when the operational story for it solidifies.
- **AgentCore Gateway** — agents connect directly to vendor MCP servers (`mcp.asana.com`, `api.githubcopilot.com/mcp`). Gateway would be an upgrade for centralized auth/rate-limiting/observability.
- **AgentCore Memory (provisioned)** — agents honor `AGENTCORE_MEMORY_ID` if set, but no Memory resource is provisioned by the foundation stack. Teams that want memory today provision their own.
- **AgentCore Browser** — not used; no agent has a browser dependency today.
- **UAT agent** — depends on Browser and a maintenance story for tests across UI changes.
- **Feedback agent** — depends on Memory being provisioned and populated.
- **Slack dispatch** — the registry advertises Slack triggers but there's no receiver Lambda or signing-secret path. Flagged as a gap in `skills/pdlc-agents-register-triggers`.
- **Merge, Gtm, Triage, Diagnostics, Monitor, Bugreproducer, Securityreviewer** — each had a design doc in an earlier draft; none have code.

## Next steps (roadmap order, not commitments)

See [`docs/roadmap.md`](roadmap.md) for the live roadmap. The near-term priorities as of this writing:

1. **Provision AgentCore Memory** in the foundation template and wire seed data for each agent.
2. **Slack event receiver** so `@workitems status` in Slack works end-to-end.
3. **Per-agent Cedar evaluator in the invocation path** so policies are enforced, not advisory.
4. **AgentCore Evaluations** wired up against the `eval_dataset.json` golden sets each agent already ships.
5. **Jira support** — Atlassian has an official remote MCP server; the agent-side work is lighter than the dispatch side (needs a Jira webhook Lambda).

## Why this document is short

The original plan was a 72-story, 18-week implementation schedule. In practice:

- Phases 0, 1, 2, 4, 5 (infrastructure, Dispatch, Workitems, Researcher, Docwriter) shipped, though not in the order or scope the plan predicted.
- Phases 3 (Uat) and 6 (Fleet Operations) didn't happen. Adr was added mid-stream instead.
- Tracking 72 stories against a plan we weren't actually executing was doc debt, not planning.

A shipping project is better served by a README + design doc that describes what exists, plus a roadmap that's short and honest. This document is a pointer to both.
