# Docwriter

**Role:** Technical writer — API docs, user guides, release notes
**Status:** Shipped — live on AgentCore Runtime
**Trigger:** `@docwriter` mention in GitHub, Asana, or Slack; PR merge events
**Code:** [`agents/docwriter/`](../../agents/docwriter/)
**Spec:** [`docs/specs/docwriter-agent-spec.md`](../specs/docwriter-agent-spec.md)

## What Docwriter does

Docwriter keeps documentation in sync with the codebase. It reads code and PRs
to understand what changed, then produces documentation that explains it to
the right audience.

## Operating modes

- **API_DOCS** — generates and maintains API reference docs from OpenAPI
  specs and source code. Every endpoint gets description, parameters,
  request/response samples, error codes, and both curl and SDK examples.
- **RELEASE_NOTES** — builds changelogs from merged PRs, categorized as
  New Feature / Improvement / Bug Fix / Breaking Change / Internal. Written
  for end users, not developers.
- **DOC_REVIEW** — reviews doc PRs for accuracy against code, completeness,
  style compliance, broken links, and stale content.
- **GAP_DETECT** — scans the codebase for undocumented features (API
  endpoints, UI features, config options) and files GitHub issues for each
  gap.
- **MAINTAIN** — when a code PR changes behavior, identifies affected docs
  and either opens a doc PR or flags them stale via an issue.

## How Docwriter fits in

Workitems triggers Docwriter by commenting `@docwriter` on a GitHub issue after
Claude's work is approved and merged. Docwriter reads the issue and related
PRs, then opens a documentation PR if docs are affected. Humans review
Docwriter's doc PRs directly — Workitems is not in that loop.

## Tools

- GitHub MCP (official remote server at `api.githubcopilot.com/mcp/`; PAT or GitHub App token from SSM)
- Asana MCP (official server at `mcp.asana.com/v2/mcp`; OAuth refresh-token flow, credentials in SSM)
- `generate_api_docs`, `generate_release_notes`, `check_doc_freshness`,
  `detect_doc_gaps`, `post_results` (custom Strands tools under
  `agents/docwriter/tools/`)
- AgentCore Memory (optional — honored via `AGENTCORE_MEMORY_ID` env var; no Memory resource is provisioned today)

## Guardrails

- **Never** modifies code files — only documentation.
- **Never** closes issues, merges PRs (including its own doc PRs), or
  deletes tasks.
- All doc PRs labeled `docwriter-generated` for traceability.
- Always cites the PR, commit, or spec that informed a doc change.

## Deployment

Containerized, deployed to Amazon Bedrock AgentCore Runtime. Built and pushed
via `.github/workflows/deploy-docwriter.yml` on changes under
`agents/docwriter/**`.

## Roadmap

- **Confluence publishing** — for teams whose docs live in Confluence rather
  than a repo. Add Atlassian's official Remote MCP Server
  (`https://mcp.atlassian.com/v1/mcp`) as a tool target (Docwriter would connect
  directly, the way it currently connects to Asana and GitHub MCP, or through
  Gateway if/when that migration lands). API_DOCS, RELEASE_NOTES, and MAINTAIN
  modes gain a Confluence output target alongside GitHub doc PRs. See
  [`docs/roadmap.md`](../roadmap.md).
