# AI-Augmented SDLC: Toolchains & Claude Integration Map

> **Status: context, not spec.** This is a role-by-role survey of where Claude could fit in a typical software team's toolchain. It predates the shipping fleet and describes capabilities broader than what this project actually delivers today. Use it for thinking about expansion; do not mistake it for documentation of what runs. See [`roadmap.md`](roadmap.md) and [`03-design-agent-fleet.md`](03-design-agent-fleet.md) for what's live.

## Foundation Stack (Shared)
GitHub (repos, issues, actions) → AWS (infra) → Asana or Jira (project tracking)

---

## Claude Owns (Human Supervises)

### Dev/Tester (Unit & Automated Tests)
**Current Toolchain**
- Test frameworks: Jest, Vitest, pytest, Playwright (component)
- Coverage: Istanbul/nyc, coverage.py
- CI gating: GitHub Actions with coverage thresholds
- Mutation testing: Stryker, mutmut
- Mocking: MSW (API), Testcontainers (integration)

**Claude Integration Points**
- **GitHub Issues → @claude**: assign a "write tests for X" issue, Claude Code opens a PR with tests
- **PR trigger**: on every PR, Claude Code runs as a reviewer that checks for missing test coverage and opens follow-up issues
- **Coverage diff comments**: GitHub Action posts coverage delta on PRs; Claude auto-generates tests for uncovered paths
- **Key integration needed**: Claude Code ↔ coverage tooling (lcov/istanbul output parsing) so Claude can target specific uncovered functions

### Technical Writer / Docs
**Current Toolchain**
- Docs-as-code: Docusaurus, MkDocs, Mintlify, ReadMe
- API docs: OpenAPI/Swagger auto-gen, Redocly
- Diagrams: Mermaid, D2, PlantUML
- Versioning: docs live in repo, deployed via CI
- Style: Vale (linting for tone/consistency)

**Claude Integration Points**
- **PR hook**: on merged PRs that change public APIs, Claude drafts doc updates and opens a docs PR
- **Changelog automation**: Claude generates release notes from PR descriptions + commit messages
- **Onboarding guides**: Claude reads codebase + existing docs, identifies gaps, drafts missing guides
- **Key integration needed**: Claude Code ↔ OpenAPI spec diffing, so API doc updates are triggered by schema changes

### Release Manager
**Current Toolchain**
- Release orchestration: GitHub Releases, semantic-release, changesets
- Feature flags: LaunchDarkly, AWS AppConfig, Unleash
- Deployment: GitHub Actions → AWS CodeDeploy / ECS / Lambda
- Rollback: blue/green or canary via AWS, ArgoCD if K8s
- Status pages: Statuspage.io, Instatus

**Claude Integration Points**
- **Pre-release checklist**: Claude audits open PRs, pending migrations, flag states, and drafts a go/no-go summary
- **Release notes**: auto-generated from merged PRs, categorized by type (feature/fix/breaking)
- **Post-deploy monitoring**: Claude watches CloudWatch/Datadog for anomalies in the first hour, alerts Slack if metrics degrade
- **Key integration needed**: Claude ↔ feature flag API (read flag states, suggest flag cleanup for fully-rolled-out features)

---

## Shared Ownership (Claude Does Heavy Lifting)

### Developer
**Current Toolchain**
- Editor: VS Code / Cursor / JetBrains + Claude Code CLI
- Version control: Git + GitHub (PRs, branch protection)
- Language tooling: ESLint, Prettier, Ruff, TypeScript strict
- Local dev: Docker Compose, LocalStack (for AWS), Vite
- Debugging: Chrome DevTools, AWS X-Ray
- Architecture: ADRs in repo, C4 diagrams

**Claude Integration Points**
- **Issue → PR pipeline**: @claude on GitHub issues generates implementation PRs
- **Code review**: Claude Code as a required reviewer on all PRs — catches bugs, style issues, security smells
- **Architecture companion**: developer describes a design problem, Claude drafts an ADR with trade-offs
- **Refactoring**: Claude handles mechanical refactors (rename patterns, extract modules, migrate APIs) that humans avoid because they're tedious
- **Key integration needed**: Claude Code ↔ project context (access to ADRs, design docs, and related issues so its PRs reflect architectural intent, not just local code)

### DevOps / Infrastructure Engineer
**Current Toolchain**
- IaC: AWS CDK (TypeScript), Terraform, Pulumi
- CI/CD: GitHub Actions (build/test/deploy pipelines)
- Containers: Docker, ECR, ECS or EKS
- Monitoring: CloudWatch, Datadog, Grafana
- Secrets: AWS Secrets Manager, GitHub Secrets
- Cost: AWS Cost Explorer, Infracost

**Claude Integration Points**
- **IaC generation**: describe infra needs in an issue, Claude drafts CDK/Terraform and opens a PR
- **Pipeline debugging**: paste a failed GitHub Action log, Claude diagnoses and proposes a fix
- **Cost review**: Claude analyzes IaC changes and estimates cost impact before merge
- **Runbook generation**: Claude creates incident runbooks from architecture docs and monitoring configs
- **Key integration needed**: Claude ↔ AWS APIs (read-only) for live resource state; Claude ↔ Infracost for automated cost annotations on IaC PRs

### Security Engineer
**Current Toolchain**
- SAST: Semgrep, CodeQL (GitHub native), SonarQube
- Dependency scanning: Dependabot, Snyk, Trivy
- Secrets detection: GitLeaks, TruffleHog
- IAM analysis: AWS IAM Access Analyzer, Prowler
- Pen testing: Burp Suite, OWASP ZAP
- Compliance: AWS Config rules, Checkov

**Claude Integration Points**
- **PR security review**: Claude runs as a security-focused reviewer, checking for OWASP Top 10 patterns, overly permissive IAM, exposed secrets
- **Dependency triage**: when Dependabot opens a PR, Claude assesses actual exploitability in your codebase (not just CVE severity)
- **IAM policy review**: Claude reads IAM policies and flags least-privilege violations with suggested tightened versions
- **Threat model drafting**: Claude generates STRIDE threat models from architecture diagrams and API specs
- **Key integration needed**: Claude ↔ CodeQL/Semgrep results so it can prioritize findings and reduce alert fatigue

### Data Engineer
**Current Toolchain**
- Pipelines: AWS Glue, Step Functions, Airflow, dbt
- Storage: S3 (data lake), DynamoDB, RDS/Aurora, OpenSearch
- Streaming: Kinesis, EventBridge, SQS
- Media processing: MediaConvert, Rekognition, FFmpeg
- Data quality: Great Expectations, dbt tests
- Catalog: AWS Glue Data Catalog, DataHub

**Claude Integration Points**
- **Pipeline scaffolding**: describe a data flow, Claude generates Step Function definitions or Airflow DAGs
- **Query optimization**: paste a slow query, Claude rewrites it with explain plan analysis
- **Schema evolution**: Claude reviews migration scripts for backward compatibility
- **Media pipeline specific**: Claude helps build Rekognition or other ML integrations for entity identification in domain-specific content
- **Key integration needed**: Claude ↔ query plan output (Athena/RDS explain plans) for data-informed optimization suggestions

### Business Analyst
**Current Toolchain**
- Requirements: Confluence, Notion, Google Docs
- Diagramming: Miro, FigJam, Lucidchart
- Data analysis: Excel/Sheets, Looker, Metabase, QuickSight
- User stories: Jira/Asana (feeds into backlog)
- Surveys/feedback: Typeform, Productboard, Canny

**Claude Integration Points**
- **Research → requirements**: Claude processes interview transcripts, survey data, and support tickets into structured user stories with acceptance criteria
- **Competitive analysis**: Claude researches competitor features and maps them against your backlog
- **Impact sizing**: Claude pulls usage data from analytics tools and estimates feature impact
- **Spec review**: Claude reads a PRD and identifies ambiguities, missing edge cases, and untestable criteria before dev starts
- **Key integration needed**: Claude ↔ Productboard/Canny (customer feedback tools) so it can continuously synthesize incoming signals

### UAT Tester
**Current Toolchain**
- Browser automation: Playwright, Cypress, Selenium
- Visual regression: Percy, Chromatic, Playwright screenshots
- Test management: TestRail, Zephyr, or GitHub Issues with labels
- Accessibility: axe-core, Lighthouse
- Device testing: BrowserStack, LambdaTest

**Claude Integration Points**
- **Story → test script**: Claude reads a user story and generates Playwright E2E tests
- **Test maintenance**: when UI changes break tests, Claude updates selectors and flow logic
- **Visual regression triage**: Claude reviews Percy diffs and categorizes them (intentional change vs. regression)
- **Accessibility audit**: Claude runs axe-core results through analysis and generates fix recommendations with code
- **Key integration needed**: Claude ↔ Playwright test results + screenshot diffs for intelligent failure triage (not just "test failed" but "the submit button moved 20px left")

---

## Human-Primary (Claude Assists)

### Product Owner
**Current Toolchain**
- Roadmapping: Productboard, Aha!, Linear, Asana portfolios
- Analytics: Mixpanel, Amplitude, PostHog, AWS Pinpoint
- Feature flags: LaunchDarkly (for progressive rollouts)
- Communication: Slack, Loom (async demos)
- Prioritization: RICE/ICE scoring in spreadsheets or Productboard

**Claude Integration Points**
- **Decision packages**: Claude pulls analytics + backlog + customer feedback and presents "here are 3 prioritization options with trade-offs"
- **Stakeholder updates**: Claude drafts weekly product updates from sprint data, shipped features, and metric changes
- **PRD drafting**: PO outlines intent, Claude produces a structured PRD with edge cases, dependencies, and open questions
- **Experiment design**: Claude designs A/B test plans including sample size, metrics, and duration
- **Key integration needed**: Claude ↔ analytics platform (Mixpanel/PostHog) so it can pull real usage data into decision packages

### UX/UI Designer
**Current Toolchain**
- Design: Figma (primary), Sketch
- Prototyping: Figma prototyping, Framer
- Design system: Storybook, Figma component library
- Handoff: Figma Dev Mode, Zeplin
- User research: Maze, UserTesting, Hotjar

**Claude Integration Points**
- **Design → code**: designer produces a Figma comp, Claude generates the React component matching the design system
- **Accessibility**: Claude audits designs for WCAG compliance and suggests fixes
- **Copy writing**: Claude generates UI copy variations (button labels, error messages, empty states) that the designer picks from
- **Heuristic review**: Claude evaluates a flow against Nielsen's heuristics and flags usability concerns
- **Key integration needed**: Figma → Claude pipeline (Figma API or MCP connector) so Claude can read design specs directly instead of relying on screenshots

### Project Manager
**Current Toolchain**
- Tracking: Asana, Jira, Linear, GitHub Projects
- Time: Toggl, Harvest (if billing matters)
- Communication: Slack, Teams, email
- Reporting: Asana dashboards, Jira reports, custom Looker/Sheets
- Rituals: Zoom/Meet (standups, retros, planning)

**Claude Integration Points**
- **Status reports**: Claude pulls from GitHub (PRs merged, issues closed), Asana/Jira (sprint progress), and drafts the weekly update
- **Risk detection**: Claude flags issues that are stale, PRs that are blocked, and sprints that are trending behind
- **Meeting prep**: Claude generates standup summaries, retro data (cycle time, bug rate trends), and planning recommendations
- **Dependency mapping**: Claude reads issues and identifies cross-team dependencies the PM needs to manage
- **Key integration needed**: Claude ↔ Asana/Jira API (MCP) + GitHub API for unified project intelligence. This is the highest-leverage PM integration.

### AI Review / Prompt Engineer
**Current Toolchain**
- Prompt management: Anthropic Workbench, PromptLayer, Humanloop
- Eval: promptfoo, custom eval harnesses, Braintrust
- Observability: Langfuse, LangSmith, Helicone
- Version control: prompts stored in repo alongside code
- A/B testing: custom or via feature flags

**Claude Integration Points**
- **Self-evaluation**: Claude generates eval datasets and scores its own outputs against rubrics
- **Prompt iteration**: human defines the quality bar, Claude generates prompt variants and benchmarks them
- **Regression detection**: on code changes, Claude runs prompt evals and flags quality regressions
- **Cost optimization**: Claude suggests prompt compression or model routing (Haiku vs. Sonnet vs. Opus) based on task complexity
- **Key integration needed**: Claude ↔ eval framework (promptfoo or custom) with automated runs in CI — prompt quality becomes a merge gate

---

## Human-Only (Claude Assists After the Fact)

### Customer / Market Researcher
**Current Toolchain**
- Interviews: Zoom/Meet + Grain/Otter.ai (transcription)
- Surveys: Typeform, SurveyMonkey, Google Forms
- Analytics: Mixpanel, FullStory, Hotjar (session replay)
- Repository: Dovetail, EnjoyHQ, Notion
- Competitive: G2, Crunchbase, SimilarWeb

**Claude Integration Points**
- **Post-interview synthesis**: Claude processes transcripts and extracts themes, quotes, and actionable insights
- **Survey analysis**: Claude identifies patterns across open-ended survey responses
- **Competitive monitoring**: Claude periodically searches for competitor updates and summarizes changes
- **Insight → backlog**: Claude maps research findings to existing issues or drafts new ones
- **Key integration needed**: Claude ↔ Dovetail/research repository so insights flow directly into the product workflow

### Scrum Master / Agile Coach
**Current Toolchain**
- Facilitation: Miro, FigJam, Retrium
- Metrics: Jira/Linear velocity reports, cycle time dashboards
- Team health: Officevibe, TeamMood, retrospective tools
- Knowledge: Confluence, Notion (team agreements, working norms)

**Claude Integration Points**
- **Retro prep**: Claude analyzes sprint metrics and generates discussion prompts tailored to what actually happened
- **Pattern detection**: Claude identifies recurring retro themes across sprints ("deployment friction has come up 4 of the last 6 sprints")
- **Facilitation guides**: Claude drafts structured agendas for planning, retros, and workshops
- **Team health trends**: Claude summarizes sentiment data and flags concerning patterns
- **Key integration needed**: Claude ↔ retro tool (Retrium) + sprint metrics for longitudinal team health analysis

---

## Cross-Cutting Integration Priorities

**Highest leverage integrations to build first:**

1. **GitHub ↔ Claude Code (deep)** — already in place, but enrich with project context (ADRs, design docs, related issues)
2. **Asana/Jira ↔ Claude (MCP)** — unified project intelligence for PM, PO, and scrum master roles
3. **Claude ↔ Analytics (Mixpanel/PostHog)** — enables data-informed decision packages for PO
4. **Claude ↔ Figma (MCP/API)** — eliminates design-to-code handoff friction
5. **Claude ↔ AWS (read-only)** — live infra awareness for DevOps, cost review, and incident response
6. **Claude ↔ Slack (MCP)** — notification hub for all roles; Claude posts summaries, alerts, and drafts where the team already works
7. **Claude ↔ Eval/Observability** — prompt quality as a CI gate; critical as Claude's autonomous surface area grows

**The meta-pattern**: every integration that gives Claude *read access to context* makes its *write actions* dramatically better. The biggest gap in most AI-augmented workflows isn't Claude's capability — it's Claude operating without enough context about the project, the people, and the decisions already made.
