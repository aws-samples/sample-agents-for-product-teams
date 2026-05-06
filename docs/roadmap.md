# PDLC Agent Fleet Roadmap

A short, honest roadmap. What shipped, what's next, and what's deferred. The aspirational "v2 Features" section from an earlier draft of this doc has been moved to a separate [ideas](#ideas-not-on-the-roadmap) section at the bottom — those aren't commitments, just a list of things worth considering when we have bandwidth.

## Vision

An autonomous agent fleet that handles the operational burden of software development — planning, documentation, business analysis, architectural alignment — so small teams can focus on building product.

---

## Shipped

| Agent | Role | Status |
|---|---|---|
| **Workitems** | PO/PM: work decomposition (approval pattern), status reports, risk detection, Asana ↔ GitHub sync | Live |
| **Researcher** | Business analyst: research synthesis, competitive scans, story drafting, spec review | Live |
| **Docwriter** | Technical writer: API docs, release notes, doc PRs, freshness checks | Live |
| **Adr** | ADR linker: tags issues with governing ADRs, reviews PRs against them | Live |

Supporting infrastructure shipped:
- **Dispatch Router** Lambda routes `@mention` events from GitHub + Asana to the right runtime.
- **Asana webhook receiver** Lambda handles Asana event subscription, signature verification, and normalization.
- **`agent-dispatch.yml`** GitHub Actions workflow handles the GitHub mention path.
- **Per-agent Cedar policies** under `cedar/<agent>.cedar` declare what each agent may and may not do.
- **Per-agent CI/CD** (`deploy-<agent>.yml`) on push to `main`, plus a reusable `deploy-agent.yml` that handles build, Inspector scan, AgentCore Runtime create/update, registry sync, and smoke test.
- **Skills** under `skills/` drive guided install into a new repo/account.

All four agents run Claude Opus 4.7 via Bedrock.

---

## Near-term (next 1–2 quarters, order is priority)

1. **Provision AgentCore Memory in the foundation template.** Agents already honor `AGENTCORE_MEMORY_ID`; what's missing is a Memory resource in `infra/foundation/template.yaml` and a documented seeding path per agent.
2. **Slack dispatch.** `.dispatch/agents.yaml` advertises Slack triggers but there's no Slack event receiver Lambda or signing-secret path. Needs a new receiver, a Slack app manifest, and routing through the existing Dispatch Router.
3. **Cedar enforcement in the invocation path.** Today Cedar policies are advisory — they document the contract. Hard enforcement via a policy evaluator invoked before each tool call is the next step.
4. **AgentCore Evaluations.** Each agent ships with `tests/eval_dataset.json`. The evaluation pipeline that scores runs against those datasets isn't wired up.
5. **Per-assignment cost tracking.** Token usage is available in Bedrock response metadata; surface it to the DynamoDB assignments table so we can report cost per run per agent.

---

## Medium-term (the interesting work, no commitment)

### Jira + GitLab support
Atlassian has an official remote MCP server (Jira, Confluence, Compass under one OAuth). The agent-side changes are small (point at a different MCP URL, tune prompts for Jira terminology). The dispatch side needs a Jira webhook receiver.

GitLab is harder — no production-grade official remote MCP. Community options exist (`zereight/gitlab-mcp`). Each shipping agent's system prompt would need merge-request vs. pull-request terminology adjustments.

### UAT agent
Generate Playwright tests from user stories and run them against staging. Requires a real solution for test-maintenance across UI changes, not just test-generation. Depends on AgentCore Browser (or a browser-in-Lambda fallback).

### Feedback agent
A Haiku-based agent that watches human edits to other agents' output and writes corrections to the fleet's memory. Depends on Memory being provisioned and populated (item 1 above).

### Cedar enforcement in Dispatch
Beyond tool-call-time enforcement, evaluate the full policy graph at the assignment level so the router can reject attempts before invoking the runtime.

---

## Ideas — not on the roadmap

Collected from earlier design sessions. Worth considering, not committed to.

- **Merge agent** — PR readiness checklist, release assembly, GTM handoff. Design doc deleted; spec was aspirational.
- **Triage agent** — Support case triage against known issues; escalate novel ones.
- **Diagnostics agent** — Incident timeline reconstruction from Datadog + PagerDuty.
- **Monitor agent** — Scheduled observability sweeps; file new issues for novel patterns.
- **Securityreviewer agent** — Threat-modeling partner on design docs; security review on PRs.
- **Bugreproducer agent** — Reproduce filed bugs with a failing test.
- **Gtm agent** — Changelogs and announcement drafts from releases.
- **Figma integration** — Pull design tokens into Docwriter, wire Figma webhooks to Dispatch.
- **AgentCore Gateway migration** — Centralize MCP access through one managed endpoint instead of per-agent direct connections.
- **AgentCore Identity migration** — Replace the SSM credential paths with a centralized Identity vault and `@requires_access_token` pattern.
- **Trello, Aha!, Linear PM support** — Workitems with different backends.
- **Fleet dashboard** — A production-grade view showing cost, eval scores, and assignment history per agent.

---

## Document Index

Current docs in this repo:

| Document | Purpose |
|----------|---------|
| [`01-prfaq-agent-fleet.md`](01-prfaq-agent-fleet.md) | Press release + FAQ framing the problem and solution |
| [`02-prd-agent-fleet.md`](02-prd-agent-fleet.md) | Requirements (Shipped / Roadmap per item) |
| [`03-design-agent-fleet.md`](03-design-agent-fleet.md) | System architecture as shipped |
| [`aws-deploy.md`](aws-deploy.md) | What the project provisions in AWS + deterministic-deploy requirements |
| [`agent-fleet-implementation-plan.md`](agent-fleet-implementation-plan.md) | Status doc (shipped vs. deferred) |
| [`agents/*.md`](agents/) | Per-agent design docs for the four shipping agents |
| [`specs/*.md`](specs/) | Detailed specs for each shipping agent + the Dispatch routing layer |
| [`ai-pdlc-toolchain-map.md`](ai-pdlc-toolchain-map.md) | Role-by-role toolchain thinking (context, not spec) |
| [`bot-patterns-recommendations.md`](bot-patterns-recommendations.md) | Bot-pattern survey (context, not spec) |
