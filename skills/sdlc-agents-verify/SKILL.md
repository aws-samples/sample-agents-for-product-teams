---
name: sdlc-agents-verify
description: Use when the user wants to confirm their SDLC agent installation actually works end-to-end. Runs three layers of smoke tests per selected agent — runtime health, credential freshness, trigger path — and reports a per-agent pass/fail summary. Does not modify infrastructure; safe to run any time. Invoked by sdlc-agents after the register-triggers step.
---

# Verify the SDLC Agent Fleet is working

Smoke-test in three layers per agent. Don't move on to the next layer if the previous one fails — the failure mode tells you where to look.

## Layer 1 — Runtime health (AgentCore directly)

For each agent in `.sdlc-agents/selection.yaml`, invoke the runtime with a health-check payload:

```bash
for AGENT in $(yq '.agents[]' .sdlc-agents/selection.yaml); do
  RID=$(aws bedrock-agentcore-control list-agent-runtimes \
    --region "$REGION" \
    --query "agentRuntimes[?agentRuntimeName=='${AGENT}'].agentRuntimeId | [0]" \
    --output text)
  if [ "$RID" = "None" ] || [ -z "$RID" ]; then
    echo "FAIL $AGENT — no runtime found"
    continue
  fi
  ARN="arn:aws:bedrock-agentcore:${REGION}:${ACCOUNT_ID}:runtime/${RID}"
  RESULT=$(aws bedrock-agentcore invoke-agent-runtime \
    --agent-runtime-arn "$ARN" \
    --payload "$(printf '{"prompt":"health check"}' | base64)" \
    --region "$REGION" \
    /tmp/smoke-${AGENT}.json 2>&1)
  STATUS=$?
  if [ $STATUS -eq 0 ]; then
    echo "PASS $AGENT — $(head -c 200 /tmp/smoke-${AGENT}.json)"
  else
    echo "FAIL $AGENT — invoke returned $STATUS: $RESULT"
  fi
done
```

Common Layer 1 failures:

| Symptom | Likely cause | Fix |
|---|---|---|
| `ResourceNotFoundException` | Runtime doesn't exist yet | Re-run `sdlc-agents-provision-aws`, or push code so the deploy workflow creates it |
| `AccessDeniedException` | Caller lacks `bedrock-agentcore:InvokeAgentRuntime` | Fix IAM on the calling role |
| 200 with empty result | Agent code started but didn't reach its LLM call | Check CloudWatch `/aws/bedrock-agentcore/runtimes/<agent>-<id>-DEFAULT` logs |
| 200 with error text mentioning "Asana" | Agent couldn't reach Asana MCP | Credential issue — re-run `sdlc-agents-connect-asana` verify section |

## Layer 2 — Credential freshness

The Layer 1 health check only confirms the runtime *starts*. Many agent tools probe external services at first use, and stale credentials show up there.

For each integration the user has connected, mint a fresh token and probe the endpoint:

### Asana

```bash
python3 <<'PY'
import boto3, requests
ssm = boto3.client("ssm", region_name="$REGION")
cid = ssm.get_parameter(Name="/sdlc-agents/asana-mcp-client-id", WithDecryption=True)["Parameter"]["Value"]
cs = ssm.get_parameter(Name="/sdlc-agents/asana-mcp-client-secret", WithDecryption=True)["Parameter"]["Value"]
rt = ssm.get_parameter(Name="/sdlc-agents/asana-mcp-refresh-token", WithDecryption=True)["Parameter"]["Value"]
r = requests.post("https://app.asana.com/-/oauth_token", data={
    "grant_type":"refresh_token","client_id":cid,"client_secret":cs,"refresh_token":rt}, timeout=15)
if not r.ok:
    print(f"FAIL asana-mcp — refresh: {r.status_code} {r.text}")
else:
    tok = r.json()["access_token"]
    mcp = requests.post("https://mcp.asana.com/v2/mcp",
        headers={"Authorization": f"Bearer {tok}","Content-Type":"application/json","Accept":"application/json, text/event-stream"},
        json={"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"verify","version":"0.1"}}},
        timeout=15)
    print(f"{'PASS' if mcp.ok else 'FAIL'} asana-mcp — initialize: {mcp.status_code}")
PY
```

### GitHub

```bash
python3 <<'PY'
import boto3, requests
ssm = boto3.client("ssm", region_name="$REGION")
try:
    tok = ssm.get_parameter(Name="/sdlc-agents/github-mcp-token", WithDecryption=True)["Parameter"]["Value"]
except Exception:
    print("SKIP github — no PAT found at /sdlc-agents/github-mcp-token (maybe using App auth)")
else:
    r = requests.get("https://api.github.com/user",
        headers={"Authorization": f"Bearer {tok}","Accept":"application/vnd.github+json"}, timeout=15)
    print(f"{'PASS' if r.ok else 'FAIL'} github-pat — /user: {r.status_code}")
PY
```

## Layer 3 — End-to-end trigger path

Layer 1 + 2 confirm the runtime and credentials are healthy. Layer 3 confirms an `@agent` mention in the actual tool UI triggers the agent and gets a visible response.

This layer cannot be fully automated — it requires the user to post a mention in their actual Asana/GitHub/Slack. Walk the user through:

1. Open your `Asana` demo board (or repo / Slack channel).
2. Post `@workitems health check` on any task/issue.
3. Watch for:
   - **Within 5s**: an emoji reaction (👀 or 👍) on your comment
   - **Within 30–60s**: a new comment from the agent starting with its signature (e.g. `🤖 **[Workitems Agent]**`)

While the user tries this, tail the pipeline:

```bash
# Run these in parallel terminals (or one-shot --since 2m)
aws logs tail "/aws/lambda/asana-webhook-${STAGE}" --since 2m --region "$REGION" --follow
aws logs tail "/aws/lambda/dispatch-router-${STAGE}" --since 2m --region "$REGION" --follow
aws logs tail "/aws/bedrock-agentcore/runtimes/workitems-<id>-DEFAULT" --since 2m --region "$REGION" --follow
```

Trace the event through all three logs:

1. **webhook Lambda** should log `Processing 1 Asana events` then `Dispatching to workitems: comment_mention`
2. **dispatch-router Lambda** should log `Dispatch event:` with the full context, then `Dispatched assignment <uuid> to workitems`
3. **runtime** logs should show the agent picking up the invoke and starting tool calls

If a log is silent, the breakpoint is between the previous log and this one.

## Report

At the end, produce a table:

```
Agent        L1 Runtime   L2 Creds        L3 End-to-end
workitems    PASS         asana PASS      PASS (reaction + reply seen on task 1214...)
                          github PASS
docwriter    PASS         asana PASS      SKIP (no @docwriter mentioned yet)
                          github PASS
researcher   FAIL         asana PASS      —
                          (no tavily key)
```

If anything is FAIL or SKIP, call it out explicitly so the user knows what's not actually working yet.

## What this skill does NOT do

- Load-test. Smoke tests only — one invocation per agent.
- Auto-retry on transient failures. A failure is useful signal; surface it.
- Invoke agents with content that would cost real money. Always use "health check" or equivalent cheap prompts.
