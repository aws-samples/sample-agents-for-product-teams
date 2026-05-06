# ADR Agent — Spec

**Status:** Shipped — live on AgentCore Runtime
**Trigger:** `@adr` mention on GitHub issues or pull requests; `issues.opened`/`issues.edited` webhook events (optional, config-gated)
**Source control scope:** GitHub only (for MLP; GitLab support follows the fleet's generic path)

## Problem

Architecture decisions are written down in ADRs, and then nobody reads them. By the time a developer picks up an issue — or worse, opens a PR — the relevant ADRs are either unfamiliar or forgotten. Teams re-litigate settled decisions, implement against deprecated guidance, or ship code that silently violates an accepted pattern.

Existing linting tools don't cover this because ADRs encode *intent*, not syntax.

## What ADR does

**On an issue:** reads the issue body + comments, scans the repo's ADR directory, applies `adr-<number>` labels for each matching ADR, and posts one consolidated rationale comment explaining why each applies (with status flags: accepted / deprecated / superseded). Doesn't modify the issue body.

**On a PR that references an issue:** reads the PR diff + the linked issue's existing `adr-<N>` labels (from the step above), then reviews the diff against those specific ADRs' constraints and posts PR review comments where the diff conflicts with ADR guidance. Linked-issue ADRs are the authoritative scope — this is the highest-signal case.

**On a PR that does not reference an issue:** reads the diff, infers which ADRs *could* apply from the code paths touched, reviews the diff against those, and posts review comments marked "suggested, no linked issue." Strictly lower confidence; clearly labeled so reviewers can downweight.

## What ADR does NOT do

- Write, edit, or propose new ADRs. Teams write ADRs; the agent reads them.
- Close issues or approve/merge PRs. Findings are advisory.
- Auto-dismiss findings reviewers disagree with — humans dismiss, agent observes and doesn't re-apply the same label twice on the same issue once a reviewer has manually removed it.
- Deeply analyze superseded or deprecated ADRs — on a match to one, it names the successor and stops there.

## Operating modes

One entrypoint (`@app.entrypoint`), three internal modes dispatched off the payload:

| Mode | Triggered by | Output |
|---|---|---|
| `TAG_ISSUE` | `@adr` on issue or `issues.opened/edited` when the optional auto-tag is enabled | Issue labels + one rationale comment |
| `REVIEW_PR_LINKED` | `@adr` on PR where the PR body contains `Closes #N` / `Fixes #N` | PR review comments scoped to issue N's ADR labels |
| `REVIEW_PR_UNLINKED` | `@adr` on PR with no linked issue | PR review comments with "suggested" severity, scoped to directory-inferred ADRs |

## ADR discovery

Directory is configurable per repo via `.pdlc-agents/adr.yaml`:

```yaml
adr_dir: docs/adrs       # default; search order: docs/adrs, adrs, ADRs, docs/decisions, architecture/decisions
confidence_threshold: 0.65  # below this, findings are "suggestions" not hard labels
require_status: accepted    # only match ADRs with this status; "any" to match all
```

If the config file is absent, the agent tries the common paths in order and uses the first one that exists. If none exist, it posts a single comment: *"No ADR directory found. Add ADRs at `docs/adrs/` and re-mention me."* Then stops.

## ADR format assumptions

Each ADR is one markdown file. The agent parses:

- **Number** — from the filename (`0001-use-postgres.md` → `1`) or first-line heading (`# ADR-0001: Use Postgres`)
- **Title** — from the first `# ` heading, excluding any `ADR-NNNN:` prefix
- **Status** — first `## Status` section's first non-empty line; normalized to `proposed | accepted | deprecated | superseded`
- **Supersedes / superseded-by** — optional cross-refs, `## Superseded by ADR-0042` style
- **Body** — everything else; used for semantic matching

The agent is lenient — missing status is treated as `accepted`, missing number defers to filename.

## Matching

Two signals, combined:

1. **Keyword overlap** — ADR's title + body terms vs. issue/PR content. Cheap, catches explicit references.
2. **Semantic similarity** — embed the issue/PR content and each ADR body using Bedrock Titan embeddings; cosine similarity. Catches the cases where the issue describes a scenario governed by an ADR without naming the ADR directly.

Combined score > `confidence_threshold` → match. Scores under threshold → suggestion-only in the unlinked-PR case, dropped in the issue-tag case.

## Rationale comment format

One comment per run, signed. Per matched ADR:

```
🏛️ **[ADR Agent]**

This work is governed by the following architecture decisions:

- **ADR-0012** — Use JWT for service-to-service auth (status: accepted)
  *Applies because the issue describes a new internal API endpoint. ADR-0012 mandates JWT validation on all `/internal/*` routes.*
- **ADR-0019** — Postgres as the primary OLTP store (status: accepted)
  *Applies because the issue involves storing user preference data. ADR-0019 prohibits introducing new datastores without an ADR update.*

Applied labels: `adr-0012`, `adr-0019`.

If any of these don't actually apply, remove the label — I won't re-apply a label a human has removed.
```

On the unlinked-PR path, the same format but each bullet prefixed with `[suggested]` and no labels applied.

## Tools (custom Strands @tool functions)

One file per tool, kept small:

- `index_adrs(adr_dir)` — parse the ADR directory into a structured index. Cached per invocation; re-parses each run (directory is small).
- `match_issue_to_adrs(issue_body, adr_index)` — runs keyword + semantic matching, returns ranked `{adr, score, rationale}` list.
- `match_pr_to_adrs(pr_diff, adr_index, scoped_adr_numbers=None)` — same shape. When `scoped_adr_numbers` is passed (linked-issue case), only those ADRs are evaluated.
- `find_linked_issues(pr_body)` — parses `Closes #N` / `Fixes #N` / `Resolves #N` patterns.

All tools return structured dicts; the agent composes the rationale comment and calls GitHub MCP to apply labels / post comments.

## Memory

- Per-repo ADR index cached in AgentCore Memory (`/agents/adr/<repo>/index`). Refreshed when ADR files change (detected by last-commit SHA on the directory). Avoids re-embedding the same ADR library on every run.
- Per-issue "applied labels" ledger (`/agents/adr/<repo>/applied/<issue_number>`). Lets us respect human removal — if a label was present in the ledger and is no longer on the issue, we don't re-apply it.

## Guardrails (Cedar)

Reuses the shared forbid list (no close / no merge / no delete). Additional per-agent allow list:

- `github_get_file`, `github_list_files`, `github_search_code` — read ADR dir
- `github_get_issue`, `github_list_issues`, `github_get_pr`, `github_list_prs`
- `github_add_label`, `github_remove_label` (only labels matching `adr-*` prefix)
- `github_add_comment`, `github_add_pr_review_comment`
- `bedrock:InvokeModel` (for embeddings + reasoning)

Explicitly forbidden beyond the shared list:
- Modifying any file under the configured `adr_dir`
- Creating or closing issues
- Pushing any branch

## Repo config convention

```yaml
# .pdlc-agents/adr.yaml (in the target repo)
adr_dir: docs/adrs
confidence_threshold: 0.65
require_status: accepted
auto_tag_on_open: false   # if true, agent runs on issues.opened without needing @adr
```

## Infrastructure

- AgentCore Runtime: `adr` — pattern-identical to `docwriter`
- ECR: `sdlc-agents/adr`
- IAM role: `adr-agentcore-runtime` (cloudwatch-logs, dynamodb-assignments, ecr-pull, ssm-read-github-mcp)
- Cedar policy: `cedar/adr.cedar`
- Workflow: `.github/workflows/deploy-adr.yml`

## Rollout

1. **MLP (this spec):** `TAG_ISSUE` + `REVIEW_PR_LINKED`. Ship after single-repo eval passes a hand-graded test set of 20 real issues/PRs.
2. **v1.1:** `REVIEW_PR_UNLINKED` with explicit "suggested" labeling on findings.
3. **v1.2:** Auto-tag on `issues.opened` (gated by `auto_tag_on_open`).
4. **v1.3:** Gap detection — when an issue describes work that implies a decision with no covering ADR, agent comments suggesting an ADR title and stops. (Deferred — easy to over-fire.)
5. **v2:** GitLab support via the fleet's GitLab MCP target.
