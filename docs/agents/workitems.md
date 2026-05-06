# Workitems

**Role:** PO/PM — work decomposition, status reports, risk detection, bidirectional sync
**Status:** Shipped — live on AgentCore Runtime
**Trigger:** `@workitems` mention in Asana, GitHub, or Slack; Asana task assignment; scheduled runs
**Code:** [`agents/workitems/`](../../agents/workitems/)
**Spec:** [`docs/specs/workitems-agent-plan.md`](../specs/workitems-agent-plan.md)

## What Workitems does

Workitems is the project manager for the fleet. It bridges Asana (where planning
happens) and GitHub (where development happens) and coordinates the other
agents.

- **Work decomposition**: reads an Asana task describing a feature or epic,
  proposes a plan as an Asana comment, and — on human approval — creates the
  corresponding GitHub issues with acceptance criteria.
- **Assignment**: hands issues to `@claude` for implementation, and triggers
  `@docwriter` when a merged change affects documentation.
- **Review**: reads Claude's work on an issue, checks it against the
  acceptance criteria, and either approves or sends it back for revision.
- **Status reports**: synthesizes GitHub + Asana activity into weekly status
  (shipped, in progress, blocked, at risk).
- **Risk detection**: flags stale issues, blocked PRs, past-due tasks,
  unassigned work.
- **Sync**: reconciles issue status between GitHub and Asana.

## How Workitems works

```
Human sets goals in Asana
    → Workitems decomposes into GitHub issues (after approval)
    → Workitems assigns implementation to @claude
    → Claude implements and reports back
    → Workitems reviews against acceptance criteria
    → Workitems approves or requests changes
    → Workitems triggers @docwriter for doc updates when relevant
    → Workitems reports completion back to Asana
```

Workitems is the only agent in the fleet that assigns work. No agent
self-assigns or self-approves.

## Tools

- Asana MCP (official server at `mcp.asana.com/v2/mcp`; OAuth refresh-token flow, credentials in SSM)
- GitHub MCP (official remote server at `api.githubcopilot.com/mcp/`; PAT or GitHub App token from SSM)
- `generate_status_report`, `detect_risks`, `reconcile_sync`, `post_results`
  (custom Strands tools under `agents/workitems/tools/`)
- AgentCore Memory (optional — honored via `AGENTCORE_MEMORY_ID` env var; no Memory resource is provisioned today)

## Guardrails

- **Never** closes issues, merges PRs, or deletes tasks (enforced by Cedar).
- **Never** creates GitHub issues without prior human approval in Asana.
- Every agent-triggering comment must contain the literal trigger word
  (`@claude`, `@docwriter`) — without it, the downstream agent never picks up
  the work.
- Reports tool failures honestly rather than faking a success comment.

## Deployment

Containerized, deployed to Amazon Bedrock AgentCore Runtime. Built and pushed
via `.github/workflows/deploy-workitems.yml` on changes under `agents/workitems/**`.

## Roadmap

- **Additional PM tools**: Jira, Trello, and Aha! as alternative project
  sources alongside Asana. Core decomposition and sync logic is reused;
  only the Dispatch webhook receiver and the Gateway MCP target change per
  tool. See [`docs/roadmap.md`](../roadmap.md) for sequencing.
