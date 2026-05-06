# Adr

**Role:** ADR agent — links issues and PRs to the architecture decisions that govern them
**Status:** Shipped — live on AgentCore Runtime
**Trigger:** `@adr` mention on a GitHub issue or pull request
**Code:** [`agents/adr/`](../../agents/adr/)
**Spec:** [`docs/specs/adr-agent-spec.md`](../specs/adr-agent-spec.md)

## What Adr does

Adr keeps architecture decisions connected to the work that implements them. It runs in three modes depending on what it's mentioned on:

- **On an issue** — reads the issue, scans the repo's ADR directory, labels the issue with `adr-<number>` for each matching ADR, and posts a single rationale comment explaining why each applies.
- **On a PR that links an issue** (`Closes #N`) — reads the PR diff, pulls the linked issue's existing ADR labels, and posts review comments where the diff conflicts with those ADRs' guidance.
- **On a PR with no linked issue** — reads the diff, infers candidate ADRs from the code paths touched, and posts review comments marked "suggested" (lower confidence since there's no issue-scoped ground truth).

It's read-only toward code and ADRs themselves — it reads the ADR library, it doesn't write to it.

## Prerequisites

The target repo must already have an ADR directory. Default search paths (first hit wins): `docs/adrs`, `adrs`, `ADRs`, `docs/decisions`, `architecture/decisions`. Override with `.pdlc-agents/adr.yaml → adr_dir`.

If no ADR directory exists, Adr posts a single "no ADRs found" comment and stops. It does not try to operate without ADRs.

## Operating modes

| Mode | Mention target | What happens |
|---|---|---|
| `TAG_ISSUE` | `@adr` on issue | Match issue → ADRs, apply `adr-<N>` labels, post rationale comment |
| `REVIEW_PR_LINKED` | `@adr` on PR with `Closes #N` in body | Review diff against the linked issue's ADR labels, post PR review comments |
| `REVIEW_PR_UNLINKED` | `@adr` on PR without a linked issue | Review diff against directory-inferred ADRs, post "suggested" review comments |

## ADR format assumed

- One markdown file per ADR under the configured directory
- **Number** parsed from filename (`0001-use-postgres.md` → `1`) or first-line heading
- **Title** from the first `# ` heading (stripping any `ADR-NNNN:` prefix)
- **Status** from the first non-empty line in the `## Status` section, normalized to `proposed | accepted | deprecated | superseded`
- Missing status defaults to `accepted`; missing number falls back to filename

Configurable via `.pdlc-agents/adr.yaml`:

```yaml
adr_dir: docs/adrs
confidence_threshold: 0.65
require_status: accepted   # only match ADRs with this status; "any" to include all
auto_tag_on_open: false    # v1.2: run on issues.opened without needing @adr
```

## How Adr fits in

```
GitHub issue or PR
    ↓  @adr mention
Adr
    ├─ issue         → tag with ADR labels, rationale comment
    ├─ PR + linked   → review against linked issue's ADR labels
    └─ PR + no link  → review against directory-inferred ADRs (suggested)
```

Adr sits upstream of `@claude` and the Workitems agent — the labels and rationale land before implementation starts, so decisions frame the work rather than being retrofitted after the fact. It runs alongside Securityreviewer on PRs; the two agents cover different scopes (architecture governance vs. threat modeling) and their findings don't overlap.

## Infrastructure

- GitHub MCP (existing) for issue/PR reads, label writes, comment writes
- AgentCore Memory for the per-repo ADR index (cached between invocations; refreshed on ADR-dir change)
- Bedrock Titan for semantic embeddings (keyword + semantic matching combined)
- No external integrations beyond GitHub

## Guardrails (Cedar)

- **Never** writes or modifies files under the ADR directory
- **Never** closes, edits, or resolves issues
- **Never** approves or merges PRs
- **Never** reapplies a `adr-<N>` label that a human has removed on the same issue/PR
- All label writes limited to `adr-*` prefix
- All rationale comments cite the specific ADR and its status

See [`cedar/adr.cedar`](../../cedar/adr.cedar).

## Rollout

- **MLP:** `TAG_ISSUE` + `REVIEW_PR_LINKED`
- **v1.1:** `REVIEW_PR_UNLINKED` with suggestion-only findings
- **v1.2:** Auto-tag on `issues.opened` (gated by config)
- **v1.3:** Gap detection — propose ADR titles when work implies a new decision
- **v2:** GitLab support via the fleet's GitLab MCP target

See [`docs/specs/adr-agent-spec.md`](../specs/adr-agent-spec.md) for the full design.
