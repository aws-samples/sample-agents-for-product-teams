# Threat Model — PDLC Agent Fleet

**Version:** 1.7
**Date:** 2026-05-05
**Status:** Living document. Describes the fleet as it currently ships.
**Methodology:** Aligned with the [AWS Threat Designer](https://aws.amazon.com/blogs/machine-learning/accelerate-threat-modeling-with-generative-ai/) approach — identify assets, map data flows, enumerate threats (MITRE ATT&CK / OWASP), and document how each threat is mitigated today or why it is accepted.

---

## 1. System Overview

The PDLC Agent Fleet is a multi-agent system on Amazon Bedrock AgentCore Runtime. Users trigger agents via `@mention` in GitHub or Asana. A Dispatch Router Lambda resolves the mention, checks authorization, and invokes the appropriate agent container. Agents interact with external platforms (GitHub, Asana) through MCP servers using stored credentials.

### 1.1 Component Inventory

| ID | Component | Type | Description |
|----|-----------|------|-------------|
| C-1 | GitHub Actions (`agent-dispatch.yml`) | CI/CD Workflow | Extracts `@mention` from comments, assumes an OIDC-federated role, invokes Dispatch Router Lambda |
| C-2 | Asana Webhook Lambda | AWS Lambda + API Gateway | Public HTTPS endpoint; verifies HMAC signature; forwards events to Dispatch Router |
| C-3 | Dispatch Router Lambda | AWS Lambda | Resolves agent, checks auth/concurrency, records assignment, invokes AgentCore Runtime |
| C-4 | AgentCore Runtimes (×4) | Bedrock AgentCore | Containerized agents (workitems, researcher, docwriter, adr) running Strands SDK + Claude Opus 4.7 |
| C-5 | DynamoDB (`dispatch-assignments`) | Database | Assignment state tracking with TTL-based expiry |
| C-6 | SSM Parameter Store | Secrets/Config | Agent registry (String), OAuth tokens, PATs, webhook secret (SecureString) |
| C-7 | S3 Artifacts Bucket | Object Storage | Agent artifacts, screenshots, test results |
| C-8 | Cedar Policies | Policy Files | Per-agent allow/deny rules for tool invocations (advisory only — not enforced at runtime) |
| C-9 | GitHub MCP Server | External API | `api.githubcopilot.com/mcp/` — agents read/write GitHub via PAT |
| C-10 | Asana MCP Server | External API | `mcp.asana.com/v2/mcp` — agents read/write Asana via OAuth |
| C-11 | GitHub OIDC Provider | IAM Federation | Allows GitHub Actions to assume a scoped deploy role without stored credentials |
| C-12 | ECR Repositories | Container Registry | One per agent; `IMMUTABLE` tag policy; images built in CI, scanned by Amazon Inspector |

---

## 2. Data Flow Diagram

```
                    ┌──────────────────────────────────────────────────────┐
                    │              TRUST BOUNDARY: External Platforms       │
                    │                                                      │
                    │   GitHub (Issues, PRs, Comments)    Asana (Tasks)    │
                    └──────────┬──────────────────────────────┬────────────┘
                               │                              │
                    ┌──────────┼──────────────────────────────┼────────────┐
                    │          │  TRUST BOUNDARY: AWS Account  │            │
                    │          ▼                              ▼            │
                    │  ┌───────────────┐           ┌──────────────────┐   │
                    │  │ GitHub Actions │           │ API Gateway      │   │
                    │  │ OIDC → IAM    │           │ (public HTTPS)   │   │
                    │  └───────┬───────┘           └────────┬─────────┘   │
                    │          │ Lambda invoke               │             │
                    │          │                    ┌────────▼─────────┐   │
                    │          │                    │ Asana Webhook    │   │
                    │          │                    │ Lambda           │   │
                    │          │                    │ (HMAC verify)    │   │
                    │          │                    └────────┬─────────┘   │
                    │          │                             │ async invoke│
                    │          ▼                             ▼             │
                    │  ┌─────────────────────────────────────────────┐    │
                    │  │         Dispatch Router Lambda               │    │
                    │  │  • Parse mention  • Check auth (allowlist)  │    │
                    │  │  • Check concurrency  • Record in DynamoDB  │    │
                    │  └──────────────────────┬──────────────────────┘    │
                    │                         │ InvokeAgentRuntime        │
                    │          ┌──────────────┼──────────────┐            │
                    │          ▼              ▼              ▼            │
                    │  ┌────────────┐ ┌────────────┐ ┌────────────┐      │
                    │  │ workitems  │ │ researcher │ │ docwriter  │ ...  │
                    │  │ (AgentCore)│ │ (AgentCore)│ │ (AgentCore)│      │
                    │  └─────┬──────┘ └─────┬──────┘ └─────┬──────┘      │
                    │        │              │              │              │
                    │        │  SSM (creds) │              │              │
                    │        ▼              ▼              ▼              │
                    └────────┼──────────────┼──────────────┼──────────────┘
                             │              │              │
                    ┌────────┼──────────────┼──────────────┼──────────────┐
                    │        ▼  TRUST BOUNDARY: External MCP Servers      │
                    │  GitHub MCP          Asana MCP        Tavily Search │
                    └─────────────────────────────────────────────────────┘
```

### 2.1 Data Flows

| ID | From → To | Data | Protocol | Auth |
|----|-----------|------|----------|------|
| DF-1 | GitHub → GitHub Actions | Comment body, user login, issue metadata | HTTPS (GitHub webhook) | GitHub App event |
| DF-2 | GitHub Actions → Dispatch Router | Full comment + issue context as JSON payload | AWS Lambda invoke (OIDC → IAM) | STS AssumeRoleWithWebIdentity |
| DF-3 | Asana → API Gateway | Webhook event payload (story/task changes) | HTTPS POST | HMAC-SHA256 signature |
| DF-4 | Asana Webhook Lambda → Asana API | Task/story fetch requests | HTTPS | Bearer PAT from SSM |
| DF-5 | Asana Webhook Lambda → Dispatch Router | Normalized event payload | Lambda async invoke | IAM execution role |
| DF-6 | Dispatch Router → SSM | Registry fetch | AWS API | IAM execution role |
| DF-7 | Dispatch Router → DynamoDB | Assignment create/query | AWS API | IAM execution role |
| DF-8 | Dispatch Router → AgentCore Runtime | Instruction + context as JSON | `InvokeAgentRuntime` | IAM execution role (scoped to runtime/runtime-endpoint ARNs in this account+region) |
| DF-9 | Agent → SSM | Credential fetch (OAuth tokens, PATs) | AWS API | AgentCore runtime role |
| DF-10 | Agent → GitHub MCP | Issue/PR reads, comment writes | HTTPS | Bearer PAT |
| DF-11 | Agent → Asana MCP | Task reads, comment writes | HTTPS | OAuth2 access token |
| DF-12 | Agent → Bedrock | LLM inference (Claude Opus 4.7) | AWS API | AgentCore runtime role |
| DF-13 | CI/CD → ECR | Container image push (SHA-tagged, immutable) | HTTPS | OIDC → IAM |

---

## 3. Threat Catalog

Threats are categorized using [STRIDE](https://learn.microsoft.com/en-us/azure/security/develop/threat-modeling-tool-threats) and mapped to [MITRE ATT&CK](https://attack.mitre.org/) and [OWASP LLM Top 10](https://genai.owasp.org/llm-top-10/) where applicable. Each entry documents the current control posture: **Mitigated**, **Partially mitigated**, **Accepted** (acknowledged as a known limitation of this reference architecture), or **Open** (not yet addressed).

### 3.1 Prompt Injection (LLM-Specific)

| ID | Threat | Severity | Component | OWASP LLM | Status |
|----|--------|----------|-----------|-----------|--------|
| T-1 | **Indirect prompt injection via issue/task content** | **Critical** | C-4 | LLM01 | Partially mitigated |
| T-2 | **Direct prompt injection via @mention** | **High** | C-3, C-4 | LLM01 | Partially mitigated |
| T-3 | **Cross-agent prompt injection** | **High** | C-4 | LLM01 | Partially mitigated |

An attacker can craft a GitHub issue body, Asana task description, or the comment containing the `@mention` itself to insert instructions the agent reads as context. Injected instructions can override the system prompt; chained injection across agents (one agent creates a task that manipulates another) amplifies blast radius.

**Current controls (defense-in-depth, ordered edge → runtime → structure):**

1. **Edge filter at the Dispatch Router.** The body of every inbound `@mention` is scored by Amazon Bedrock Guardrails (`PROMPT_ATTACK` filter, `InputStrength: MEDIUM`) before the agent is invoked. A trip records the assignment as `blocked_guardrail`, posts a block-notice reply to the originating thread (no silent failures), emits a `GuardrailTripped` CloudWatch metric, and returns 400. This is the primary defense against T-2 and the first line against T-3. Attackers who probe the filter receive the same block-notice legitimate users do — there is no differentiated error path. `MEDIUM` is the shipping strength after `HIGH` was found to block benign user messages at high false-positive rate against the Dispatch Context wrapper; operators running against more hostile inputs can raise it in `infra/foundation/template.yaml`.

2. **Runtime guardrail on every agent's model invocation.** The same guardrail is attached to each agent's Bedrock `InvokeModel` call. Content the agent fetches from external platforms after dispatch (task notes, issue bodies, PR descriptions pulled via MCP) is scored server-side on the way into the model. This is the only layer that sees T-1 — an edge-only check cannot, because the attack arrives via a trusted-looking tool response, not via the mention comment. `OutputStrength` on this guardrail is `NONE` by design: agent outputs are bounded by structural controls (approval pattern, no destructive tools, per-agent IAM) rather than content filtering, and Cedar runtime enforcement (roadmap) is the intended structural layer.

3. **Model-level resistance.** Claude Opus 4.7 has built-in resistance to adversarial prompts. Treated as a baseline, not a boundary — probabilistic like any LLM defense.

4. **Structural controls on what a subverted agent can do.** Agents have no destructive tools (no close-issue, merge-PR, or delete-task primitives). Approval-pattern workflows require a human to accept proposed work before it lands. Per-agent IAM runtime roles grant only the specific SSM parameters and MCP endpoints each agent needs. A prompt-injected agent can still misuse a legitimate tool (e.g. post a misleading comment), but cannot escalate into actions the architecture doesn't expose.

5. **Authorization at the Router (T-4).** The per-agent `authorization.users` allowlist rejects any sender not explicitly permitted to invoke that agent. Cross-agent chains only propagate between agents the operator has paired, which bounds the blast radius of T-3 to the topology of the allowlists.

**Residual risk.** Bedrock Guardrails is probabilistic, not deterministic — a sufficiently novel prompt-attack pattern can slip past either evaluation point. Controls 3–5 bound what *happens* when it does: a subverted agent is restricted to the tools its IAM role and MCP servers allow, cannot invoke peers outside its allowlist, and cannot perform destructive actions. None of this prevents exfiltration via legitimate write channels (T-15) — Cedar runtime enforcement (T-5) is the roadmap item that would close that gap by intercepting individual tool calls. Operators deploying against untrusted input (public repos, external collaborators) should layer a classifier-based pre-filter in the Dispatch Router on top of Guardrails and revisit the Accepted findings before go-live.

**Detection.** `GuardrailTripped` fires on every block — the rate is the signal. A sustained rise above ~10 trips/hour triggers an alarm and warrants operator attention (either an active probing campaign or a false-positive spike worth re-tuning filter strength for). Guardrail-service outages fail closed and emit `GuardrailError`; any non-zero rate pages. All trip decisions are written to the assignments table with a 30-day TTL, providing an audit trail independent of CloudWatch log retention.

### 3.2 Authorization & Access Control

| ID | Threat | Severity | Component | STRIDE | Status |
|----|--------|----------|-----------|--------|--------|
| T-4 | **Agent registry authorization defaults** | — | C-3 | Elevation of Privilege | Mitigated |
| T-5 | **Cedar policies not enforced at runtime** | **High** | C-8 | Tampering | Accepted |
| T-6 | **Dispatch Router IAM scope** | — | C-3 | — | Mitigated |
| T-7 | **GitHub OIDC trust scope** | — | C-11 | — | Mitigated (guidance) |

**T-4 (Mitigated):** `.dispatch/agents.yaml` ships with `authorization.users: []` for every agent and the Dispatch Router fails closed — an empty allowlist returns 403 with a log line instructing the operator to populate the registry and re-run `scripts/sync_registry.py`. The wildcard `"*"` is still accepted for operators who explicitly opt into an open-by-default posture, but it is no longer the shipping default. Cross-agent invocation is permitted by listing a peer agent's bot identity (GitHub login or Asana user GID) in the callee's `users` list — see T-23 for the design intent and runaway-chain defense.

**T-5 (Accepted for v1):** Cedar policy files under `cedar/*.cedar` express per-agent allow/deny rules for tool calls, but no evaluator runs them at invocation time. A prompt-injected agent can call any tool its MCP server exposes. Documented as a roadmap item. The intended evaluator would intercept every `@tool` call in the Strands runtime and deny forbidden operations, which would bound T-1/T-2/T-3 blast radius materially.

**T-6 (Mitigated):** The Dispatch Router Lambda's IAM policy grants only `bedrock-agentcore:InvokeAgentRuntime`, scoped to `arn:aws:bedrock-agentcore:${AWS::Region}:${AWS::AccountId}:runtime/*` and the corresponding `runtime/*/runtime-endpoint/*` shape. The router cannot invoke runtimes in other accounts or regions, and cannot call `bedrock:InvokeAgent` on the legacy Bedrock Agents service.

**T-7 (Mitigated in guidance):** The deploy role's OIDC trust policy is created by operators (not by the foundation stack). Every piece of shipping guidance — `docs/aws-deploy.md` §1.3, `skills/pdlc-agents-setup-claude-code`, `skills/pdlc-agents-register-triggers` — recommends `StringEquals` with two explicit `sub` claims:

- `repo:<org>/<repo>:ref:refs/heads/main` — covers `push`-to-main deploys and comment-driven triggers (`issue_comment`, `pull_request_review_comment`, `pull_request_review`), which all run in the default-branch context.
- `repo:<org>/<repo>:pull_request` — covers `claude-code.yml`'s `pull_request: [opened, synchronize]` trigger, the only true "pull_request event" in OIDC terms.

Wildcards (`StringLike: repo:<org>/<repo>:*`) are explicitly called out as anti-patterns. Operators are responsible for applying the guidance when they create the role.

### 3.3 Credential & Secret Management

| ID | Threat | Severity | Component | STRIDE | Status |
|----|--------|----------|-----------|--------|--------|
| T-8 | **Asana PAT lifetime in Lambda execution environment** | — | C-2 | Information Disclosure | Mitigated |
| T-9 | **Webhook secret self-write during handshake** | — | C-2 | Tampering | Mitigated |
| T-10 | **OAuth token refresh failure leaves stale credentials** | **Low** | C-4, C-6 | Denial of Service | Accepted |
| T-11 | **GitHub PAT scope may be overly broad** | **Medium** | C-9 | Elevation of Privilege | Open |

**T-8 (Mitigated):** `infra/dispatch/asana_webhook.py` fetches the Asana PAT on demand inside `asana_get`, caches it only on an `invocation_state` dict that goes out of scope when the handler returns, and never retains it on a module-level global. The webhook secret is likewise fetched per invocation. A memory-disclosure or verbose-log incident exposes at most the secrets used by the single request that was in flight, not the secrets used by every prior request in the same execution environment.

**T-9 (Mitigated):** The asana-webhook Lambda's IAM policy grants only `ssm:GetParameter` on the Asana PAT and webhook-secret parameters in steady state — it cannot overwrite the secret. The handshake still works because registration is gated through `scripts/bootstrap_asana_webhook.py`: the operator runs the script, which attaches a temporary inline `ssm:PutParameter` policy (scoped to the single parameter) to the Lambda's execution role, calls the Asana webhooks API, polls SSM until the handshake writes the secret, and removes the inline policy. Outside that registration window, an attacker who can replay Asana's handshake receives a 403 — the Lambda logs "handshake PutParameter denied" and refuses to overwrite the stored secret.

**T-10 (Accepted):** Agents surface OAuth refresh errors in logs but there is no automated rotation or CloudWatch alarm. Operators are expected to notice failed runs and re-run `pdlc-agents-connect-asana`. Acceptable for a reference architecture; production deployments should add alarms on SSM parameter age.

**T-11 (Open):** The GitHub MCP server is authenticated with either a PAT or a GitHub App installation. The PAT path cannot enforce minimum scopes — a token with `repo` grants write access to every repository the owner can access, not just the target repo. The App path is scope-bounded but requires more setup. Roadmap: recommend (and default to) the App path in documentation; flag overly broad PATs at startup.

### 3.4 Network & API Security

| ID | Threat | Severity | Component | STRIDE | Status |
|----|--------|----------|-----------|--------|--------|
| T-12 | **Public API Gateway endpoint for Asana webhooks** | **Medium** | C-2 | Spoofing, DoS | Partially mitigated |
| T-13 | **No API Gateway throttling or WAF configured** | **Medium** | C-2 | Denial of Service | Open |
| T-14 | **Dispatch Router 900-second timeout** | **Low** | C-3 | Denial of Service | Accepted |

**T-12 (Partially mitigated):** The `/asana/webhook` endpoint is public but every request's HMAC-SHA256 signature is verified against the stored webhook secret before any downstream work is done. Forged events are rejected at ingress. What remains open: volumetric DDoS and replay — see T-13.

**T-13 (Open):** The SAM template sets no throttling, burst, or WAF configuration on the webhook API. A flood of malformed requests still triggers Lambda cold starts and signature-verification work. Fix path: add API Gateway usage-plan throttling and optionally attach AWS WAF for IP-based rate limiting.

**T-14 (Accepted):** The Dispatch Router Lambda timeout is 900 seconds to accommodate the synchronous `InvokeAgentRuntime` call for long agent runs. A hung agent ties up the Lambda execution environment; combined with concurrency limits, this could delay legitimate dispatches. Acceptable for the scale this architecture targets.

### 3.5 Data Integrity & Exfiltration

| ID | Threat | Severity | Component | STRIDE | Status |
|----|--------|----------|-----------|--------|--------|
| T-15 | **Agent exfiltrates data to unauthorized destinations** | **High** | C-4 | Information Disclosure | Accepted |
| T-16 | **DynamoDB assignment records contain full instruction text** | **Low** | C-5 | Information Disclosure | Mitigated |
| T-17 | **Agent output posted to wrong platform context** | **Medium** | C-4 | Tampering | Open |

**T-15 (Accepted):** A prompt-injected agent could use a write-capable tool (GitHub comment, Asana task, Researcher's Tavily web search) to exfiltrate sensitive context. The primary defense would be Cedar runtime enforcement (see T-5). In the current architecture, the defense-in-depth controls are:

- Agents have no direct network access beyond their MCP servers and Bedrock (no arbitrary outbound HTTP).
- Tool invocations are logged to CloudWatch, producing an audit trail.
- Per-agent IAM runtime roles grant only the specific SSM parameters each agent needs.

Exfiltration through legitimate tool paths (e.g., encoding data in a GitHub comment) is not prevented, and is accepted as an LLM-trust limitation until Cedar enforcement lands.

**T-16 (Mitigated):** DynamoDB encryption-at-rest uses AWS-owned keys by default. The `dispatch-assignments` table has a 30-day TTL on every record (`AttributeName: ttl`, `Enabled: true`), bounding exposure window. Cross-account access is not possible without an IAM principal in the same account.

**T-17 (Open):** `source_context` (GitHub `issue_number`, Asana `task_gid`) is passed through untrusted channels (webhook payloads). If manipulated, the agent posts its output to a different issue or task than the originator. Fix path: validate the target context against the original mention event before posting; cross-check sender and target belong to the same project or repo.

### 3.6 Supply Chain & Build Pipeline

| ID | Threat | Severity | Component | STRIDE | Status |
|----|--------|----------|-----------|--------|--------|
| T-18 | **Compromised base image or dependency in agent container** | **Medium** | C-12 | Tampering | Partially mitigated |
| T-19 | **ECR image tag mutability** | — | C-12 | — | Mitigated |
| T-20 | **GitHub Actions workflow injection** | **Medium** | C-1 | Tampering | Partially mitigated |

**T-18 (Partially mitigated):** Every CI build runs Amazon Inspector SBOM scanning on the agent container. Python dependencies are pinned to versions in `requirements.txt` but not hashed. Dependabot opens PRs for updates. Fix path: add `pip install --require-hashes` with a lockfile, and gate deploys on Inspector severity.

**T-19 (Mitigated):** ECR repositories for fleet agents (`sdlc-agents/*`) are created with `--image-tag-mutability IMMUTABLE` by both `.github/workflows/deploy-agent.yml` and the `pdlc-agents-provision-aws` skill. Images are tagged with `:${github.sha}` only; no `:latest` tag is produced. An attacker with ECR push rights cannot silently overwrite a running image — every push requires a new tag, and the AgentCore runtime is updated explicitly in CI. Operators with pre-existing MUTABLE repos from earlier deploys are not automatically upgraded; delete and recreate for the hardened default.

**T-20 (Partially mitigated):** `.github/workflows/agent-dispatch.yml` passes `${{ github.event.comment.body }}` via the `env:` context, not direct shell interpolation — the standard mitigation for command injection in GitHub Actions. This pattern is safe today; any future refactoring that moves the comment body into `run:` interpolation would reintroduce the vulnerability. The review checklist for workflow changes should flag this.

### 3.7 Denial of Service & Resource Exhaustion

| ID | Threat | Severity | Component | STRIDE | Status |
|----|--------|----------|-----------|--------|--------|
| T-21 | **Token budget exhaustion** | **Medium** | C-4 | Denial of Service | Open |
| T-22 | **Concurrency slot exhaustion** | **Medium** | C-3 | Denial of Service | Partially mitigated |
| T-23 | **Runaway agent-to-agent chains** | **High** | C-3, C-4 | Denial of Service | Open |

**T-21 (Open):** `.dispatch/agents.yaml` declares `daily_token_budget` per agent but no runtime enforcement exists. A flood of requests or a prompt-injected loop could run the Bedrock bill up. Fix path: track daily token consumption per agent in DynamoDB and reject dispatches over budget. AWS Service Quotas on Bedrock model invocations is an out-of-band ceiling operators can set.

**T-22 (Partially mitigated):** The Dispatch Router consults DynamoDB for active-assignment counts per agent and rejects dispatches over `max_concurrent`. What's absent: per-user rate limiting. A single user can legitimately fill the concurrency window and block others. Fix path: add a per-sender dispatch-count bucket in DynamoDB with a short rolling window.

**T-23 (Open):** Cross-agent invocation is an **intentional design property** of this fleet, not a threat. Workitems orchestrates Docwriter (and Claude Code) by posting `@docwriter` / `@claude` comments that the dispatch workflow fires on; future handoffs such as Adr → Workitems are anticipated. A blanket "reject bot-authored events" rule would break the primary workflow, so it is explicitly not the control.

The real threat is a **chain that doesn't stop** — a prompt-injected or mis-prompted agent that issues mentions indefinitely, or a bidirectional handoff that fails to terminate. Consequences are compute spend (Bedrock token bill), DynamoDB write pressure on the assignments table, and delayed dispatch for legitimate work as concurrency slots fill.

**Current controls:**
- `authorization.users` allowlists per agent (T-4) — runaway only propagates between agents the operator has explicitly paired.
- `max_concurrent` per agent in the registry, enforced by the Dispatch Router. Caps in-flight work but does not bound total volume over time.
- Comment-pattern gating in `agent-dispatch.yml` — the workflow fires only on known `@agent` tokens, which bounds the surface but not the volume.

**Recommended mitigation (circuit breaker in the Dispatch Router):** thread a `parent_assignment_id` through dispatch and track three signals in DynamoDB; trip on any of them and emit a CloudWatch alarm:

1. **Chain depth** — reject when the parent chain exceeds a configured depth (e.g. 5). Catches narrow recursion like workitems → docwriter → workitems → docwriter.
2. **Per-agent dispatch rate** — a rolling-window counter keyed on `(agent_id, minute_bucket)`. Rejects past N dispatches/minute. Catches volume-based runaway regardless of origin.
3. **Daily token spend** — actualize the `daily_token_budget` field already declared in the registry (see T-21). Reject past the limit.

The three are complementary: depth handles narrow loops, rate handles fan-out floods, budget is the longer-horizon backstop. Implementation belongs in the Router where all three signals converge.

### 3.8 Security-Scan Exceptions (Accepted with Rationale)

Automated scanners (checkov, semgrep, bandit) flag several patterns in this repository that are intentional design choices for the reference architecture rather than unmitigated risks. They are enumerated here so that operators who re-run the same scans know why these findings are not treated as open work. Each exception should be re-evaluated if the deployment context changes (multi-tenant, regulated workload, customer-managed keys mandate, etc.).

| ID | Finding | Why accepted | If your posture differs |
|----|---------|--------------|-------------------------|
| T-24 | **CKV_AWS_119** — DynamoDB table not encrypted with a customer-managed KMS key | `dispatch-assignments` holds operational state (mention body, assignment status, guardrail trip records) with a 30-day TTL — not long-lived PII or regulated data. AWS-owned keys meet the bar for a reference architecture, avoid key-management surface, and incur no per-request KMS cost. | Swap `SSESpecification` to `KMSMasterKeyId: !Ref <YourCmkKey>` and grant `kms:Decrypt`/`kms:GenerateDataKey` to the Dispatch Router runtime role. |
| T-25 | **CKV_DOCKER_2** — Dockerfiles missing `HEALTHCHECK` instructions | Bedrock AgentCore Runtime manages container lifecycle via its invocation endpoint and internal liveness signals; Docker's `HEALTHCHECK` directive is not consulted by AgentCore. Adding it would give a false impression of active health management without affecting runtime behavior. | Only meaningful if you migrate agents off AgentCore to a runtime that honors Docker healthchecks (ECS, raw Kubernetes); at that point wire a Strands `/health` endpoint and add the directive. |
| T-26 | **CKV_AWS_173** — Lambda environment variables not encrypted with a KMS CMK | The Lambda functions' env vars hold *references* to SSM parameters (names and resource ARNs), not secret values. Actual credentials are fetched from SSM SecureString at invocation time (T-8). A CMK on the env-var block would encrypt public identifiers. | If your account-level policy mandates CMK-everywhere, set `KmsKeyArn` on each `AWS::Serverless::Function` to an existing CMK and grant `kms:Decrypt` to the runtime role. |
| T-27 | **CKV_AWS_120** — API Gateway caching not enabled on the webhook endpoint | The Asana webhook handler verifies HMAC-SHA256 on every inbound payload and routes events to the Dispatch Router asynchronously. Caching would serve cached 200s to replayed or forged payloads and defeat signature verification semantics. | Not recommended to enable. |
| T-28 | **CKV_AWS_117** — Lambda functions not deployed inside a VPC | Both Lambdas (Dispatch Router, Asana webhook) talk only to AWS service endpoints (DynamoDB, SSM, Bedrock AgentCore, Lambda Invoke) and to external HTTPS APIs (Asana, GitHub). There are no private VPC resources to reach. A VPC attachment would add ENI management + cold-start latency with no reachability benefit. | If you introduce a private backend (RDS, internal ALB, VPC endpoint to Bedrock for egress control), attach both Lambdas to a private subnet with NAT egress and add `AWSLambdaVPCAccessExecutionRole`. |

**Mitigated by this same review** (no longer exceptions): CKV_AWS_28 (DynamoDB PITR enabled), CKV_AWS_18/CKV_AWS_21 (S3 access logging + versioning), CKV_AWS_73/CKV_AWS_76 (API Gateway X-Ray + access logs), CKV_AWS_115/CKV_AWS_116 (Lambda reserved concurrency + DLQ), CKV_DOCKER_3 (non-root container user), CKV2_GHA_1 (top-level workflow `permissions: contents: read`).

---

## 4. Trust Boundaries

| Boundary | Components Inside | Components Outside | Controls |
|----------|-------------------|--------------------|----------|
| **AWS Account** | C-2 through C-8, C-11, C-12 | C-1 (GitHub Actions), C-9 (GitHub MCP), C-10 (Asana MCP) | IAM, OIDC federation |
| **Dispatch Layer** | C-2, C-3 | C-4 (Agents) | IAM roles, Lambda invoke permissions, scoped `InvokeAgentRuntime` |
| **Agent Runtime** | Individual agent container | Other agents, Dispatch layer | AgentCore runtime isolation, per-agent IAM roles |
| **External APIs** | — | C-9, C-10 | OAuth/PAT authentication, HTTPS TLS |
| **CI/CD Pipeline** | C-1, C-12 | Developer workstations | OIDC (scoped `sub` claims), branch protection, Inspector scans, immutable ECR tags |

---

## 5. Risk Summary

Risk is expressed as the residual exposure given current controls. Mitigated threats are not re-scored.

| Severity | Count | Threats |
|----------|-------|---------|
| **Critical (Partially mitigated)** | 1 | T-1 |
| **High (Accepted)** | 1 | T-15 |
| **High (Partially mitigated)** | 2 | T-2, T-3 |
| **High (Open)** | 1 | T-23 |
| **Medium (Open or Partial)** | 8 | T-11, T-13, T-17, T-21 (open); T-12, T-18, T-20, T-22 (partial) |
| **Low (Accepted with rationale)** | 5 | T-24, T-25, T-26, T-27, T-28 |
| **Low** | 3 | T-10, T-14, T-16 |
| **Mitigated (Not scored)** | 6 | T-4, T-6, T-7, T-8, T-9, T-19 |

---

## 6. Recommended Next Work

Roadmap items ordered by leverage:

1. **Cedar runtime enforcement (T-5, T-15)** — the highest-value *structural* control. Intercepting tool calls and enforcing per-agent allow/deny rules bounds prompt-injection blast radius, prevents exfiltration via unauthorized tools, and makes the `cedar/*.cedar` files load-bearing rather than aspirational. Complements the now-shipped Guardrails layer: Guardrails reduces the probability of subversion; Cedar bounds the damage if it occurs.
2. **Dispatch circuit breaker (T-23, T-21, T-22)** — thread `parent_assignment_id` through dispatch; enforce chain-depth, per-agent rolling-rate, and daily-token-budget limits in the Dispatch Router with CloudWatch alarms on trip. Closes the primary DoS surface of a by-design multi-agent topology.
3. **Input validation on dispatch (T-1, T-2, T-17)** — lightweight classifier-based pre-filter in the Dispatch Router layered before Guardrails; cross-check that agent output targets the originating context.
4. **API Gateway throttling (T-13)** — usage-plan throttling and optional WAF for IP-based limits.
5. **GitHub App over PAT (T-11)** — default docs and skills to App installation tokens.
6. **Dependency hash-pinning (T-18)** — `pip install --require-hashes` with a lockfile.

---

## 7. Assumptions & Scope

- Covers the fleet as shipped: four agents (workitems, researcher, docwriter, adr), Dispatch Router, Asana webhook. Slack integration, AgentCore Memory, AgentCore Gateway, AgentCore Identity, and Feedback/UAT agents are out of scope — they are not yet implemented.
- Single AWS account + single region deployment. Multi-account or cross-region introduces additional trust boundaries not analyzed here.
- LLM model behavior (hallucinations, jailbreaks, adversarial-input sensitivity) is treated as a baseline risk of using foundation models. Mitigations focus on constraining what the agent can *do*, not on preventing the model from generating bad outputs.
- GitHub MCP and Asana MCP servers are treated as trusted third-party services. Their internal security posture is out of scope.
- This fleet is intended as a reference architecture. Operators deploying it against sensitive production repositories should revisit every **Accepted** and **Open** finding and make their own risk decisions before launch.

---

## Revision History

| Date | Version | Changes |
|------|---------|---------|
| 2026-05-05 | 1.7 | Checkov / semgrep scan pass (Kai Xu review). Hardened CFN: DynamoDB PITR, S3 versioning + access logs, API Gateway X-Ray + access logs, Lambda reserved concurrency + SQS DLQ; Dockerfiles switched to non-root `agent` user; all workflows given top-level `permissions: contents: read`. New §3.8 documents T-24..T-28 — accepted scanner findings (CKV_AWS_119, CKV_DOCKER_2, CKV_AWS_173, CKV_AWS_120, CKV_AWS_117) with rationale and upgrade paths. |
| 2026-05-05 | 1.6 | Security review fixes: T-4 Asana sender is now the user `.gid` (was the self-editable display name — a HIGH-severity auth bypass); Router rejects unresolved sender sentinels ("", "unknown") as defense-in-depth. §3.1 narrative now states the shipping guardrail posture (`InputStrength: MEDIUM`, `OutputStrength: NONE`) — prior text implied HIGH/HIGH. |
| 2026-05-05 | 1.5 | T-1/T-2/T-3 flipped from Accepted to Partially mitigated — Bedrock Guardrails (`PROMPT_ATTACK`) enforced at the Dispatch Router edge and on every agent's `InvokeModel` call. Section 6 roadmap re-ordered: Cedar enforcement now #1. |
| 2026-05-01 | 1.4 | Added Amazon Bedrock Guardrails (prompt-attack filter) as the recommended near-term defense for T-1/T-2/T-3; promoted to #1 in Section 6 roadmap ahead of Cedar enforcement |
| 2026-05-01 | 1.3 | T-8 flipped to Mitigated (PAT fetch moved to invocation scope); T-9 flipped to Mitigated (Lambda loses steady-state `ssm:PutParameter`; operator bootstrap script mediates Asana handshake); T-1 Authorization bullet corrected to reference T-4 allowlist |
| 2026-05-01 | 1.2 | T-4 flipped to Mitigated (registry defaults to `users: []`, router fails closed); T-23 reframed as intentional cross-agent design with circuit-breaker as the recommended control |
| 2026-05-01 | 1.1 | Reframed as living document; statuses added (Mitigated / Partial / Accepted / Open) for each threat |
| 2026-05-01 | 1.0 | Initial assessment of v1 fleet |
