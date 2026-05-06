# Researcher

**Role:** Business analyst — research synthesis, competitive intel, backlog analysis
**Status:** Shipped — live on AgentCore Runtime
**Trigger:** `@researcher` mention in Asana; Asana task assignment
**Code:** [`agents/researcher/`](../../agents/researcher/)
**Spec:** [`docs/specs/researcher-ba-agent-spec.md`](../specs/researcher-ba-agent-spec.md)

## What Researcher does

Researcher is the team's analyst. It takes raw signals — research transcripts,
survey data, support tickets, market trends — and turns them into structured
findings, user stories, and prioritized recommendations.

Researcher works entirely through Asana. All input arrives as Asana task
assignments or mentions; all output is posted back to Asana as comments,
new tasks, or task field updates.

## Operating modes

- **SYNTHESIZE** — processes qualitative research (transcripts, surveys,
  support tickets, app reviews) into themed findings with severity,
  frequency, and representative quotes.
- **COMPETE** — monitors the competitive landscape via web search (Tavily).
  Tracks launches, pricing, and positioning, with findings persisted across
  runs in AgentCore Memory.
- **SPECIFY** — drafts user stories with personas, goals, acceptance
  criteria, edge cases, and dependencies. Reviews existing specs for
  completeness, ambiguity, and testability.
- **PRIORITIZE** — computes RICE scores across the backlog, flags duplicates
  and gaps, and presents prioritization options with trade-offs (never a
  single prescribed answer).
- **SIZE** — estimates feature impact by combining usage analytics with
  qualitative research. Always includes confidence levels and assumptions.

## Tools

- Asana MCP (official server at `mcp.asana.com/v2/mcp`; OAuth refresh-token flow, credentials in SSM)
- `web_search` (Tavily) for competitive intelligence — API key in SSM at `/sdlc-agents/researcher-tavily-api-key`
- `synthesize_research`, `draft_user_stories`, `analyze_backlog`,
  `competitive_scan`, `review_spec`, `post_results` (custom Strands tools
  under `agents/researcher/tools/`)
- AgentCore Memory (optional — honored via `AGENTCORE_MEMORY_ID` env var; no Memory resource is provisioned today)

## Guardrails

- **Never** deletes or completes tasks — those are human decisions.
- **Never** makes final prioritization decisions — presents options, humans
  choose.
- Every claim, finding, or recommendation cites its source (URL, Asana
  task GID, data methodology, or prior research). Unsourced assessments are
  explicitly labeled.
- All tasks Researcher creates are labeled `researcher-generated` for traceability.

## Deployment

Containerized, deployed to Amazon Bedrock AgentCore Runtime. Built and pushed
via `.github/workflows/deploy-researcher.yml` on changes under
`agents/researcher/**`.
