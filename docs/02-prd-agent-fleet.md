# Product Requirements Document
## Autonomous PDLC Agent Fleet

**Document Version:** 2.0
**Date:** April 2026
**Status:** v1 shipped — four agents live. Sections marked "Roadmap" are planned, not implemented.

---

## 1. Problem Statement

Small development teams building software products face a fundamental scaling problem: the ratio of "work about work" to actual value-creating work grows as the product matures. A team of 2–5 developers spends significant engineering time on activities that don't require human judgment — syncing project tracking tools, writing status reports, maintaining documentation, reviewing specs for completeness, and keeping architectural intent aligned with the code being shipped.

These tasks are critical but mechanical. They don't require creativity or domain judgment — they require thoroughness, consistency, and timeliness. When they slip under deadline pressure, the consequences compound: specs enter development incomplete, docs become stale, stakeholders get outdated information, and architectural decisions get forgotten or re-litigated.

Those tasks map cleanly to specialized roles — project manager, business analyst, technical writer, architecture historian — but a small team cannot afford dedicated headcount for each. An autonomous agent fleet can fill these roles at a fraction of the cost, with better consistency, and with safety guardrails (Cedar) that make them safe to run in production from day one.

## 2. Target Users

### Primary: The Developer / Small Team Lead
Writes code, manages the project, writes docs, and talks to stakeholders. Needs to offload everything except coding and strategic decisions. Interacts with agents via `@mentions` in GitHub and Asana. Reviews agent output rather than producing it from scratch.

### Secondary: The Product Owner
Defines what to build and prioritizes the backlog. Needs timely status reports, competitive intelligence, and impact estimates without compiling data from multiple tools. Consumes agent output (status reports, decision packages, competitive briefs) and approves Workitems's proposed decompositions.

### Tertiary: Stakeholders and Leadership
Need visibility into project status. Consume Workitems's status reports and Docwriter's release notes. Never interact with agents directly.

## 3. Product Vision

A fleet of autonomous AI agents that operate as specialized team members across the software development lifecycle, coordinated through a unified `@mention` interface — enabling a small team to offload the work-about-work and stay focused on creative and judgment-heavy tasks.

## 4. Agent Roster and Responsibilities

### 4.1 Workitems (`@workitems`) — Project Manager

**Responsibility:** Keeps the project organized and stakeholders informed.

| ID | Requirement | Priority | Status |
|----|------------|----------|--------|
| P-01 | Decompose an Asana task into a proposed plan and post it as an Asana comment | P1 | Shipped |
| P-02 | On human approval, create the proposed GitHub issues with acceptance criteria | P1 | Shipped |
| P-03 | Sync GitHub issue and Asana task status bidirectionally | P1 | Shipped |
| P-04 | Generate status reports from GitHub + Asana data | P1 | Shipped |
| P-05 | Detect risks: stale issues, blocked PRs, past-due tasks, at-risk milestones | P1 | Shipped |
| P-06 | Trigger `@docwriter` when a merged change affects documentation | P2 | Shipped |
| P-07 | Review Claude's work against acceptance criteria | P2 | Roadmap |
| P-08 | Predict sprint completion likelihood based on velocity trends | P3 | Roadmap |

### 4.2 Researcher (`@researcher`) — Business Analyst

**Responsibility:** Turns raw signals into actionable product inputs.

| ID | Requirement | Priority | Status |
|----|------------|----------|--------|
| L-01 | Review user stories for completeness (missing AC, ambiguities, untestable conditions) | P1 | Shipped |
| L-02 | Synthesize qualitative research (transcripts, surveys, support tickets) into themed findings | P1 | Shipped |
| L-03 | Draft user stories with personas, acceptance criteria, and dependencies | P1 | Shipped |
| L-04 | Analyze the backlog for duplicates, gaps, and prioritization inconsistencies | P1 | Shipped |
| L-05 | Run competitive scans via web search (Tavily), posting brief to the originating platform | P2 | Shipped |
| L-06 | RICE scoring across the backlog | P2 | Roadmap |
| L-07 | Feature impact modeling from usage analytics + qualitative research | P3 | Roadmap |

### 4.3 Docwriter (`@docwriter`) — Technical Writer

**Responsibility:** Keeps documentation accurate and current.

| ID | Requirement | Priority | Status |
|----|------------|----------|--------|
| I-01 | Generate release notes from merged PRs, categorized for end users | P1 | Shipped |
| I-02 | Generate API reference documentation from OpenAPI specs and source | P1 | Shipped |
| I-03 | Detect documentation gaps (undocumented endpoints, features missing guides) | P1 | Shipped |
| I-04 | Check doc freshness against code changes | P1 | Shipped |
| I-05 | Open doc PRs when merged code PRs affect docs | P2 | Shipped |
| I-06 | Confluence publishing for teams whose docs don't live in the repo | P3 | Roadmap |

### 4.4 Adr (`@adr`) — Architecture Decision Linker

**Responsibility:** Keeps architectural intent connected to the code that implements it.

| ID | Requirement | Priority | Status |
|----|------------|----------|--------|
| A-01 | Tag issues with `adr-<N>` labels for each matching ADR | P1 | Shipped |
| A-02 | Post a rationale comment on the issue explaining why each ADR applies | P1 | Shipped |
| A-03 | Review PRs that link an issue against that issue's ADR labels | P1 | Shipped |
| A-04 | Review PRs without a linked issue against ADRs inferred from touched code paths, clearly labeled lower-confidence | P1 | Shipped |
| A-05 | Flag ADRs marked deprecated or superseded and name the successor | P2 | Shipped |

### 4.5 Dispatch — Cross-Platform Routing Layer

**Responsibility:** Routes work to the right agent from any integrated platform.

| ID | Requirement | Priority | Status |
|----|------------|----------|--------|
| D-01 | Route `@agent` mentions from GitHub issue/PR comments to the correct AgentCore Runtime | P1 | Shipped |
| D-02 | Route `@agent` mentions from Asana task comments | P1 | Shipped |
| D-03 | Trigger agents via Asana task assignment to bot user accounts | P1 | Shipped |
| D-04 | Support agent aliases (`@pm` → `@workitems`) configurable in `.dispatch/agents.yaml` | P1 | Shipped |
| D-05 | Post agent results back to the originating platform in a platform-appropriate format | P1 | Shipped |
| D-06 | Track all assignments in DynamoDB with status, timing, and result references | P1 | Shipped |
| D-07 | Per-agent concurrency caps and daily token budgets enforced via registry | P1 | Shipped |
| D-08 | Slack event routing (mentions, slash commands) | P2 | Roadmap |
| D-09 | Slash commands (`/deploy`, `/approve`, `/disable`) for human control | P2 | Roadmap |
| D-10 | Approval-gate state machine for high-risk agent actions | P2 | Roadmap |

### 4.6 Fleet Memory — Shared Knowledge Layer (roadmap)

Agents honor an `AGENTCORE_MEMORY_ID` environment variable today (the Strands `AgentCoreMemoryToolProvider` is wired up), but no Memory resource is provisioned by the shipping infra template. Teams that want memory provision their own.

Planned when the operator story firms up:

| ID | Requirement | Priority | Status |
|----|------------|----------|--------|
| M-01 | Single AgentCore Memory resource with `/shared/`, `/agents/{id}/` namespaces | P1 | Roadmap |
| M-02 | All agents hydrate from shared + private namespaces on every invocation | P1 | Roadmap |
| M-03 | Memory seeding (domain knowledge, glossary, conventions) at setup | P2 | Roadmap |

## 5. Non-Functional Requirements

| ID | Requirement | Priority | Status |
|----|------------|----------|--------|
| NF-01 | No agent can merge PRs, close issues, delete tasks, or deploy to production (Cedar policy enforced) | P1 | Shipped |
| NF-02 | All agent actions logged to CloudWatch via OpenTelemetry | P1 | Shipped |
| NF-03 | OAuth tokens and PATs stored in SSM Parameter Store as SecureString, never in code or environment variables | P1 | Shipped |
| NF-04 | All agents deployed via CI/CD: GitHub Actions → ECR → Amazon Inspector scan → AgentCore Runtime | P1 | Shipped |
| NF-05 | Agent response time: < 5 minutes for standard operations | P1 | Shipped |
| NF-06 | Per-agent daily token budget, enforced in the dispatch registry | P1 | Shipped |
| NF-07 | Per-agent Cedar policy file in `cedar/<agent>.cedar` | P1 | Shipped |
| NF-08 | Fleet-wide CloudWatch dashboard with per-agent invocations, latency, errors | P2 | Roadmap |
| NF-09 | Prompt caching (Strands `CacheConfig`) targeting input-token reduction on repeated system prompts | P2 | Roadmap |
| NF-10 | Operational runbooks per agent (OAuth recovery, memory issues, escalation) | P2 | Roadmap |

## 6. Success Metrics

Concrete baselines and targets should be set per adopter; these are the categories worth tracking:

| Metric | Why it matters |
|---|---|
| Agent PR / comment acceptance rate (merged or acknowledged without major edits) | Direct signal of agent quality |
| Time spent on status reporting | Workitems's load-bearing value prop |
| Documentation shipped alongside features (vs. later) | Docwriter's load-bearing value prop |
| Mid-sprint change requests per story | Researcher's spec-review signal |
| ADR label coverage on in-flight issues | Adr's load-bearing value prop |
| Fleet operating cost per month | Cost governance |

## 7. Out of Scope

- **Code implementation** — handled by `@claude` (Claude Code Action) as a separate system (see `skills/pdlc-agents-setup-claude-code`)
- **Marketing copy and sales collateral** — the fleet automates the SDLC, not go-to-market
- **Customer support automation** — agents don't interact with the product's end users
- **Infrastructure provisioning and incident response** — out of scope today; see roadmap for SRE-facing agents
- **Security testing and code review** — out of scope today; `@claude` PR review covers the light-touch path
- **Final approval of any agent output** — all agent-generated artifacts require human review

## 8. Supported Toolchain Configurations

| Component | Supported today | Planned |
|---|---|---|
| Source control | **GitHub** | GitLab |
| Project management | **Asana** | Jira, Linear |
| Team communication | None (results post to origin platform only) | Slack event subscriptions |
| CI/CD | **GitHub Actions** | — |
| Cloud | **AWS** | Required (AgentCore is AWS-native) |
| Docs framework | Any (Docwriter output is Markdown by default) | Confluence publishing |

## 9. Dependencies

| Dependency | Owner | Risk |
|------------|-------|------|
| Amazon Bedrock AgentCore Runtime | AWS | Low |
| Strands Agents SDK (Python) | AWS Open Source | Low — actively maintained |
| Claude Opus 4.7 via Bedrock | Anthropic via AWS | Low — available on-demand in Bedrock |
| GitHub API + official remote MCP (`api.githubcopilot.com/mcp`) | GitHub | Low |
| Asana API + official MCP (`mcp.asana.com/v2/mcp`) | Asana | Low |
| Cedar policy engine | AWS | Low |

## 10. Status and Next

The v1 fleet is live. The four shipping agents handle work decomposition, status, research synthesis, doc generation, and ADR linking. The next priorities on the roadmap (in `docs/roadmap.md`) are:

1. Memory provisioning in the infra template so agents have persistent context out of the box.
2. Slack dispatch routing so status reports and mentions work in Slack.
3. Jira and GitLab support so teams not on Asana + GitHub can adopt.

## 11. Open Questions

| Question | Impact |
|----------|--------|
| Should agent-generated PRs auto-merge when CI passes and the PR is fully reviewed? | Velocity vs. safety; likely a per-repo opt-in |
| How should shared memory, once provisioned, be audited for accuracy? | Memory quality over time |
| Should cross-agent handoff (Workitems → Docwriter → Adr) be formalized with a protocol or stay as `@mention` comments? | Architecture complexity vs. early value |
