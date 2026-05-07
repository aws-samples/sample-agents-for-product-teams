---
name: sdlc-agents-setup-claude-code
description: Use when the user wants to enable Claude Code on Amazon Bedrock in their GitHub repo so @claude can respond on issues, code against issues, and review pull requests. Installs the claude-code.yml workflow, configures the Bedrock IAM role + OIDC trust, and verifies that @claude responds end-to-end. Complements the main SDLC Agent Fleet but is scoped to GitHub + Bedrock only.
---

# Enable Claude Code on Amazon Bedrock in a GitHub repo

## What this gives the user

Two capabilities, one workflow:

1. **Issue coding** — on `@claude` in an issue/comment, Claude Code clones the repo, reads the conversation, and opens a PR with an implementation.
2. **PR code review** — on a new PR or `@claude review` comment, Claude Code reviews the diff, leaves inline comments, and posts a summary.

Both use the same `anthropics/claude-code-action@v1` GitHub Action, authenticated to **Amazon Bedrock** via **GitHub Actions OIDC** — no long-lived Anthropic API key, no Claude.ai auth, no `CLAUDE_CODE_OAUTH_TOKEN`. The action invokes `us.anthropic.claude-opus-4-7-v1` through Bedrock `InvokeModel`.

## Why Bedrock (vs API key)

- **Single identity boundary**: same AWS account that hosts the SDLC agent fleet already pays for and audits Claude usage.
- **No secret rotation**: OIDC tokens are short-lived and scoped to the repo.
- **CloudTrail visibility**: every `InvokeModel` call lands in CloudTrail, which matters for security reviews and cost attribution.

Use an Anthropic API key instead only if the user has a constraint that forces it (e.g. no AWS account, or a different region story than their fleet).

## Prerequisites

- A GitHub repo the user admins.
- AWS account with **Bedrock model access enabled** for `us.anthropic.claude-opus-4-7-v1` in the region Claude Code will run in (default `us-east-1`). The region is independent of where the SDLC agent fleet runs — Claude Code only needs `bedrock:InvokeModel` from CI runners.
- `gh` CLI authenticated as a repo admin (for setting secrets/variables); or the user can click through the UI.
- If using the SDLC Agent Fleet: `sdlc-agents-provision-aws` Step 0 already created a deploy role (default name `sdlc-agents-deploy`). You can either reuse it (simplest) or create a dedicated `ClaudeCodeBedrockRole` (cleaner blast radius). This skill does the dedicated-role path — reuse is a footnote at the end.

## Collect values up front

Ask the user and record:

- `AWS_ACCOUNT_ID` — 12 digits
- `AWS_REGION` — the region Claude Code will call Bedrock in (default `us-east-1`; must have Opus 4.7 model access)
- `GITHUB_ORG` and `GITHUB_REPO` — scopes the OIDC trust policy
- Which events should trigger Claude (defaults below are sensible):
  - `@claude` in issue or issue comment → code against issue and open PR
  - `@claude` in PR review comment → respond to the review
  - PR opened/synchronize → auto-review every PR (opt-in; noisy on busy repos)

## Step 1 — Verify Bedrock model access

```bash
aws bedrock get-foundation-model \
  --model-identifier us.anthropic.claude-opus-4-7-v1 \
  --region "$AWS_REGION"
```

If this returns `ResourceNotFoundException`, stop and tell the user to request access in the Bedrock console (Model access → Opus 4.7) before continuing. Provisioning IAM/OIDC without model access will succeed but the first `@claude` run will 403.

## Step 2 — Create the IAM role for Claude Code

The role needs two permissions: `bedrock:InvokeModel` on the target model (and the cross-region inference profile if using one), and the trust policy to be assumed by GitHub Actions OIDC from the specific repo.

### 2a. Ensure the GitHub OIDC provider exists in the account

```bash
aws iam list-open-id-connect-providers \
  | grep -q 'token.actions.githubusercontent.com' \
  || aws iam create-open-id-connect-provider \
       --url https://token.actions.githubusercontent.com \
       --client-id-list sts.amazonaws.com \
       --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1
```

(Idempotent — skip if already present. `sdlc-agents-provision-aws` Step 0a creates one for the fleet; reuse it.)

### 2b. Create the role with a scoped trust policy

```bash
cat > /tmp/trust.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {
      "Federated": "arn:aws:iam::${AWS_ACCOUNT_ID}:oidc-provider/token.actions.githubusercontent.com"
    },
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": {
        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
        "token.actions.githubusercontent.com:sub": [
          "repo:${GITHUB_ORG}/${GITHUB_REPO}:ref:refs/heads/main",
          "repo:${GITHUB_ORG}/${GITHUB_REPO}:pull_request"
        ]
      }
    }
  }]
}
EOF

aws iam create-role \
  --role-name ClaudeCodeBedrockRole \
  --assume-role-policy-document file:///tmp/trust.json \
  --description "Invoked by GitHub Actions in ${GITHUB_ORG}/${GITHUB_REPO} to call Bedrock for Claude Code" \
  || echo "(role exists — update trust policy if org/repo changed)"

rm /tmp/trust.json
```

**Why two explicit subjects and not `:*`:** `StringLike: repo:<org>/<repo>:*` allows any branch, tag, or environment in the repo to assume the role — including feature branches that haven't been reviewed. The `claude-code.yml` workflow needs exactly two subjects: `pull_request` (only emitted for the `pull_request: [opened, synchronize]` trigger, the sole "pull request event" in OIDC terms) and `ref:refs/heads/main` (the default-branch sub — emitted for `issue_comment`, `pull_request_review`, and `pull_request_review_comment`, all of which run in the default-branch context). Enumerating them with `StringEquals` is the default here. If you share the role across multiple repos, extend the list — one entry per `<org>/<repo>` per subject — rather than falling back to `StringLike` with wildcards.

### 2c. Attach the Bedrock permission

```bash
cat > /tmp/bedrock-invoke.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": [
      "bedrock:InvokeModel",
      "bedrock:InvokeModelWithResponseStream"
    ],
    "Resource": [
      "arn:aws:bedrock:${AWS_REGION}::foundation-model/anthropic.claude-opus-4-7-v1:0",
      "arn:aws:bedrock:*::foundation-model/anthropic.claude-opus-4-7-v1:0",
      "arn:aws:bedrock:${AWS_REGION}:${AWS_ACCOUNT_ID}:inference-profile/us.anthropic.claude-opus-4-7-v1"
    ]
  }]
}
EOF

aws iam put-role-policy \
  --role-name ClaudeCodeBedrockRole \
  --policy-name BedrockInvokeOpus47 \
  --policy-document file:///tmp/bedrock-invoke.json

rm /tmp/bedrock-invoke.json
```

Opus 4.7 is served through a **cross-region inference profile** (`us.*` prefix) — both the profile ARN and the underlying foundation-model ARN (in any region the profile routes to) must be allowed. The wildcard region on the foundation-model ARN covers that without enumerating each region the profile might land on.

Capture the role ARN:

```bash
ROLE_ARN=$(aws iam get-role --role-name ClaudeCodeBedrockRole --query 'Role.Arn' --output text)
echo "$ROLE_ARN"
```

## Step 3 — Install the workflow in the user's repo

Drop this file at `.github/workflows/claude-code.yml` in the target repo:

```yaml
name: Claude Code Assistant

on:
  issue_comment:
    types: [created]
  pull_request_review_comment:
    types: [created]
  pull_request_review:
    types: [submitted]
  pull_request:
    types: [opened, synchronize]
  issues:
    types: [opened, assigned, labeled]

jobs:
  claude-response:
    # Respond on:
    #   - any PR open/sync (auto-review — remove this line to make review explicit-only)
    #   - @claude in an issue, issue comment, or PR review comment
    if: |
      github.event_name == 'pull_request' ||
      (github.event_name == 'issue_comment' && contains(github.event.comment.body, '@claude')) ||
      (github.event_name == 'pull_request_review_comment' && contains(github.event.comment.body, '@claude')) ||
      (github.event_name == 'issues' && contains(github.event.issue.body, '@claude'))
    runs-on: ubuntu-latest
    permissions:
      contents: write
      pull-requests: write
      issues: write
      id-token: write
      actions: read
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 1

      - name: Configure AWS Credentials (OIDC)
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.CLAUDE_CODE_ROLE_ARN }}
          aws-region: ${{ vars.CLAUDE_CODE_AWS_REGION || 'us-east-1' }}

      - uses: anthropics/claude-code-action@v1
        with:
          use_bedrock: "true"
          claude_args: |
            --model us.anthropic.claude-opus-4-7-v1
```

**Two knobs to tune before the user commits:**

1. **Auto-review on every PR vs explicit `@claude review`.** The `pull_request` trigger above runs on *every* push to *every* PR. On active repos this gets noisy and spendy. To make review explicit:

   - Remove `github.event_name == 'pull_request' ||` from the `if:` condition.
   - Remove the `pull_request` entry from `on:`.

   Now `@claude review` in a PR comment triggers it; nothing auto-runs.

2. **Issue coding gate.** The condition above triggers on *any* issue body containing `@claude`. Narrower options:

   - `issues.types: [labeled]` only + check `contains(github.event.label.name, 'claude')` — only run when someone labels the issue `claude`.
   - Keep mention-based but ignore bot mentions: add `&& github.event.sender.type != 'Bot'`.

Commit the file on a branch, push, open a PR. (Don't push straight to `main` — Claude Code won't be triggerable to review itself yet.)

## Step 4 — Wire up the secrets and variables

In the target repo — `Settings → Secrets and variables → Actions`:

| Kind | Name | Value |
|---|---|---|
| Secret | `CLAUDE_CODE_ROLE_ARN` | the `$ROLE_ARN` from Step 2c |
| Variable | `CLAUDE_CODE_AWS_REGION` | the `$AWS_REGION` from prerequisites (optional — defaults to `us-east-1` if omitted) |

Via `gh`:

```bash
gh secret   set CLAUDE_CODE_ROLE_ARN      --body "$ROLE_ARN"
gh variable set CLAUDE_CODE_AWS_REGION    --body "$AWS_REGION"
```

The role ARN is a **secret** because it identifies a specific role in a specific account that someone could target for misconfiguration probes. The region is a **variable** because there's no sensitivity to it — it just shapes which endpoint the action hits.

## Step 5 — Verify

Three checks, in order. Don't skip — each catches a different class of failure.

### 5a. IAM simulation (offline, fast)

```bash
aws iam simulate-principal-policy \
  --policy-source-arn "$ROLE_ARN" \
  --action-names bedrock:InvokeModel \
  --resource-arns "arn:aws:bedrock:${AWS_REGION}:${AWS_ACCOUNT_ID}:inference-profile/us.anthropic.claude-opus-4-7-v1" \
  --query 'EvaluationResults[0].EvalDecision' --output text
```

Must print `allowed`. If it prints `implicitDeny` or `explicitDeny`, re-check the role policy (Step 2c).

### 5b. CI reaches Bedrock (live, but cheap)

On the branch where you added `claude-code.yml`, open a PR with a trivial change. The workflow should:

1. Start within ~10s of PR open
2. Successfully run the "Configure AWS Credentials (OIDC)" step
3. Proceed to the `claude-code-action` step

Inspect the run:

```bash
gh run list --workflow "Claude Code Assistant" --limit 1
gh run view <run-id> --log
```

**Expected failures to debug:**

| Symptom | Cause | Fix |
|---|---|---|
| `Could not assume role with OIDC: Not authorized to perform sts:AssumeRoleWithWebIdentity` | Trust policy doesn't allow this repo | Check `sub` condition in Step 2b — must match `repo:<org>/<repo>:ref:refs/heads/main` or `repo:<org>/<repo>:pull_request` |
| `AccessDeniedException when calling InvokeModel` | Role lacks Bedrock permission | Re-check the inline policy from Step 2c; confirm resource ARNs match the region |
| `You don't have access to the model with the specified model ID` | Bedrock model access not enabled | Request access in Bedrock console → Model access → Opus 4.7 |
| Action runs but `@claude` gets no response | Condition in `if:` didn't match | Check event name + body in the run logs; adjust the condition |

### 5c. End-to-end user test

Ask the user to post `@claude hello, can you see this?` as a comment on any issue in the repo. Within ~30s Claude Code should post a reply. If silent after 90s:

- `gh run list` — was a workflow triggered at all?
- If yes: check the log for which step failed.
- If no: the `if:` condition excluded this event. Usually missing `@claude` substring or a PR vs issue mismatch.

## Reusing the existing deploy role (footnote)

If the user already has `sdlc-agents-deploy` from `sdlc-agents-provision-aws` Step 0, they can attach the Bedrock inline policy from Step 2c to *that* role and set `CLAUDE_CODE_ROLE_ARN` to the existing `AWS_DEPLOY_ROLE_ARN`. One fewer role to manage, at the cost of a broader blast radius: if `@claude` gets compromised (via prompt injection that extracts secrets), an attacker has deploy privileges. For production, keep the roles separate.

## What this skill does NOT do

- Configure Claude Code outside GitHub Actions (IDE, local CLI, or desktop app) — that path uses the user's personal Claude account, not Bedrock.
- Install Claude Code Action v0.x — the `@v1` path is stable and the only supported Bedrock integration as of this writing.
- Handle non-Anthropic models via Bedrock — the action expects `anthropic.*` model IDs.
- Filter or redact repo contents before they go to Bedrock. Bedrock's Anthropic models do not train on customer data, but if the repo has regulated content (PHI, export-controlled code) the user needs a separate review before enabling `@claude` at all. Flag this; don't paper over it.
