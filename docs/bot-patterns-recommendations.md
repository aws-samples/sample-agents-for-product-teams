# Bot Pattern Survey & Agent Fleet Recommendations
## Evolving GitHub Bot Patterns for the AI-Augmented PDLC

> **Status: context, not spec.** This document surveys long-established GitHub bot patterns (stale-bot, auto-labeler, deploy bots) and proposes how a reasoning-agent fleet could subsume them. Many recommendations reference agents (Uat, Feedback, Merge) and Workitems modes (TRIAGE, RELEASE, DEPLOY) that the shipping fleet does *not* implement. Use this for thinking about future direction; see [`roadmap.md`](roadmap.md) for what's planned and [`03-design-agent-fleet.md`](03-design-agent-fleet.md) for what's live.

---

## Part 1: Established Bot Patterns

The GitHub ecosystem has developed six categories of bot automation over the past decade. Most are rule-based (if X then Y). Our agent fleet replaces rule-based bots with reasoning agents, but there are patterns we haven't adopted yet that would make the fleet significantly more capable.

### 1. Issue Lifecycle Management

**What exists today:**
- **Stale bot** (probot/stale, actions/stale): marks and closes inactive issues after N days
- **Triage bot**: adds `triage` label to new issues, removes when other labels are added
- **Auto-labeler** (actions/labeler): applies labels based on file paths changed in PRs
- **Issue forms**: structured templates that collect severity, area, and type via dropdowns, parsed by Actions
- **Auto-assignment**: round-robin or load-balanced assignment based on labels or areas

**What we're missing:**
Our fleet has Workitems for risk detection and Researcher for backlog analysis, but neither owns the full issue lifecycle from creation to closure. There's no agent that triages *new* issues as they arrive — classifying severity, assigning to the right person, detecting duplicates in real-time, and ensuring nothing falls through the cracks.

**Recommendation: Add TRIAGE mode to Workitems**
When a new issue is created, Workitems should:
- Classify: bug / feature / question / support (using the issue body, not just the title)
- Estimate severity from description context (not just user-selected dropdown)
- Check for duplicates against existing open issues (Researcher's TF-IDF, but in real-time)
- Auto-assign based on component ownership (maintained in memory)
- Add appropriate labels
- If it's a question, draft an answer from docs and post as comment

This replaces 4 separate rule-based bots with one reasoning agent that understands context. A stale bot closes issues blindly; Workitems can assess *why* an issue is inactive and decide whether it should be closed, escalated, or re-assigned.

### 2. IssueOps / ChatOps

**What exists today:**
- **IssueOps** (github/command, github/branch-deploy): slash commands in PR comments trigger workflows. `.deploy staging`, `.noop`, `/approve`, `/lock`
- **ApproveOps**: require approval from specific team members via `/approve` comment before a workflow proceeds
- **Slash Command Dispatch** (peter-evans): parses commands from comments, dispatches to separate workflows for parallel processing

**What we're missing:**
Our Dispatch system handles @agent mentions, but doesn't support *slash commands* or *approval workflows*. We have no way for a human to say `/approve` on an agent's proposed action, and no way for agents to request human approval before proceeding with high-risk operations.

**Recommendation: Extend Dispatch with slash commands and approval gates**

Add to Dispatch Router:
```
/deploy staging          →  Triggers deployment pipeline
/approve                 →  Approves a pending agent action
/reject [reason]         →  Rejects with feedback
/lock deployments        →  Prevents any deployments (release freeze)
/unlock deployments      →  Lifts freeze
/status                  →  Workitems reports current project status
/budget [agent]          →  Shows agent's token spend for the day
/disable [agent]         →  Kill switch (the missing gap we identified)
/enable [agent]          →  Re-enable
```

And add an **approval gate** to the agent framework:
```python
@tool
def request_approval(
    action_description: str,
    risk_level: str,  # low, medium, high
    timeout_minutes: int = 60
) -> str:
    """Request human approval before proceeding with a risky action.
    
    Posts to the originating platform with an approval request.
    Blocks until /approve or /reject is received, or timeout.
    """
```

This gives you the kill switch and the human-in-the-loop escalation path that we identified as missing.

### 3. Release Management

**What exists today:**
- **semantic-release**: fully automated versioning from conventional commits. Determines next version, generates changelog, creates Git tag and GitHub Release.
- **changesets**: maintains "changeset" files per PR describing the change and version bump type. On release, aggregates into changelog.
- **Mergify**: auto-merges PRs when conditions are met (CI passes, approvals gathered, labels applied). Especially useful for Dependabot PRs.
- **auto** (intuit/auto): label-driven releases — PR labels like `patch`, `minor`, `major` control version bumps

**What we're missing:**
Docwriter generates release notes and changelogs, but doesn't own the release *process*. Nobody coordinates the full release flow: version bump → changelog → tag → deploy → announce → verify.

**Recommendation: Add RELEASE mode to Workitems with Docwriter collaboration**

Workitems becomes the release coordinator:
1. Developer comments `/release` on a PR or issue
2. Workitems checks: all PRs for this milestone are merged, all Uat tests pass, no open blockers
3. Workitems invokes Docwriter → generates release notes
4. Workitems requests approval: "/approve to release v2.4.0 to production"
5. On `/approve`, Workitems: bumps version (semantic-release pattern), creates tag, triggers deployment
6. Post-deploy: Workitems invokes Uat → smoke tests against production
7. On pass: Workitems announces in Slack, updates Asana status, closes milestone

This replaces semantic-release + Mergify + manual coordination with an agent that *reasons* about release readiness rather than following rules.

### 4. PR Quality Gates

**What exists today:**
- **Required status checks**: CI must pass, code coverage thresholds, lint checks
- **CODEOWNERS**: auto-request review from specific teams based on file paths
- **Auto-merge** (GitHub native): merge when all requirements met
- **PR size warnings**: bots that comment when PRs exceed a line count threshold
- **Conventional commit enforcement**: reject PRs with non-conforming commit messages
- **License compliance**: scan for incompatible dependency licenses

**What we're missing:**
@claude reviews code, AWS Security Agent reviews security, Uat reviews test coverage. But nobody enforces *process* quality: is the PR description complete? Does it link to an issue? Is the commit message conventional? Is the PR too large? Are the right reviewers assigned?

**Recommendation: Add a PR quality gate to the Dispatch workflow**

Before routing to any agent, add a lightweight check:
```yaml
pr-quality-gate:
  on: pull_request
  steps:
    - name: Check PR quality
      # Runs before any agent is invoked
      # Checks:
      # - PR description is not empty
      # - Links to GitHub issue or Asana task
      # - Commit messages follow conventional format
      # - PR is < 500 lines (warn) or < 1000 lines (block)
      # - CODEOWNERS review requested
      # - Labels applied (feature, fix, chore, docs)
      # If checks fail, posts a comment guiding the author
```

This is deliberately rule-based, not agent-based. You don't need LLM reasoning for "does this PR have a description?" Save agent tokens for work that requires judgment.

### 5. Dependency & Security Management

**What exists today:**
- **Dependabot**: auto-creates PRs for dependency updates, security patches
- **Renovate**: more configurable alternative to Dependabot with auto-merge policies
- **CodeQL** (GitHub native): SAST scanning, alerts on vulnerabilities
- **Socket**: detects supply chain attacks in npm/PyPI dependencies
- **License Bot**: flags PRs that introduce dependencies with incompatible licenses

**What we have:**
AWS Security Agent handles pen testing, code review, and design review. But it's focused on *your* code, not your *dependencies*.

**Recommendation: Keep Dependabot + add agent-assisted triage**

Don't replace Dependabot — it's excellent at what it does. But add a Dispatch-triggered flow:
- When Dependabot opens a PR, Dispatch routes to @claude for a contextual assessment: "Is this dependency actually used in a code path that's reachable in production? What's the real impact?"
- For major version bumps, route to Uat: "Run the full test suite against this dependency update before anyone reviews it"
- For security patches, route to Workitems: "Update the security status in Asana and notify the team"

This turns Dependabot from "noise that gets ignored" into "pre-assessed updates with context."

### 6. Environment & Deployment Ops

**What exists today:**
- **Branch deploy** (github/branch-deploy): deploy from a branch before merging via `.deploy` IssueOps command
- **Environment protection rules**: require approvals before deploying to production
- **Deploy locks**: prevent concurrent deployments
- **Noop deployments**: preview what would change without actually deploying (Terraform plan)
- **Canary/blue-green automation**: progressive rollout with automatic rollback on error metrics

**What we're missing:**
Our fleet tests (Uat) and reports (Workitems) but nobody owns the deployment coordination between environments. There's no agent that says "staging is green, production deploy is safe, here's what changed, do you want to proceed?"

**Recommendation: Add DEPLOY mode to Workitems**

Workitems becomes the deployment coordinator (not the deployer — it orchestrates):
```
1. PR merged → GitHub Actions deploys to staging automatically
2. Workitems detects staging deployment, invokes Uat: "Run smoke suite"
3. Uat reports: all green
4. Workitems posts to PR: "Staging verified ✅. To deploy to production, 
   comment /deploy production"
5. Human comments /deploy production
6. Workitems checks: deploy lock not held, no active incidents, tests passing
7. Workitems triggers production deployment via GitHub Actions
8. Workitems invokes Uat: "Run production smoke suite"
9. On pass: Workitems announces. On fail: Workitems alerts and offers /rollback
```

---

## Part 2: Patterns That Evolve Bots Into Agents

The patterns above are well-established. Here's where we push beyond what rule-based bots can do — things that only reasoning agents can handle.

### 7. Intelligent PR Routing

Rule-based CODEOWNERS assigns reviewers by file path. An agent can assign by *context*:

- "This PR changes the search algorithm" → assign the developer who built the original search, plus someone from the product team who owns search quality
- "This PR adds a new API endpoint" → assign a backend reviewer + trigger Docwriter for API doc check + trigger Security Agent for endpoint review
- "This is a one-line config change" → auto-approve if CI passes, no human review needed

Add this to Dispatch as a PR event handler.

### 8. Incident-Aware Development

AWS DevOps Agent handles incidents. But your fleet should be aware of incidents too:

- When DevOps Agent detects an incident, Workitems should pause non-critical scheduled runs and flag the team
- Uat should skip scheduled test runs against the affected environment
- Researcher should track the incident as a data point for reliability analysis
- Post-incident, Workitems should create a retro task in Asana

Add an EventBridge rule that subscribes to DevOps Agent incident events and notifies the Dispatch Router.

### 9. Cross-Repository Intelligence

Most bots operate within a single repo. Your agents should work across repos:

- Researcher analyzes backlog across the frontend and backend repos together
- Uat runs E2E tests that span both repos (deploy frontend + backend to staging, test together)
- Docwriter maintains docs that reference both repos' APIs
- Workitems tracks project status across all repos in the project

This requires the Gateway GitHub target to have access to multiple repos, and the agents' memory to maintain a cross-repo project map.

### 10. Proactive vs. Reactive

Every bot pattern above is reactive: something happens, bot responds. Agents can be *proactive*:

**Researcher proactive behaviors:**
- Monitors app store review feeds and flags emerging complaints *before* they become support tickets
- Detects competitor feature launches and immediately assesses impact on the roadmap
- Identifies seasonal patterns: "Last year during the Q4 launch window, traffic spiked 300% — should we pre-scale?"

**Workitems proactive behaviors:**
- Predicts sprint completion likelihood based on velocity trends and current burn rate
- Detects developer workload imbalances before they become blockers
- Identifies PRs that have been open too long and are accumulating merge conflicts

**Uat proactive behaviors:**
- Monitors production error rates and auto-generates regression tests for new error patterns
- Detects UI drift between Figma designs and deployed app (scheduled visual comparison)
- Identifies test coverage gaps by analyzing code changes that have no corresponding tests

### 11. Agent Self-Improvement

The most advanced pattern: agents that improve their own performance.

- Uat tracks which generated tests get modified by humans after merge. The modifications become training signal: "my selector strategy was wrong here, update memory."
- Docwriter tracks which doc PRs get edited by humans. The edits reveal style guide gaps.
- Researcher tracks which user stories get modified during sprint. The modifications reveal spec quality issues.
- Workitems tracks which status reports get corrected. The corrections reveal data quality issues.

Add a **feedback loop** to each agent:
```python
@tool
def learn_from_human_edit(
    original_pr: int,
    human_edit_pr: int
) -> str:
    """Compare an agent-generated PR with a human's subsequent edits.
    
    Extracts patterns from the diff and updates memory to improve
    future output quality.
    """
```

---

## Part 3: Updated Recommendations Summary

### Add to existing agents (no new agents needed):

| Pattern | Agent | New Mode/Feature |
|---------|-------|-----------------|
| Issue triage (classify, deduplicate, assign) | Workitems | TRIAGE mode |
| Release coordination | Workitems | RELEASE mode |
| Deployment orchestration | Workitems | DEPLOY mode |
| Slash commands (/deploy, /approve, /lock) | Dispatch | Command parser |
| Kill switch (/disable, /enable) | Dispatch | Agent control |
| Approval gates (human-in-the-loop) | All agents | request_approval tool |
| Dependabot triage | @claude + Uat | Event-driven dispatch |
| PR quality gate | GitHub Actions | Rule-based (no agent) |
| Incident awareness | All agents | EventBridge subscription |
| Cross-repo intelligence | All agents | Multi-repo Gateway config |
| Proactive behaviors | All agents | Scheduled analysis runs |
| Self-improvement feedback loop | All agents | learn_from_human_edit tool |
| Intelligent PR routing | Dispatch | PR event handler |

### New stories to add to the implementation plan:

**Phase 1 additions (Dispatch):**
- 1.9: Implement slash command parser (/deploy, /approve, /reject, /lock, /unlock, /status, /budget, /disable, /enable)
- 1.10: Implement approval gate tool (request_approval with timeout)
- 1.11: Implement kill switch (DynamoDB agent_status flag, checked on every dispatch)

**Phase 2 additions (Workitems):**
- 2.11: Implement TRIAGE mode for new issues (classify, deduplicate, assign, label)
- 2.12: Implement RELEASE mode (readiness check, version bump, tag, deploy coordination, announcement)
- 2.13: Implement DEPLOY mode (staging verification, production gate, rollback support)
- 2.14: Subscribe to AWS DevOps Agent incident events via EventBridge

**Phase 3 additions (Uat):**
- 3.15: Implement Dependabot PR auto-testing (full suite on major bumps, smoke on patches)
- 3.16: Implement proactive production error → test generation pipeline

**Phase 6 additions (Fleet Ops):**
- 6.11: Implement PR quality gate (rule-based, pre-agent)
- 6.12: Implement intelligent PR routing in Dispatch
- 6.13: Implement self-improvement feedback loop (learn_from_human_edit) across all agents
- 6.14: Configure cross-repo Gateway access and multi-repo memory

**Revised story count: 72 → 86 stories**

---

## Part 4: What NOT to Automate

Not every bot pattern should become an agent. Keep these as simple rules:

- **Conventional commit enforcement**: a regex check, not an LLM call
- **PR size warnings**: a line count, not a reasoning task  
- **Branch protection**: GitHub's native feature, not an agent
- **CI status checks**: GitHub Actions, not an agent
- **Auto-merge for Dependabot patches**: Mergify or native auto-merge with conditions

The principle: **use agents for judgment, use rules for compliance.** If the decision can be made with a regex or a threshold, don't burn tokens on it.
