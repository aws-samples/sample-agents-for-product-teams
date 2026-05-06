# Dispatch: Unified @Agent Work Assignment System
## Cross-Platform Agent Routing for GitHub, Asana, and Slack

> **Status: target design.** The shipping Dispatch layer (`infra/dispatch/router.py` + `asana_webhook.py`, plus `.github/workflows/agent-dispatch.yml`) routes mentions from **GitHub** and **Asana** to the right AgentCore Runtime and tracks assignments in DynamoDB. **Slack** routing described in this spec is not wired up — there's no Slack event receiver Lambda or signing-secret path today. The registry advertises Slack triggers for some agents but the path is dark end-to-end. For current behavior, read the router and webhook Lambda source.

---

## 1. The Pattern

Any human on the team can assign work to any autonomous agent by @mentioning it in the tool they're already using — the same way you'd tag a teammate.

```
GitHub Issue comment:    @uat write E2E tests for this story
Asana task comment:      @workitems generate a status report for this sprint
Slack message:           @uat run regression suite against staging
GitHub PR comment:       @uat verify this PR doesn't break the upload flow
Asana task assignment:   Assign task → "Uat (Bot)"
```

The system routes the mention to the correct AgentCore Runtime agent, passes context, and the agent posts results back to where the request originated.

---

## 2. Agent Registry

Each agent has a registered identity across all platforms:

| Agent ID | Purpose | GitHub Trigger | Asana Trigger | Slack Trigger |
|----------|---------|---------------|---------------|---------------|
| `claude` | Developer (code impl, review) | `@claude` | `@claude` | `@claude` |
| `uat` | UAT Tester (Playwright tests) | `@uat` / `@uat` | `@uat` / `@uat` | `@uat` |
| `workitems` | PO/PM (status, sync, triage) | `@workitems` | `@workitems` | `@workitems` |
| `sentinel` | Security review | `@sentinel` | `@sentinel` | `@sentinel` |
| `docbot` | Technical writer | `@docbot` | `@docbot` | `@docbot` |

Aliases are supported: `@uat` resolves to `@uat`. Defined in a config file in the repo.

---

## 3. Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                        Event Sources                                 │
│                                                                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │
│  │ GitHub       │  │ Asana        │  │ Slack        │              │
│  │              │  │              │  │              │              │
│  │ • Issue      │  │ • Task       │  │ • App        │              │
│  │   comment    │  │   comment    │  │   mention    │              │
│  │ • PR comment │  │ • Task       │  │ • Slash      │              │
│  │ • Issue      │  │   assigned   │  │   command    │              │
│  │   assigned   │  │ • Custom     │  │              │              │
│  │ • PR review  │  │   field set  │  │              │              │
│  │   comment    │  │              │  │              │              │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘              │
│         │                 │                  │                       │
└─────────┼─────────────────┼──────────────────┼───────────────────────┘
          │                 │                  │
          ▼                 ▼                  ▼
┌──────────────────────────────────────────────────────────────────────┐
│                    Dispatch Router (Lambda)                           │
│                                                                      │
│  1. Verify event authenticity (webhook signatures)                  │
│  2. Parse @mention → resolve agent ID (incl. aliases)               │
│  3. Extract instruction text + context                              │
│  4. Check authorization (is this user allowed to invoke this agent?)│
│  5. Build context payload                                           │
│  6. Invoke AgentCore Runtime                                        │
│  7. Track assignment in DynamoDB                                    │
│  8. Post acknowledgment back to source                              │
│                                                                      │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────────────────┐    │
│  │ Agent       │  │ Auth Table   │  │ Assignment Tracker      │    │
│  │ Registry    │  │ (who can     │  │ (DynamoDB)              │    │
│  │ (config)    │  │  invoke whom)│  │                         │    │
│  └─────────────┘  └──────────────┘  │ • assignment_id         │    │
│                                      │ • source (gh/asana/slk) │    │
│                                      │ • agent_id              │    │
│                                      │ • requester             │    │
│                                      │ • instruction           │    │
│                                      │ • status                │    │
│                                      │ • created_at            │    │
│                                      │ • completed_at          │    │
│                                      │ • result_summary        │    │
│                                      └─────────────────────────┘    │
└──────────────────────────┬───────────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────────────┐
│                    AgentCore Runtime                                  │
│                                                                      │
│  ┌──────────┐  ┌───────────┐  ┌──────────┐  ┌──────────┐          │
│  │ @claude  │  │ @uat│  │ @workitems   │  │ @sentinel│          │
│  │ (dev)    │  │ (UAT)     │  │ (PO/PM)  │  │ (sec)    │          │
│  └────┬─────┘  └─────┬─────┘  └────┬─────┘  └────┬─────┘          │
│       │               │             │              │                │
│       └───────────────┼─────────────┼──────────────┘                │
│                       │             │                                │
│                       ▼             ▼                                │
│              Results posted back to originating platform             │
│              via AgentCore Gateway (GitHub, Asana, Slack)            │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 4. Platform-Specific Trigger Mechanics

### 4a. GitHub — Actions Workflow (Existing Pattern, Extended)

GitHub already has the @claude pattern working. We extend it to support multiple agents by parameterizing the trigger phrase and routing to different backends.

**Single workflow, multi-agent:**

```yaml
name: Agent Dispatch
permissions:
  contents: read
  pull-requests: write
  issues: write
  id-token: write

on:
  issue_comment:
    types: [created]
  pull_request_review_comment:
    types: [created]
  issues:
    types: [opened, assigned]

jobs:
  dispatch:
    # Trigger on any registered agent mention
    if: |
      (github.event_name == 'issue_comment' && (
        contains(github.event.comment.body, '@uat') ||
        contains(github.event.comment.body, '@uat') ||
        contains(github.event.comment.body, '@workitems') ||
        contains(github.event.comment.body, '@sentinel') ||
        contains(github.event.comment.body, '@docbot')
      )) ||
      (github.event_name == 'issues' && (
        github.event.action == 'assigned' && (
          github.event.assignee.login == 'uat-bot' ||
          github.event.assignee.login == 'workitems-bot' ||
          github.event.assignee.login == 'sentinel-bot'
        )
      ))
    runs-on: ubuntu-latest
    steps:
      - name: Configure AWS Credentials
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.DISPATCH_ROLE_ARN }}
          aws-region: us-west-2

      - name: Route to Agent
        run: |
          # Extract mention and instruction from event payload
          BODY="${{ github.event.comment.body || github.event.issue.body }}"
          
          # Call Dispatch Router Lambda
          aws lambda invoke \
            --function-name dispatch-router \
            --payload "$(jq -n \
              --arg source "github" \
              --arg event_type "${{ github.event_name }}" \
              --arg body "$BODY" \
              --arg repo "${{ github.repository }}" \
              --arg issue_number "${{ github.event.issue.number || github.event.pull_request.number }}" \
              --arg sender "${{ github.event.sender.login }}" \
              --arg event_action "${{ github.event.action }}" \
              --arg assignee "${{ github.event.assignee.login }}" \
              '{source: $source, event_type: $event_type, body: $body, 
                repo: $repo, issue_number: $issue_number, sender: $sender,
                event_action: $event_action, assignee: $assignee}'
            )" \
            response.json
```

**@claude stays on its own workflow** — it uses `anthropics/claude-code-action@v1` directly and doesn't need the Dispatch Router because it runs Claude Code (not an AgentCore agent). The dispatch workflow handles all other agents.

**Assignment via GitHub user:** Create bot accounts (`uat-bot`, `workitems-bot`) as repo collaborators. Assigning an issue to `uat-bot` triggers the same dispatch flow without needing a comment.

### 4b. Asana — Webhook + Lambda (New)

Asana has no native GitHub Actions equivalent, so we build the listener ourselves.

**Three trigger mechanisms, same pipeline:**

**Trigger 1: Comment mention**
A human comments `@uat write tests for this story` on an Asana task. The webhook fires on `story` resource type with `added` action.

**Trigger 2: Task assignment**
Assign a task to the agent's Asana bot user account (e.g., "Uat Bot"). The webhook fires on `task` resource type with `changed` action (assignee field changed).

**Trigger 3: Custom field**
Set a custom field "Agent" (dropdown) to "Uat" or "Workitems". This is the most Asana-native approach — it works with Asana rules, forms, and templates.

**Webhook setup:**

```python
import hashlib
import hmac
import json
import re
import boto3

# Lambda function: asana-webhook-receiver
# Fronted by API Gateway with public HTTPS endpoint

AGENT_PATTERN = re.compile(
    r'@(claude|uat|uat|workitems|sentinel|docbot)\b',
    re.IGNORECASE
)

ALIAS_MAP = {
    'uat': 'uat',
}

AGENT_BOT_USERS = {
    'uat': '1234567890',  # Asana user GID for Uat Bot
    'workitems': '1234567891',
    'sentinel': '1234567892',
}

def handler(event, context):
    headers = event.get('headers', {})
    body = event.get('body', '')
    
    # --- Asana handshake (first-time setup) ---
    if 'x-hook-secret' in headers:
        return {
            'statusCode': 200,
            'headers': {'X-Hook-Secret': headers['x-hook-secret']},
            'body': ''
        }
    
    # --- Verify signature ---
    signature = headers.get('x-hook-signature', '')
    expected = hmac.new(
        WEBHOOK_SECRET.encode(), body.encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return {'statusCode': 401}
    
    # --- Process events ---
    payload = json.loads(body)
    events = payload.get('events', [])
    
    for event_data in events:
        resource_type = event_data.get('resource', {}).get('resource_type')
        action = event_data.get('action')
        parent_gid = event_data.get('parent', {}).get('gid')
        
        # Trigger 1: Comment with @mention
        if resource_type == 'story' and action == 'added':
            process_comment_mention(event_data, parent_gid)
        
        # Trigger 2: Task assignment changed
        elif resource_type == 'task' and action == 'changed':
            if 'assignee' in event_data.get('change', {}).get('field', ''):
                process_assignment(event_data)
        
        # Trigger 3: Custom field changed
        elif resource_type == 'task' and action == 'changed':
            process_custom_field(event_data)
    
    return {'statusCode': 200}


def process_comment_mention(event_data, task_gid):
    """Fetch the comment text, check for @agent mention, dispatch."""
    story_gid = event_data['resource']['gid']
    
    # Fetch full story text (webhook payload is lightweight)
    story = asana_client.stories.get_story(story_gid)
    text = story.get('text', '')
    
    match = AGENT_PATTERN.search(text)
    if not match:
        return
    
    agent_id = match.group(1).lower()
    agent_id = ALIAS_MAP.get(agent_id, agent_id)
    
    # Extract instruction (everything after the @mention)
    instruction = text[match.end():].strip()
    
    # Fetch task context
    task = asana_client.tasks.get_task(task_gid)
    
    dispatch_to_agent(
        source='asana',
        agent_id=agent_id,
        instruction=instruction,
        context={
            'task_gid': task_gid,
            'task_name': task['name'],
            'task_notes': task.get('notes', ''),
            'task_assignee': task.get('assignee', {}).get('name'),
            'task_custom_fields': task.get('custom_fields', []),
            'project_gid': task.get('projects', [{}])[0].get('gid'),
            'requester': story.get('created_by', {}).get('name'),
        }
    )


def process_assignment(event_data):
    """Task assigned to a bot user account."""
    task_gid = event_data['resource']['gid']
    task = asana_client.tasks.get_task(task_gid)
    
    assignee_gid = task.get('assignee', {}).get('gid')
    
    # Check if assigned to a known bot user
    for agent_id, bot_gid in AGENT_BOT_USERS.items():
        if assignee_gid == bot_gid:
            dispatch_to_agent(
                source='asana',
                agent_id=agent_id,
                instruction=f"Work on this task: {task['name']}",
                context={
                    'task_gid': task_gid,
                    'task_name': task['name'],
                    'task_notes': task.get('notes', ''),
                    'task_custom_fields': task.get('custom_fields', []),
                    'trigger': 'assignment',
                }
            )
            break


def dispatch_to_agent(source, agent_id, instruction, context):
    """Send to Dispatch Router Lambda."""
    lambda_client = boto3.client('lambda')
    lambda_client.invoke(
        FunctionName='dispatch-router',
        InvocationType='Event',  # async
        Payload=json.dumps({
            'source': source,
            'agent_id': agent_id,
            'instruction': instruction,
            'context': context,
        })
    )
```

**Asana webhook registration** (per project):
```python
asana_client.webhooks.create_webhook({
    'resource': '<project_gid>',
    'target': 'https://<api-gateway-url>/asana-webhook',
    'filters': [
        {'resource_type': 'story', 'action': 'added'},    # comments
        {'resource_type': 'task', 'action': 'changed'},   # assignments + fields
    ]
})
```

### 4c. Slack — App Events API

Register a Slack app with `app_mention` event subscription and slash commands.

**Event trigger:**
```
User in #engineering: @uat run regression against staging
```

**Slash commands:**
```
/uat run regression --env staging
/workitems status --project myproject
/sentinel audit --pr 142
```

**Handler (Lambda via API Gateway):**

```python
def handle_slack_event(event):
    """Process Slack app_mention or slash command."""
    
    if event.get('type') == 'app_mention':
        text = event['text']
        # Text arrives as: "<@U12345BOT_ID> run regression against staging"
        # Strip the bot mention prefix
        instruction = re.sub(r'^<@\w+>\s*', '', text).strip()
        agent_id = resolve_agent_from_slack_bot_id(event['bot_id'])
        
    elif event.get('command'):
        # Slash command: /uat run regression --env staging
        agent_id = event['command'].lstrip('/')
        instruction = event['text']
    
    # Post acknowledgment immediately (Slack 3-second timeout)
    post_slack_message(
        channel=event['channel'],
        text=f"🏁 Got it. Dispatching to `{agent_id}`...",
        thread_ts=event.get('ts')  # reply in thread
    )
    
    # Dispatch async
    dispatch_to_agent(
        source='slack',
        agent_id=agent_id,
        instruction=instruction,
        context={
            'channel': event['channel'],
            'thread_ts': event.get('ts'),
            'requester': event['user'],
        }
    )
```

---

## 5. Dispatch Router — Central Routing Logic

The Dispatch Router is a single Lambda that all event sources feed into. It's the traffic cop.

```python
import json
import re
import time
import uuid
import boto3

dynamodb = boto3.resource('dynamodb')
assignments_table = dynamodb.Table('dispatch-assignments')
agentcore = boto3.client('bedrock-agentcore')

# Agent Registry: loaded from SSM Parameter Store or a config file
AGENT_REGISTRY = {
    'uat': {
        'runtime_id': 'arn:aws:bedrock-agentcore:us-west-2:ACCT:runtime/uat',
        'aliases': ['uat'],
        'description': 'UAT testing agent — generates and runs Playwright tests',
        'allowed_sources': ['github', 'asana', 'slack'],
        'allowed_users': ['*'],  # or specific usernames
        'max_concurrent': 5,
        'default_instruction_prefix': 'You are being invoked from {source}. ',
    },
    'workitems': {
        'runtime_id': 'arn:aws:bedrock-agentcore:us-west-2:ACCT:runtime/workitems',
        'aliases': [],
        'description': 'PO/PM agent — status reports, sync, risk detection',
        'allowed_sources': ['github', 'asana', 'slack'],
        'allowed_users': ['*'],
        'max_concurrent': 3,
        'default_instruction_prefix': 'You are being invoked from {source}. ',
    },
    'sentinel': {
        'runtime_id': 'arn:aws:bedrock-agentcore:us-west-2:ACCT:runtime/sentinel',
        'aliases': ['security'],
        'description': 'Security review agent',
        'allowed_sources': ['github', 'slack'],
        'allowed_users': ['josh', 'michelle'],  # restricted
        'max_concurrent': 2,
        'default_instruction_prefix': '',
    },
}

# Flatten aliases for lookup
ALIAS_MAP = {}
for agent_id, config in AGENT_REGISTRY.items():
    for alias in config.get('aliases', []):
        ALIAS_MAP[alias] = agent_id


def handler(event, context):
    """Central dispatch router."""
    
    source = event['source']  # github | asana | slack
    
    # --- Resolve agent ---
    agent_id = event.get('agent_id')
    if not agent_id:
        # Parse from body text
        body = event.get('body', '')
        agent_id = extract_agent_mention(body)
    
    if not agent_id:
        return post_error(event, "No agent mentioned. Available agents: " + 
                         ", ".join(f"@{a}" for a in AGENT_REGISTRY.keys()))
    
    agent_id = ALIAS_MAP.get(agent_id, agent_id)
    
    if agent_id not in AGENT_REGISTRY:
        return post_error(event, f"Unknown agent: @{agent_id}")
    
    agent_config = AGENT_REGISTRY[agent_id]
    
    # --- Authorization ---
    requester = event.get('sender') or event.get('context', {}).get('requester', 'unknown')
    if agent_config['allowed_users'] != ['*'] and requester not in agent_config['allowed_users']:
        return post_error(event, f"You are not authorized to invoke @{agent_id}.")
    
    if source not in agent_config['allowed_sources']:
        return post_error(event, f"@{agent_id} cannot be invoked from {source}.")
    
    # --- Concurrency check ---
    active = count_active_assignments(agent_id)
    if active >= agent_config['max_concurrent']:
        return post_error(event, 
            f"@{agent_id} is at capacity ({active}/{agent_config['max_concurrent']}). "
            "Try again in a few minutes.")
    
    # --- Build context payload ---
    instruction = event.get('instruction', '')
    if not instruction:
        instruction = extract_instruction_from_body(event.get('body', ''), agent_id)
    
    # Enrich instruction with source context
    enriched_instruction = build_enriched_instruction(
        agent_config, source, instruction, event
    )
    
    # --- Track assignment ---
    assignment_id = str(uuid.uuid4())
    assignments_table.put_item(Item={
        'assignment_id': assignment_id,
        'agent_id': agent_id,
        'source': source,
        'requester': requester,
        'instruction': instruction,
        'status': 'dispatched',
        'created_at': int(time.time()),
        'source_context': json.dumps(event.get('context', {})),
        'ttl': int(time.time()) + 86400 * 30,  # 30-day retention
    })
    
    # --- Post acknowledgment ---
    post_acknowledgment(event, agent_id, assignment_id)
    
    # --- Invoke AgentCore Runtime ---
    agentcore.invoke_agent(
        runtimeId=agent_config['runtime_id'],
        inputText=enriched_instruction,
        sessionId=assignment_id,
        # Pass callback info so agent knows where to post results
        sessionAttributes={
            'assignment_id': assignment_id,
            'callback_source': source,
            'callback_context': json.dumps(event.get('context', {})),
        }
    )
    
    return {'statusCode': 200, 'assignment_id': assignment_id}


def build_enriched_instruction(agent_config, source, instruction, event):
    """Build a rich instruction with context from the source platform."""
    
    prefix = agent_config['default_instruction_prefix'].format(source=source)
    
    context_parts = [prefix, instruction]
    
    # Add source-specific context
    if source == 'github':
        context_parts.append(f"\nGitHub repo: {event.get('repo')}")
        context_parts.append(f"Issue/PR: #{event.get('issue_number')}")
        
    elif source == 'asana':
        ctx = event.get('context', {})
        context_parts.append(f"\nAsana task: {ctx.get('task_name')}")
        if ctx.get('task_notes'):
            context_parts.append(f"Task description: {ctx['task_notes'][:2000]}")
        
    elif source == 'slack':
        ctx = event.get('context', {})
        context_parts.append(f"\nSlack channel: {ctx.get('channel')}")
    
    # Always include callback instruction
    context_parts.append(
        f"\n\nWhen complete, post your results back to {source}. "
        f"Assignment ID: {event.get('assignment_id', 'pending')}"
    )
    
    return '\n'.join(context_parts)


def extract_agent_mention(text):
    """Extract @agent mention from text."""
    match = re.search(
        r'@(claude|uat|uat|workitems|sentinel|docbot|security)\b',
        text, re.IGNORECASE
    )
    return match.group(1).lower() if match else None
```

---

## 6. Response Flow — Agents Post Results Back

Each agent includes a `post_results` tool that routes responses back to the originating platform.

```python
@tool
def post_results(
    assignment_id: str,
    summary: str,
    details: str = "",
    status: str = "completed",
    attachments: list = None
) -> str:
    """Post results back to the platform that requested this work.
    
    Args:
        assignment_id: The dispatch assignment ID from session attributes
        summary: One-line summary of what was done
        details: Full details (markdown supported)
        status: completed | failed | needs_review | blocked
        attachments: List of S3 URLs (screenshots, reports, etc.)
    """
    # Fetch assignment record to get callback info
    assignment = assignments_table.get_item(
        Key={'assignment_id': assignment_id}
    )['Item']
    
    source = assignment['callback_source']
    context = json.loads(assignment['source_context'])
    
    if source == 'github':
        post_github_comment(
            repo=context['repo'],
            issue_number=context['issue_number'],
            body=format_github_response(summary, details, status, attachments)
        )
        if status == 'completed':
            add_github_label(context['repo'], context['issue_number'], 'agent-complete')
    
    elif source == 'asana':
        post_asana_comment(
            task_gid=context['task_gid'],
            text=format_asana_response(summary, details, status, attachments)
        )
        if status == 'completed':
            update_asana_custom_field(context['task_gid'], 'Agent Status', 'Complete')
    
    elif source == 'slack':
        post_slack_message(
            channel=context['channel'],
            thread_ts=context.get('thread_ts'),
            text=format_slack_response(summary, details, status, attachments)
        )
    
    # Update assignment tracker
    assignments_table.update_item(
        Key={'assignment_id': assignment_id},
        UpdateExpression='SET #s = :status, completed_at = :ts, result_summary = :summary',
        ExpressionAttributeNames={'#s': 'status'},
        ExpressionAttributeValues={
            ':status': status,
            ':ts': int(time.time()),
            ':summary': summary,
        }
    )
    
    return f"Results posted to {source}"
```

---

## 7. Response Formatting Per Platform

### GitHub (Markdown with collapsible sections):
```markdown
## 🏁 Uat — Test Results

**Status:** ✅ 12 passed, ❌ 1 failed, ⚠️ 2 skipped

### Summary
Generated 15 Playwright tests from acceptance criteria. 12 pass on staging.

<details>
<summary>❌ Failed: test_content_search_returns_team_results</summary>

**Expected:** Search for "Team Alpha" returns content tagged with that team
**Actual:** Search returned 0 results (search index not refreshed on staging)
**Classification:** Environment issue — staging search index is stale

Screenshot: [failure.png](https://s3-link)
</details>

<details>
<summary>📝 Full Test Report</summary>

| Test | Status | Duration |
|------|--------|----------|
| test_login_flow | ✅ Pass | 2.3s |
| test_content_upload | ✅ Pass | 4.1s |
| test_content_search_returns_team_results | ❌ Fail | 8.2s |
| ... | ... | ... |
</details>

---
*Assignment: abc123 | Requested by @josh | Completed in 3m 42s*
```

### Asana (Plain text with structure):
```
🏁 Uat — Test Results
Status: ✅ 12 passed, ❌ 1 failed, ⚠️ 2 skipped

Generated 15 Playwright tests from this story's acceptance criteria.

Failed: test_content_search_returns_team_results
→ Search for "Team Alpha" returned 0 results
→ Classification: Environment issue (staging search index stale)
→ Not a code regression

Full report: https://s3-link/report.html
Screenshots: https://s3-link/screenshots/

Completed in 3m 42s
```

### Slack (Blocks with threading):
```
🏁 *Uat — Test Results*
✅ 12 passed  ❌ 1 failed  ⚠️ 2 skipped

1 failure classified as environment issue (not a regression).
Full report → <link|View Report>

_Thread replies contain detailed results._
```

---

## 8. Asana-Specific UX Enhancements

Since Asana doesn't have native bot mentions, we make the agent experience feel native:

### 8a. Bot User Accounts
Create dedicated Asana user accounts for each agent:
- **Uat Bot** (uat@yourdomain.com)
- **Workitems Bot** (workitems@yourdomain.com)

These appear in the Asana assignee dropdown. Assigning a task to "Uat Bot" triggers the agent — identical UX to assigning to a human.

### 8b. Custom Field: "Agent"
Add a single-select custom field to projects:
- Options: None, Uat, Workitems, Sentinel, Claude
- Changing this field triggers the webhook → dispatch

This integrates with **Asana Rules**: "When task moves to 'Ready for QA' section → set Agent field to Uat." Now your workflow automatically triggers UAT testing.

### 8c. Asana Rules Integration
```
Rule: When task moves to "Ready for QA"
  → Set custom field "Agent" to "Uat"
  → (Webhook fires → Dispatch Router → Uat agent runs tests)

Rule: When task moves to "Ready for Review"  
  → Set custom field "Agent" to "Workitems"
  → (Webhook fires → Dispatch Router → Workitems generates status update)
```

This means **zero @mention typing required** — just drag a task to a section and the agent picks it up.

### 8d. Asana Forms
For incoming requests, add an "Agent" field to Asana forms:
- "Should an AI agent work on this?" → Dropdown: None, Uat, Workitems
- Form submission creates a task with the field pre-set → agent auto-triggers

---

## 9. Agent-to-Agent Communication (A2A)

Agents can invoke each other. This is critical for workflow chains.

**Example: PR merged → test → report**
```
1. Developer merges PR
2. GitHub webhook triggers Dispatch Router
3. Dispatch routes to @uat: "PR #142 merged, run regression"
4. Uat runs tests, posts results to GitHub
5. Uat invokes @workitems via A2A: "Tests complete for PR #142, 
   update project status in Asana"
6. Workitems updates Asana task status and posts sprint metrics
```

**A2A invocation within an agent:**
```python
@tool
def invoke_agent(
    agent_id: str,
    instruction: str,
    wait_for_response: bool = False
) -> str:
    """Invoke another agent via A2A protocol.
    
    Args:
        agent_id: Target agent (e.g., 'workitems', 'uat')
        instruction: What to tell the other agent
        wait_for_response: Block until the other agent completes
    """
    agent_config = AGENT_REGISTRY[agent_id]
    
    response = agentcore.invoke_agent(
        runtimeId=agent_config['runtime_id'],
        inputText=instruction,
        sessionAttributes={
            'invoked_by': self.agent_id,
            'callback_source': 'a2a',
        }
    )
    
    if wait_for_response:
        return response['output']
    return f"Dispatched to @{agent_id}"
```

---

## 10. Configuration File (Repo-Level)

Store agent configuration in the repo so team members can modify it without code changes:

```yaml
# .dispatch/agents.yaml

agents:
  uat:
    description: "UAT testing — generates and runs Playwright tests"
    runtime_arn: "arn:aws:bedrock-agentcore:us-west-2:ACCT:runtime/uat"
    aliases: [uat, test]
    triggers:
      github: [issue_comment, pr_comment, assignment]
      asana: [comment, assignment, custom_field]
      slack: [mention, slash_command]
    authorization:
      users: []  # fails closed — populate before first use
      teams: ["engineering", "qa"]
    limits:
      max_concurrent: 5
      timeout_minutes: 30
    asana:
      bot_user_gid: "1234567890"
      custom_field_value: "Uat"
      auto_trigger_sections: ["Ready for QA"]

  workitems:
    description: "PO/PM — status reports, GitHub↔Asana sync, risk detection"
    runtime_arn: "arn:aws:bedrock-agentcore:us-west-2:ACCT:runtime/workitems"
    aliases: []
    triggers:
      github: [issue_comment]
      asana: [comment, assignment, custom_field]
      slack: [mention, slash_command]
    authorization:
      users: []  # fails closed — populate before first use
    limits:
      max_concurrent: 3
      timeout_minutes: 15
    asana:
      bot_user_gid: "1234567891"
      custom_field_value: "Workitems"
      auto_trigger_sections: ["Sprint Review"]

  sentinel:
    description: "Security review agent"
    runtime_arn: "arn:aws:bedrock-agentcore:us-west-2:ACCT:runtime/sentinel"
    aliases: [security]
    triggers:
      github: [pr_comment, assignment]
      asana: [comment]
      slack: [mention]
    authorization:
      users: [josh, michelle]  # restricted access
    limits:
      max_concurrent: 2
      timeout_minutes: 20

defaults:
  acknowledgment_emoji: "👀"  # react to the triggering comment
  result_format: "markdown"
  assignment_retention_days: 30
```

---

## 11. Observability & Audit

### Assignment Dashboard (CloudWatch)
- Assignments per agent per day
- Mean time to completion by agent
- Failure rate by agent
- Source distribution (how many from GitHub vs. Asana vs. Slack)
- Concurrency utilization (are agents hitting max_concurrent?)

### Audit Trail (DynamoDB)
Every assignment is tracked:
```json
{
  "assignment_id": "abc-123",
  "agent_id": "uat",
  "source": "asana",
  "trigger_type": "comment_mention",
  "requester": "josh",
  "instruction": "write E2E tests for content search",
  "status": "completed",
  "created_at": 1713100800,
  "completed_at": 1713101022,
  "duration_seconds": 222,
  "result_summary": "15 tests generated, 12 passed, 1 failed (env issue)",
  "token_usage": 45230,
  "cost_estimate_usd": 0.87
}
```

### Slack Digest (Daily)
Each morning, @workitems posts a team-visible summary:
```
📊 Agent Activity — Yesterday
• @uat: 8 assignments, 7 completed, 1 blocked
• @workitems: 3 assignments, 3 completed  
• @sentinel: 1 assignment, 1 completed
• @claude: 12 issues resolved (via GitHub Actions)

Total agent cost: $14.23
```

---

## 12. Implementation Sequence

| Phase | Scope | Weeks |
|-------|-------|-------|
| **1. Dispatch Router** | Lambda + DynamoDB + API Gateway. GitHub Actions workflow for non-claude agents. Hardcoded agent registry. | 1–2 |
| **2. GitHub integration** | @uat and @workitems working via GitHub issue/PR comments. Bot user accounts as assignees. Response posting. | 2–3 |
| **3. Asana webhooks** | Webhook receiver Lambda. Comment mention parsing. Bot user assignment trigger. | 3–4 |
| **4. Asana native UX** | Custom field trigger. Asana Rules integration. Form integration. | 4–5 |
| **5. Slack** | App registration. @mention + slash commands. Threaded responses. | 5–6 |
| **6. A2A chaining** | Agent-to-agent invocation. PR merge → test → report workflow. | 6–7 |
| **7. Config & observability** | `.dispatch/agents.yaml` config. CloudWatch dashboards. Daily digest. | 7–8 |
| **8. Self-service** | Any team member can register a new agent by adding to the config file. | 8 |
