# PRFAQ: Autonomous PDLC Agent Fleet
## Press Release / Frequently Asked Questions

> **Status:** This PRFAQ describes the v1 fleet as it ships today — four autonomous agents on Amazon Bedrock AgentCore Runtime. Earlier drafts of this document covered additional agents (UAT testing, feedback learning) and AgentCore services (Identity, Gateway, Memory, Browser) that remain on the roadmap but are not implemented yet. See [`docs/roadmap.md`](roadmap.md) for what's planned next.

---

# PRESS RELEASE

## Small Software Teams Ship Faster with an Autonomous Agent Fleet on AWS

*Four purpose-built AI agents handle project management, documentation, business analysis, and architecture-decision alignment — freeing a small team to focus on the work only humans can do.*

The PDLC Agent Fleet is an open-source set of autonomous AI agents built on **Amazon Bedrock AgentCore Runtime**. The fleet consists of four agents — **Workitems** (project management), **Researcher** (business analysis), **Docwriter** (technical writing), and **Adr** (architecture-decision linking) — coordinated by a cross-platform routing system called **Dispatch**. The agents work autonomously across GitHub and Asana, triggered by `@mentions`, task assignments, and scheduled events.

Key capabilities today:

- **Workitems** decomposes a feature ask in Asana into a proposed plan, posts it as an Asana comment, and — on human approval — creates the corresponding GitHub issues with acceptance criteria. It also generates status reports and flags risks.
- **Researcher** synthesizes qualitative research, runs competitive scans against a tracked list of companies, drafts user stories, and reviews existing specs for completeness.
- **Docwriter** generates API reference docs and release notes, reviews doc PRs, and opens doc PRs when merged code changes affect documentation.
- **Adr** tags GitHub issues with the ADRs that govern them and reviews PRs against the linked decisions, keeping architectural intent connected to the work that implements it.

Humans interact with agents by `@mention` in the tool they already use. A GitHub issue comment reading `@docwriter update the API reference` triggers Docwriter. Assigning an Asana task to the Workitems bot triggers work decomposition. The **Dispatch Router** Lambda handles cross-platform translation, authorization, and concurrency control, then invokes the appropriate AgentCore Runtime.

Every agent runs under **Cedar policy guardrails** that prevent destructive actions. No agent can merge PRs, close issues, or delete tasks. Agents comment, create, and recommend; humans approve.

The fleet is built with the **Strands Agents SDK** and deployed via a GitHub Actions CI/CD pipeline: each agent has its own container image in Amazon ECR, scanned by Amazon Inspector on build, and deployed to AgentCore Runtime via a shared reusable workflow.

To learn more, see the [README](../README.md) or the [design doc](03-design-agent-fleet.md).

---

# FREQUENTLY ASKED QUESTIONS

## Customer FAQ

**Q: What problem does this solve?**

Small development teams are bottlenecked by "work about work" — the project management, documentation, and analysis tasks that surround the actual coding. A team of 2–5 developers spends significant time syncing GitHub and Asana, writing status reports, maintaining docs, and reviewing specs for completeness. The agent fleet automates these tasks so humans focus on the work that requires creativity, judgment, and domain expertise.

**Q: Why not just use one general-purpose AI assistant for everything?**

Specialized agents outperform generalists because their system prompts, tool sets, and guardrails are each tuned for a single role. Workitems enforces an approval pattern (propose → human-approve → create); Researcher cites every claim; Docwriter opens doc PRs that never touch code; Adr is read-only toward ADRs. Those behaviors come from specialization — a generalist would need those constraints stated in every prompt.

**Q: What happens if an agent makes a mistake?**

Every agent operates under **Cedar policy guardrails** that prevent destructive actions. No agent can merge PRs, close issues, delete tasks, or deploy to production. They create, comment, and recommend — humans approve. The fleet is designed to be safe to run autonomously from day one; the worst case for any agent is a bad comment or an unhelpful draft, both easily ignored or reverted by a human.

**Q: How do I interact with the agents?**

The same way you'd tag a teammate. Type `@docwriter draft release notes for this PR` in a GitHub PR comment, or assign an Asana task to the Workitems bot. The Dispatch Router handles the routing — you don't need to know which AgentCore runtime the agent lives on or how it's configured.

**Q: What does it cost to operate?**

Consumption-based pricing. Primary cost drivers are **Bedrock model invocations** (all agents run on Claude Opus 4.7 today), **AgentCore Runtime compute** (billed per-second during agent runs), and **Lambda + API Gateway** for the Dispatch Router and Asana webhook. Token budgets per agent per day are defined in `.dispatch/agents.yaml` to cap runaway spend.

**Q: Can I add new agents?**

Yes. Adding a new agent requires writing a Strands agent (system prompt + tools), adding a Dockerfile, creating a `deploy-<name>.yml` wrapper of the shared deploy workflow, and adding an entry to `.dispatch/agents.yaml`. The new agent is then reachable via `@mention` through Dispatch.

**Q: What kind of teams is this suited for?**

Teams that plan in **Asana** and ship on **GitHub**. Jira and GitLab are on the roadmap but not yet supported. The fleet is most valuable when a team ships regularly and struggles to keep documentation, specs, and project visibility current alongside development.

## Internal FAQ

**Q: Why AgentCore Runtime instead of Lambda or ECS?**

AgentCore Runtime provides session isolation (microVM per invocation), long execution windows (hours rather than Lambda's 15 minutes), and a clean container-based deployment model. ECS would require managing orchestration, scaling, and secrets plumbing that AgentCore provides out of the box.

**Q: Why Strands Agents instead of LangGraph or CrewAI?**

Strands is AWS-native and integrates cleanly with AgentCore Runtime. `BedrockAgentCoreApp` wraps a Strands agent for deployment with minimal glue code. Strands has first-class MCP support, which matters because the fleet's tool surface is primarily MCP servers (GitHub's official remote MCP at `api.githubcopilot.com/mcp`, Asana's at `mcp.asana.com/v2/mcp`).

**Q: Why not AgentCore Gateway, Identity, or Memory?**

These were in the original design but the v1 fleet takes a simpler path:

- **Credentials**: stored in SSM Parameter Store (SecureString). Each agent's runtime role has narrow `ssm:GetParameter` access to the paths it needs. This works today with no Identity directory setup.
- **MCP endpoints**: agents connect directly to the vendor MCP servers via `streamablehttp_client`, not through a Gateway proxy. One fewer hop to debug, and the OAuth dance is handled per-tenant by `scripts/bootstrap_asana_oauth.py`.
- **Memory**: the agents honor an `AGENTCORE_MEMORY_ID` environment variable (the Strands `AgentCoreMemoryToolProvider` is wired up) but no Memory resource is provisioned by the fleet's infra template. Teams that want memory today provision their own Memory resource and pass the ID to the runtime; a shipped-out-of-the-box memory layer is a roadmap item.

The simpler path ships today. Gateway/Identity/Memory are natural upgrades when the operational story for them solidifies.

**Q: What's the blast radius if an agent goes rogue?**

Bounded by design. Cedar policies forbid destructive operations (merge, close, delete) for every agent. The Dispatch Router has per-agent concurrency caps and daily token budgets defined in `.dispatch/agents.yaml`. All agent actions are logged to CloudWatch via the OpenTelemetry distribution baked into each agent container. The worst case is a bad comment or an unhelpful draft PR, both easily reverted.

**Q: Can this work with Jira instead of Asana?**

Not yet. The architecture is agnostic (agents talk to tools via MCP servers), but the Asana-specific pieces — the webhook Lambda, the Asana MCP OAuth bootstrap, the agents' tool wiring — would need Jira equivalents. Atlassian has an official remote MCP server, so the agent-side work is lighter than the webhook/dispatch side. See the roadmap.

**Q: Can this work with GitLab instead of GitHub?**

Same answer as Jira. The dispatch layer currently speaks GitHub Actions + GitHub webhooks. A GitLab adapter would need a webhook receiver, a GitLab MCP connection, and agent-prompt updates (merge request vs. pull request, pipelines vs. actions). On the roadmap.
