# Workitems agent: PO/PM Autonomous Agent
## Architecture & Implementation Plan on Amazon Bedrock AgentCore

> **Status: target design.** The shipping agent under `agents/workitems/` implements work decomposition with the approval pattern, status reports, risk detection, and Asana↔GitHub sync. It uses **direct MCP connections** (not AgentCore Gateway) and **SSM Parameter Store** for credentials (not AgentCore Identity). Features in this spec that depend on **AgentCore Memory** (shared project context) are not wired up unless a Memory resource is provisioned out-of-band. For current behavior, read `agents/workitems/prompts.py` and the code under `agents/workitems/tools/`.

---

## 1. What This Agent Does

Workitems agent is an autonomous agent that bridges GitHub (where development happens) and Asana (where project tracking happens), performing the work that currently falls through the cracks between your developer workflow and your project management workflow.

**Core Capabilities:**
- **Work decomposition with approval**: Assigned an Asana task, Workitems reads the plan and context, reasons about how to break it into GitHub issues, proposes the plan as an Asana comment, and waits for human approval before creating issues
- **Prioritization & assignment**: Applies RICE scoring using backlog context, team velocity, and stated goals; recommends priority order and assigns to developers or @claude
- **Bi-directional sync**: GitHub issues/PRs ↔ Asana tasks, kept in lockstep
- **Status intelligence**: Automated sprint/project status reports synthesized from both systems
- **Risk detection**: Flags stale issues, blocked PRs, slipping milestones, and resource bottlenecks
- **Stakeholder updates**: Drafts weekly summaries tailored to audience (team vs. leadership)

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    AgentCore Runtime                         │
│  ┌───────────────────────────────────────────────────────┐  │
│  │              Strands Agent (Python)                    │  │
│  │  ┌─────────┐  ┌──────────┐  ┌─────────────────────┐  │  │
│  │  │ Planner │  │ Reporter │  │ Sync Reconciler     │  │  │
│  │  └────┬────┘  └────┬─────┘  └──────────┬──────────┘  │  │
│  │       └─────────────┼───────────────────┘             │  │
│  │                     │                                 │  │
│  │              ┌──────┴──────┐                          │  │
│  │              │  Tool Layer │                          │  │
│  │              └──────┬──────┘                          │  │
│  └─────────────────────┼─────────────────────────────────┘  │
│                        │                                    │
│  ┌─────────────────────┼─────────────────────────────────┐  │
│  │           AgentCore Gateway (MCP)                      │  │
│  │     ┌───────────────┼───────────────┐                 │  │
│  │     │               │               │                 │  │
│  │  ┌──┴──┐      ┌─────┴────┐   ┌─────┴─────┐          │  │
│  │  │GitHub│      │  Asana   │   │  Slack     │          │  │
│  │  │Target│      │  Target  │   │  Target    │          │  │
│  │  └──┬──┘      └─────┬────┘   └─────┬─────┘          │  │
│  └─────┼───────────────┼──────────────┼──────────────────┘  │
│        │               │              │                     │
│  ┌─────┴───────────────┴──────────────┴──────────────────┐  │
│  │              AgentCore Identity                        │  │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐            │  │
│  │  │GitHub    │  │Asana     │  │Slack     │            │  │
│  │  │OAuth2    │  │OAuth2    │  │OAuth2    │            │  │
│  │  │Provider  │  │Provider  │  │Provider  │            │  │
│  │  └──────────┘  └──────────┘  └──────────┘            │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌────────────────┐  ┌──────────────┐  ┌────────────────┐  │
│  │ AgentCore      │  │ AgentCore    │  │ AgentCore      │  │
│  │ Memory         │  │ Policy       │  │ Observability  │  │
│  │ (project state)│  │ (Cedar rules)│  │ (CloudWatch)   │  │
│  └────────────────┘  └──────────────┘  └────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. AgentCore Services Breakdown

### 3a. AgentCore Identity — Credential Management

Two credential providers, both using built-in OAuth2 vendor integrations:

**GitHub OAuth2 Provider**
```json
{
  "name": "ProjectPulseGitHub",
  "credentialProviderVendor": "GithubOauth2",
  "oauth2ProviderConfigInput": {
    "GithubOauth2ProviderConfigInput": {
      "clientId": "<github-oauth-app-client-id>",
      "clientSecret": "<github-oauth-app-client-secret>"
    }
  }
}
```

Scopes needed: `repo`, `read:org`, `read:project`

**Asana OAuth2 Provider**
Asana is available as a 1-click Gateway integration, but for deeper control, configure as a custom OAuth2 provider:
```json
{
  "name": "ProjectPulseAsana",
  "credentialProviderVendor": "CustomOauth2",
  "oauth2ProviderConfigInput": {
    "CustomOauth2ProviderConfigInput": {
      "clientId": "<asana-app-client-id>",
      "clientSecret": "<asana-app-client-secret>",
      "authorizationEndpoint": "https://app.asana.com/-/oauth_authorize",
      "tokenEndpoint": "https://app.asana.com/-/oauth_token",
      "scopes": ["default"]
    }
  }
}
```

**Authentication Flow**: 2-legged OAuth (client credentials / machine-to-machine) for the agent acting autonomously. The agent authenticates as itself with pre-authorized consent, not impersonating a user. All actions carry the agent's workload identity for audit.

### 3b. AgentCore Gateway — Unified Tool Access

Single MCP endpoint that exposes both GitHub and Asana as tool targets.

**GitHub Target** (via MCP server connection or OpenAPI spec):
- `github_list_issues` — list/filter issues by label, assignee, milestone
- `github_get_issue` — full issue detail with comments
- `github_list_prs` — PRs with status, reviewers, checks
- `github_get_pr` — PR detail with diff stats, review status
- `github_list_milestones` — milestone progress
- `github_create_issue` — create issues from Asana tasks
- `github_add_comment` — post status updates on issues
- `github_add_label` — tag issues for triage

**Asana Target** (1-click integration or custom):
- `asana_list_tasks` — tasks by project/section/assignee
- `asana_get_task` — full task detail with subtasks, custom fields
- `asana_create_task` — create tasks from GitHub issues
- `asana_update_task` — update status, dates, assignee
- `asana_list_projects` — project-level overview
- `asana_get_project_status` — latest status update
- `asana_create_project_status` — post status updates
- `asana_search` — find tasks by keyword

**Slack Target** (optional, for notifications):
- `slack_post_message` — post to channels
- `slack_post_thread` — reply in threads

### 3c. AgentCore Memory — Persistent Project State

Memory strategies for the agent to maintain context across invocations:

**Semantic Memory**: Stores project knowledge — team member roles, sprint goals, recurring patterns, historical velocity data. The agent remembers "last sprint we shipped 34 points" without re-querying.

**Session Summarization**: Each agent run is summarized and stored. Next invocation gets the compressed history of what happened before.

**User Preference Memory**: Stores stakeholder preferences — "the CTO wants bullet points, the PM wants detail, the team wants just blockers."

```python
from bedrock_agentcore.memory import MemoryClient

client = MemoryClient(region_name="us-west-2")
memory = client.create_memory_and_wait(
    name="ProjectPulseMemory",
    description="Project state, team context, and reporting preferences",
    strategies=[
        {"semanticMemoryStrategy": {
            "name": "ProjectKnowledge",
            "namespaceTemplates": ["/project/{project_id}"]
        }},
        {"summaryMemoryStrategy": {
            "name": "RunSummaries",
            "namespaceTemplates": ["/runs/{date}"]
        }},
        {"userPreferenceMemoryStrategy": {
            "name": "StakeholderPrefs",
            "namespaceTemplates": ["/stakeholders/{name}"]
        }}
    ]
)
```

### 3d. AgentCore Policy — Guardrails via Cedar

The agent has write access to both systems. Cedar policies prevent it from doing damage:

```cedar
// Agent can create issues but not close them
permit(
    principal == AgentCore::Agent::"ProjectPulse",
    action == AgentCore::Action::"InvokeTool",
    resource
) when {
    resource.toolName == "github_create_issue" ||
    resource.toolName == "github_add_comment" ||
    resource.toolName == "github_add_label" ||
    resource.toolName == "asana_create_task" ||
    resource.toolName == "asana_update_task" ||
    resource.toolName == "asana_create_project_status" ||
    resource.toolName == "slack_post_message"
};

// Block destructive operations
forbid(
    principal == AgentCore::Agent::"ProjectPulse",
    action == AgentCore::Action::"InvokeTool",
    resource
) when {
    resource.toolName == "github_delete_issue" ||
    resource.toolName == "github_close_issue" ||
    resource.toolName == "github_merge_pr" ||
    resource.toolName == "asana_delete_task" ||
    resource.toolName == "asana_delete_project"
};
```

### 3e. AgentCore Evaluations — Quality Monitoring

Set up continuous evaluation to ensure the agent's outputs stay useful:

**Built-in evaluators**:
- Correctness: are status reports factually accurate vs. source data?
- Helpfulness: do generated reports answer the questions stakeholders care about?
- Tool selection accuracy: is the agent using the right tools efficiently?
- Safety: no sensitive data leaking into Slack messages

**Custom evaluator** (Lambda):
- "Sync accuracy": after a sync run, sample 10 items and verify GitHub↔Asana state matches
- "Report freshness": verify status reports reference data from the current sprint, not stale

### 3f. AgentCore Observability — CloudWatch Integration

Dashboards tracking:
- Token usage per run (cost control)
- Tool invocation counts (GitHub vs. Asana API call balance)
- Latency per tool call
- Error rates by tool target
- Session duration
- Evaluation scores over time

Alarms:
- OAuth token refresh failures (GitHub or Asana)
- Agent run exceeding 30 minutes (normally runs in < 5)
- Error rate > 5% on any tool target
- Evaluation score drops below threshold

---

## 4. Agent Implementation (Strands SDK)

### 4a. Work Decomposition Flow (Primary Mode)

This is Workitems's most important capability. The flow mirrors the approval pattern
used by Claude Code in GitHub (where a user comments "claude-approved"):

```
┌──────────────────────────────────────────────────────────┐
│  1. User assigns Workitems to an Asana task                  │
│     (via @workitems comment, bot assignment, or custom field)│
└──────────────────────┬───────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────┐
│  2. Workitems reads:                                         │
│     - The assigned Asana task (goal, AC, context)        │
│     - The Asana project (current plan, milestones)       │
│     - GitHub repo (existing issues, open PRs, activity)  │
└──────────────────────┬───────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────┐
│  3. Workitems reasons about decomposition:                   │
│     - Breaks work into concrete, assignable issues       │
│     - Each issue: 1–3 days of work, clear AC, labeled    │
│     - Maps dependencies between issues                   │
│     - Suggests priority order and assignments            │
└──────────────────────┬───────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────┐
│  4. Workitems posts proposed plan as Asana comment:          │
│                                                          │
│     @Workitems Proposed Plan:                                │
│     I propose breaking this into 4 GitHub issues:        │
│     1. [Title] — AC: ... Labels: ... Estimate: S        │
│     2. [Title] — AC: ... Labels: ... Estimate: M        │
│     ...                                                  │
│     Dependencies: #1 blocks #3.                          │
│     Reply "approved" to create, or provide feedback.     │
└──────────────────────┬───────────────────────────────────┘
                       │
              ┌────────┴────────┐
              ▼                 ▼
┌─────────────────┐  ┌─────────────────────────────────────┐
│ User: "approved" │  │ User: "Split #2 into FE and BE"     │
└────────┬────────┘  └──────────────────┬──────────────────┘
         │                              │
         ▼                              ▼
┌─────────────────┐  ┌─────────────────────────────────────┐
│ 5a. Workitems       │  │ 5b. Workitems revises plan, re-proposes │
│ creates GitHub   │  │     (back to step 4)                │
│ issues, links    │  └─────────────────────────────────────┘
│ to Asana task,   │
│ confirms in      │
│ comment          │
└─────────────────┘
```

**Key design decision**: Workitems has no `work_decomposition` tool. Work
decomposition is *reasoning*, not a tool call. Workitems uses its standard Gateway
MCP tools (asana_get_task, github_list_issues, etc.) to gather context, then
reasons about the breakdown. The tools it calls are reads (to gather context)
and writes (to post the comment and, on approval, create issues).

### 4b. Agent Structure

See `agents/workitems/agent.py` for the full implementation. Key points:

```python
from strands import Agent
from strands.models import BedrockModel
from strands.tools.mcp import MCPClient
from mcp.client.streamable_http import streamablehttp_client
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands_tools.agent_core_memory import AgentCoreMemoryToolProvider

app = BedrockAgentCoreApp()

@app.entrypoint
def invoke(payload, context):
    """Main entry point. Receives instruction from Dispatch or schedule."""
    user_input = payload.get("prompt", payload.get("user_input", ""))

    # Gateway MCP — all GitHub, Asana, Slack tools via single endpoint
    gateway_client = MCPClient(
        lambda: streamablehttp_client(GATEWAY_URL, headers={...})
    )

    # Memory — project context persisted across invocations
    memory_provider = AgentCoreMemoryToolProvider(
        memory_id=MEMORY_ID, actor_id="workitems", ...
    )

    model = BedrockModel(model_id="us.anthropic.claude-sonnet-4-6-v1")

    with gateway_client:
        agent = Agent(
            model=model,
            system_prompt=SYSTEM_PROMPT,
            tools=[
                *gateway_client.list_tools_sync(),
                *memory_provider.tools,
                generate_status_report,
                detect_risks,
                reconcile_sync,
                post_results,
            ],
        )
        return {"result": str(agent(user_input))}
```

### 4c. Custom Tools (structured task prompts)

Custom tools are *not* where reasoning happens — they structure the agent's
multi-step workflows by returning instructions for how to use the Gateway
MCP tools. The agent's LLM does the actual reasoning and orchestration.

- `generate_status_report(project_name, audience, format)` — guides the agent
  through querying both systems and synthesizing a report tailored to audience
- `detect_risks(project_name)` — guides the agent through checking specific
  risk signals (stale issues, blocked PRs, overdue tasks, slipping milestones)
- `reconcile_sync(project_name, dry_run)` — guides the agent through matching
  GitHub issues ↔ Asana tasks and detecting/fixing state drift
- `post_results(platform, target_id, message)` — routes results back to the
  originating platform (Asana comment, GitHub comment, or Slack message)

See `agents/workitems/tools/` for implementations.

### 4d. System Prompt

The system prompt defines four operating modes: PLAN, REPORT, TRIAGE, SYNC.

The PLAN mode is the most important — it enforces the approval gate:
- Propose plan as Asana comment, structured with titles, AC, labels, estimates
- Wait for "approved" reply before creating any GitHub issues
- On feedback, revise and re-propose
- On approval, create issues and confirm with links

See `agents/workitems/prompts.py` for the full prompt.

---

## 5. Invocation Patterns

The agent runs in four modes, triggered by different mechanisms:

### 5a. Asana Assignment → PLAN mode (primary)

The most important trigger. When a user wants Workitems to break work into GitHub
issues, they assign Workitems to an Asana task using any of these methods:

```
Asana comment: "@workitems break this into issues"  →  PLAN mode
Asana assignment: assign task to workitems-bot       →  PLAN mode
Asana custom field: set Agent = Workitems            →  PLAN mode
```

All three fire Asana webhooks → Dispatch Router → Workitems. The agent enters
PLAN mode: reads context, reasons about decomposition, proposes plan as an
Asana comment, and waits for approval.

**Approval flow:**
```
User replies "approved" (case-insensitive)  →  Workitems creates GitHub issues
User replies with feedback                  →  Workitems revises and re-proposes
```

The approval reply triggers a new Asana webhook → Dispatch → Workitems invocation.
Workitems reads the conversation thread to determine whether it's an approval or
feedback, and acts accordingly.

### 5b. Scheduled (EventBridge → AgentCore Runtime)

```
EventBridge Rule: cron(0 8 ? * MON-FRI *)  →  "Run morning triage"   (TRIAGE)
EventBridge Rule: cron(0 17 ? * FRI *)      →  "Generate weekly report" (REPORT)
EventBridge Rule: cron(0 */4 ? * MON-FRI *) →  "Reconcile sync"        (SYNC)
```

### 5c. Event-Driven (GitHub Webhooks → Dispatch → AgentCore Runtime)

```
GitHub comment: "@workitems status"    →  REPORT mode
GitHub webhook (PR merged)         →  Agent updates linked Asana task status
GitHub webhook (PR review needed)  →  Agent posts reminder in Slack
```

### 5d. On-Demand (Slack command)

```
/workitems status          →  "Generate status report for current sprint"
/workitems risks           →  "Run risk detection scan"
/workitems sync --dry-run  →  "Show sync plan without executing"
```

---

## 6. Data Flow: GitHub ↔ Asana Mapping

```
GitHub                          Asana
──────                          ─────
Repository           →          Project
Milestone            →          Section (or Project milestone)
Issue                ↔          Task
  - title            ↔            - name
  - body             ↔            - notes (markdown)
  - assignee         ↔            - assignee  
  - labels           ↔            - tags / custom fields
  - milestone        ↔            - section
  - state (open)     ↔            - incomplete
  - state (closed)   ↔            - complete
PR (linked to issue) →          Task custom field: PR URL + status
Issue comment         →          Task comment (selective, tagged)
```

**Sync rules:**
- GitHub is source of truth for development items (issues, PRs)
- Asana is source of truth for project structure (timelines, dependencies, ownership)
- Agent creates linkage via custom fields and labels
- Conflicts: agent flags for human resolution, does not auto-resolve

---

## 7. Implementation Phases

### Phase 1: Foundation (Weeks 1–2)
- Set up AgentCore Identity with GitHub and Asana OAuth providers
- Configure AgentCore Gateway with both targets
- Deploy minimal Strands agent to AgentCore Runtime
- Verify read-only access to both systems
- Set up Observability dashboards

### Phase 2: Read & Report (Weeks 3–4)
- Implement status report generation (query both systems, synthesize)
- Implement risk detection
- Add AgentCore Memory for project context persistence
- Set up EventBridge scheduled invocations
- Deploy Cedar policies (read-heavy, limited writes)

### Phase 3: Sync & Write (Weeks 5–6)
- Implement GitHub↔Asana sync reconciliation
- Enable write operations with dry-run-first pattern
- Add GitHub webhook handlers for event-driven sync
- Expand Cedar policies for write operations
- Set up AgentCore Evaluations for sync accuracy

### Phase 4: Stakeholder Layer (Weeks 7–8)
- Add Slack integration via Gateway
- Implement `/workitems` Slack commands
- Add audience-aware reporting (team vs. leadership format)
- Memory: store stakeholder preferences
- Polish: prompt tuning, eval score optimization

### Phase 5: Production Hardening (Weeks 9–10)
- Load testing and latency optimization
- OAuth token refresh failure handling
- Graceful degradation (if GitHub API is down, still report from Asana)
- Cost analysis and prompt caching optimization
- Runbook for operational issues
- Register agent in AgentCore Agent Registry

---

## 8. Cost Considerations

| Component | Driver | Estimate |
|-----------|--------|----------|
| AgentCore Runtime | Per-second compute during agent runs | Low — runs are short (< 5 min) |
| Bedrock (Claude Opus 4.7) | Input/output tokens per run | ~$0.50–2.00/run depending on scope |
| AgentCore Memory | Storage + retrieval calls | Minimal at project scale |
| AgentCore Gateway | Per-tool-call | Pennies per invocation |
| GitHub API | Rate limited, free for authenticated apps | No cost |
| Asana API | Rate limited, included in Asana plan | No cost |
| CloudWatch | Logs, metrics, dashboards | ~$5–10/month |
| EventBridge | Scheduled rules | Negligible |

**Prompt caching** (via Strands CacheConfig) significantly reduces token costs on repeated system prompts and tool schemas. Expect 40–60% reduction in input tokens.

---

## 9. Security Model

- **Principle of least privilege**: Agent's GitHub OAuth app has only the scopes it needs. Asana access is scoped to specific projects.
- **No human impersonation**: Agent acts as its own workload identity. All actions in GitHub and Asana are attributable to "ProjectPulse bot."
- **Cedar policy enforcement**: Every tool call goes through Policy before execution. Destructive operations are explicitly forbidden.
- **Token vault**: OAuth tokens stored encrypted at rest (KMS) in AgentCore Identity. Never in code, never in environment variables.
- **Audit trail**: Every tool invocation logged via Observability. Full trace from "agent decided to create task" → "Gateway called Asana API" → "Asana returned 201."
- **VPC isolation**: AgentCore Runtime runs in a microVM with session isolation. No cross-session data leakage.

---

## 10. What This Enables for Each Role

| Role | Before | After |
|------|--------|-------|
| **Product Owner** | Manually checks GitHub + Asana, writes status reports | Reviews agent-drafted reports, focuses on decisions |
| **Project Manager** | Manually syncs systems, chases status updates | Monitors agent dashboards, handles exceptions only |
| **Developer** | Forgets to update Asana when closing issues | Sync is automatic, can focus on code |
| **Scrum Master** | Manually compiles sprint metrics | Metrics pre-compiled, focuses on facilitation |
| **Stakeholders** | Waits for Friday email, gets stale info | Gets real-time Slack updates on their schedule |
