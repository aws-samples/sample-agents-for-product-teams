# Researcher: Autonomous Business Analyst Agent
## Agent Specification on Amazon Bedrock AgentCore

> **Status: target design.** The shipping agent under `agents/researcher/` implements the core SYNTHESIZE / COMPETE / SPECIFY modes, with Tavily-backed web search for competitive intel. It uses **direct MCP connections** (not AgentCore Gateway) and **SSM Parameter Store** for credentials (not AgentCore Identity). Features in this spec that reference **Code Interpreter**, **analytics platform integrations** (PostHog/Mixpanel/Amplitude), or **shared Memory namespaces** are not wired up; they remain roadmap items. For current behavior, read `agents/researcher/prompts.py` and the code under `agents/researcher/tools/`.

---

## 1. What This Agent Does

Researcher is an autonomous business analyst agent that bridges the gap between raw signals (customer feedback, usage data, competitor moves, market trends) and actionable product decisions (prioritized requirements, user stories with acceptance criteria, impact estimates). It does the analytical heavy lifting so the Product Owner makes faster, better-informed decisions.

**Core Capabilities:**

- **Research synthesis**: Ingests interview transcripts, survey responses, support tickets, and app reviews — extracts themes, pain points, and opportunities into structured findings
- **Competitive intelligence**: Monitors competitor products, features, and positioning. Maintains a living competitive landscape document
- **Requirements drafting**: Translates research findings into user stories with acceptance criteria, edge cases, and dependencies
- **Spec review**: Reads existing PRDs, user stories, and issue descriptions — identifies ambiguities, missing acceptance criteria, untestable conditions, and unstated assumptions
- **Backlog analysis**: Finds duplicate issues, gaps in coverage, orphaned stories, and prioritization inconsistencies
- **Impact estimation**: Pulls usage analytics and combines with qualitative research to size feature impact using RICE or custom frameworks
- **Market sizing**: Analyzes addressable market segments, pricing data, and adoption patterns using Code Interpreter for quantitative modeling

**What it does NOT do:**
- Make final prioritization decisions — it presents options with trade-offs, the PO decides
- Talk to customers — research collection is human work, synthesis is Researcher's work
- Approve requirements — it drafts and reviews, humans sign off

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                       AgentCore Runtime                              │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                Strands Agent — Researcher                        │  │
│  │                                                               │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌────────────────────┐  │  │
│  │  │ Researcher   │  │ Analyst      │  │ Spec Writer        │  │  │
│  │  │ (synthesize  │  │ (data crunch,│  │ (user stories,     │  │  │
│  │  │  qualitative │  │  RICE score, │  │  acceptance crit,  │  │  │
│  │  │  inputs)     │  │  backlog     │  │  PRDs, gap         │  │  │
│  │  │              │  │  analysis)   │  │  analysis)         │  │  │
│  │  └──────┬───────┘  └──────┬───────┘  └─────────┬──────────┘  │  │
│  │         └─────────────────┼─────────────────────┘             │  │
│  │                           │                                   │  │
│  │                    ┌──────┴──────┐                            │  │
│  │                    │ Tool Layer  │                            │  │
│  └────────────────────┼─────────────┼────────────────────────────┘  │
│                       │             │                               │
│  ┌────────────────────┼─────────────┼────────────────────────────┐  │
│  │                    │             │                             │  │
│  │  ┌────────────────┐│  ┌──────────┴───────┐  ┌─────────────┐  │  │
│  │  │ AgentCore      ││  │ AgentCore        │  │ Bedrock     │  │  │
│  │  │ Gateway (MCP)  ││  │ Code Interpreter │  │ Web Search  │  │  │
│  │  │                ││  │                  │  │ (tool)      │  │  │
│  │  │ ┌──────┐       ││  │ pandas, numpy    │  │             │  │  │
│  │  │ │GitHub│       ││  │ matplotlib       │  │ Competitive │  │  │
│  │  │ └──────┘       ││  │ scipy, sklearn   │  │ monitoring  │  │  │
│  │  │ ┌──────┐       ││  │                  │  │ Market data │  │  │
│  │  │ │Asana │       ││  │ Survey analysis  │  │ Trend       │  │  │
│  │  │ └──────┘       ││  │ RICE scoring     │  │ research    │  │  │
│  │  │ ┌──────┐       ││  │ Cohort analysis  │  │             │  │  │
│  │  │ │Slack │       ││  │ Visualizations   │  └─────────────┘  │  │
│  │  │ └──────┘       ││  └──────────────────┘                   │  │
│  │  └────────────────┘│                                          │  │
│  └────────────────────┼──────────────────────────────────────────┘  │
│                       │                                             │
│  ┌────────────────────┼──────────────────────────────────────────┐  │
│  │                    │                                          │  │
│  │  ┌─────────────┐  │  ┌──────────────┐  ┌──────────────────┐  │  │
│  │  │ AgentCore   │  │  │ AgentCore    │  │ S3 Bucket:       │  │  │
│  │  │ Memory      │  │  │ Identity     │  │ researcher-data     │  │  │
│  │  │             │  │  │              │  │                  │  │  │
│  │  │ • Domain    │  │  │ • GitHub     │  │ /research/       │  │  │
│  │  │   knowledge │  │  │ • Asana      │  │ /competitive/    │  │  │
│  │  │ • Personas  │  │  │ • Slack      │  │ /analytics/      │  │  │
│  │  │ • Competitor│  │  │ • Analytics  │  │ /reports/         │  │  │
│  │  │   landscape │  │  │   (PostHog)  │  │ /visualizations/ │  │  │
│  │  │ • Research  │  │  │              │  │                  │  │  │
│  │  │   history   │  │  │              │  │                  │  │  │
│  │  └─────────────┘  │  └──────────────┘  └──────────────────┘  │  │
│  │                    │                                          │  │
│  │  ┌─────────────┐  │  ┌──────────────┐                        │  │
│  │  │ AgentCore   │  │  │ AgentCore    │                        │  │
│  │  │ Policy      │  │  │ Observability│                        │  │
│  │  └─────────────┘  │  └──────────────┘                        │  │
│  └────────────────────┴──────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. AgentCore Services Breakdown

### 3a. AgentCore Code Interpreter — Quantitative Analysis Engine

This is Researcher's distinguishing capability versus Workitems agent. Where Workitems reports on what happened, Researcher analyzes *why* it matters and *what to do about it*.

**Use cases:**

**Survey & feedback analysis:**
```python
# Agent generates and executes this in Code Interpreter
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.cluster import KMeans

# Load survey responses (uploaded to sandbox)
df = pd.read_csv('/tmp/survey_responses.csv')

# Cluster open-ended responses into themes
vectorizer = TfidfVectorizer(max_features=500, stop_words='english')
X = vectorizer.fit_transform(df['feedback_text'])
clusters = KMeans(n_clusters=6, random_state=42).fit(X)

# Extract top terms per cluster as theme labels
for i in range(6):
    center = clusters.cluster_centers_[i]
    top_terms = [vectorizer.get_feature_names_out()[j] 
                 for j in center.argsort()[-5:]]
    print(f"Theme {i}: {', '.join(top_terms)}")
    print(f"  Count: {(clusters.labels_ == i).sum()}")
```

**RICE scoring:**
```python
# Agent computes RICE scores for backlog items
import pandas as pd

backlog = pd.DataFrame([
    {'feature': 'Content tagging by team', 'reach': 500, 
     'impact': 3, 'confidence': 0.8, 'effort_weeks': 4},
    {'feature': 'Real-time notifications', 'reach': 300, 
     'impact': 2, 'confidence': 0.9, 'effort_weeks': 2},
    # ... loaded from Asana export
])

backlog['rice_score'] = (
    backlog['reach'] * backlog['impact'] * backlog['confidence'] 
    / backlog['effort_weeks']
)
backlog = backlog.sort_values('rice_score', ascending=False)
```

**Usage analytics:**
```python
# Cohort analysis from analytics export
import pandas as pd
import matplotlib.pyplot as plt

events = pd.read_csv('/tmp/posthog_export.csv')
events['date'] = pd.to_datetime(events['timestamp']).dt.date
events['cohort_week'] = pd.to_datetime(events['first_seen']).dt.isocalendar().week

# Retention matrix
retention = events.pivot_table(
    index='cohort_week', columns='weeks_since_first', 
    values='user_id', aggfunc='nunique'
)
retention_pct = retention.div(retention.iloc[:, 0], axis=0)

# Generate heatmap visualization
fig, ax = plt.subplots(figsize=(12, 8))
ax.imshow(retention_pct.values, cmap='YlGn', aspect='auto')
plt.savefig('/tmp/retention_heatmap.png')
```

**Competitive pricing analysis:**
```python
# Compare feature sets and pricing across competitors
competitors = pd.DataFrame([
    {'name': 'Competitor A', 'price': 49, 'search': True, 
     'team_tagging': True, 'api_access': False},
    {'name': 'Competitor B', 'price': 99, 'search': True, 
     'team_tagging': False, 'api_access': True},
    {'name': 'Our App', 'price': 39, 'search': True, 
     'team_tagging': True, 'api_access': True},
])
# Feature parity scoring, price positioning analysis
```

### 3b. Bedrock Web Search Tool — Competitive & Market Intelligence

Researcher uses Bedrock's built-in web search tool for real-time competitive monitoring and market research. This runs inside the agent's reasoning loop, not as a separate service.

**Competitive monitoring tasks:**
- Search for competitor product announcements, feature launches, pricing changes
- Monitor industry forums and communities for unmet needs
- Track industry publications for market trend data
- Research analogous products in adjacent markets (other content platforms)

**Configuration in agent:**
```python
from strands import Agent
from strands.models import BedrockModel

agent = Agent(
    model=BedrockModel(model_id="us.anthropic.claude-sonnet-4-6-v1"),
    system_prompt=SYSTEM_PROMPT,
    tools=[
        *gateway_tools,           # GitHub, Asana, Slack
        execute_python,           # Code Interpreter
        {"type": "web_search_20250305", "name": "web_search"},  # Bedrock web search
        # ... custom tools
    ]
)
```

### 3c. AgentCore Gateway — Project Data Access

Same unified MCP endpoint pattern. Researcher's tool surface:

**GitHub Tools:**
- `github_list_issues` — read backlog, filter by label/milestone
- `github_get_issue` — full issue with comments for spec review
- `github_create_issue` — create user stories from research findings
- `github_update_issue` — add acceptance criteria, labels, estimates
- `github_add_comment` — post spec review findings
- `github_search_issues` — find duplicates, related items

**Asana Tools:**
- `asana_list_tasks` — read project backlog with custom fields
- `asana_get_task` — full task detail with subtasks and history
- `asana_create_task` — create requirements from research synthesis
- `asana_update_task` — add acceptance criteria, RICE scores, priority
- `asana_add_comment` — post analysis results
- `asana_search` — find related requirements across projects
- `asana_get_project` — project-level context and status

**Slack Tools:**
- `slack_post_message` — share findings and reports
- `slack_upload_file` — share visualizations, research summaries
- `slack_search_messages` — mine Slack for product feedback signals

### 3d. AgentCore Memory — Domain Intelligence

Researcher's memory is its most strategic asset. Over time it builds a deep understanding of the product domain, users, and market.

**Semantic Memory: Domain Knowledge**
The agent accumulates understanding of the SaaS content platform domain:
- How teams operate and consume content
- Technical vocabulary (product categories, use cases, segment names)
- Integration ecosystem (upstream systems, data sources, distribution channels)
- Partner and compliance context (Partner A, Partner B, Partner C requirements)

**Semantic Memory: User Personas**
Stores and refines user personas from research:
- Admin user persona: goals, pain points, workflow patterns
- Team lead persona: different content consumption needs
- Individual user persona: budget constraints, self-service requirements

**Semantic Memory: Competitive Landscape**
Maintained across runs:
- Feature matrices per competitor (updated on each competitive scan)
- Pricing history and positioning
- Competitor strengths/weaknesses
- White space opportunities identified

**Semantic Memory: Research Archive**
Historical research findings persist:
- Past interview themes and their frequency over time
- Feature request trends (growing, stable, declining)
- Previously identified opportunities and their outcomes

```python
memory = client.create_memory_and_wait(
    name="LookoutMemory",
    description="Domain knowledge, personas, competitive intel, research history",
    strategies=[
        {"semanticMemoryStrategy": {
            "name": "DomainKnowledge",
            "namespaceTemplates": ["/domain/{topic}"]
        }},
        {"semanticMemoryStrategy": {
            "name": "UserPersonas",
            "namespaceTemplates": ["/personas/{persona_id}"]
        }},
        {"semanticMemoryStrategy": {
            "name": "CompetitiveLandscape",
            "namespaceTemplates": ["/competitors/{competitor_id}"]
        }},
        {"semanticMemoryStrategy": {
            "name": "ResearchArchive",
            "namespaceTemplates": ["/research/{study_id}"]
        }},
        {"summaryMemoryStrategy": {
            "name": "RunSummaries",
            "namespaceTemplates": ["/runs/{date}"]
        }},
        {"userPreferenceMemoryStrategy": {
            "name": "TeamPreferences",
            "namespaceTemplates": ["/preferences"]
        }}
    ]
)
```

### 3e. AgentCore Identity

**GitHub OAuth2**: Read issues/PRs, create/update issues, post comments
**Asana OAuth2**: Read/write tasks, post comments, access custom fields
**Slack OAuth2**: Post messages, upload files, search messages

**Optional — Analytics platform** (if API is used):
PostHog or Mixpanel OAuth/API key stored in Identity token vault. Allows Researcher to pull usage data directly rather than requiring CSV exports.

### 3f. AgentCore Policy

```cedar
// Researcher can read broadly across both systems
permit(
    principal == AgentCore::Agent::"Researcher",
    action == AgentCore::Action::"InvokeTool",
    resource
) when {
    resource.toolName.startsWith("github_get_") ||
    resource.toolName.startsWith("github_list_") ||
    resource.toolName.startsWith("github_search_") ||
    resource.toolName.startsWith("asana_get_") ||
    resource.toolName.startsWith("asana_list_") ||
    resource.toolName.startsWith("asana_search_") ||
    resource.toolName.startsWith("slack_search_")
};

// Researcher can create and update requirements
permit(
    principal == AgentCore::Agent::"Researcher",
    action == AgentCore::Action::"InvokeTool",
    resource
) when {
    resource.toolName == "github_create_issue" ||
    resource.toolName == "github_update_issue" ||
    resource.toolName == "github_add_comment" ||
    resource.toolName == "github_add_label" ||
    resource.toolName == "asana_create_task" ||
    resource.toolName == "asana_update_task" ||
    resource.toolName == "asana_add_comment" ||
    resource.toolName == "slack_post_message" ||
    resource.toolName == "slack_upload_file" ||
    resource.toolName == "web_search"
};

// Researcher CANNOT close/delete/merge anything
forbid(
    principal == AgentCore::Agent::"Researcher",
    action == AgentCore::Action::"InvokeTool",
    resource
) when {
    resource.toolName == "github_close_issue" ||
    resource.toolName == "github_merge_pr" ||
    resource.toolName == "github_delete_branch" ||
    resource.toolName == "asana_delete_task" ||
    resource.toolName == "asana_complete_task"
};

// Researcher can use Code Interpreter and Web Search
permit(
    principal == AgentCore::Agent::"Researcher",
    action == AgentCore::Action::"ExecuteCode",
    resource
);
```

---

## 4. Agent Implementation

### 4a. System Prompt

```python
SYSTEM_PROMPT = """You are Researcher, an autonomous business analyst agent for a 
SaaS content platform that helps teams discover and organize content relevant 
to their operations.

Your users are teams — from small teams (Partner A, Partner B customers) to 
mid-market (Partner C and similar) to enterprise. They range from individual 
users to multi-team organizations with dedicated administrators.

You have five operating modes:

1. SYNTHESIZE — Process raw research inputs (transcripts, surveys, tickets,
   reviews) into structured findings with themes, severity, and frequency.
   Always use Code Interpreter for quantitative analysis.

2. COMPETE — Monitor and analyze the competitive landscape. Search the web 
   for competitor updates. Maintain the competitive matrix in memory.
   Identify positioning opportunities and threats.

3. SPECIFY — Draft user stories with acceptance criteria from research 
   findings or product direction. Review existing specs for completeness.
   Every story must have: clear persona, goal, acceptance criteria with
   testable conditions, edge cases, and dependencies.

4. PRIORITIZE — Analyze the backlog quantitatively. Compute RICE scores
   using Code Interpreter. Identify duplicates, gaps, and conflicts.
   Present prioritization options with trade-offs — never a single answer.

5. SIZE — Estimate feature impact by combining usage analytics with 
   qualitative research. Model adoption curves, TAM segments, and 
   revenue impact using Code Interpreter.

Rules:
- Present multiple options with trade-offs. Never prescribe a single path.
- Quantify everything possible. Use Code Interpreter for all calculations.
- Cite your sources. If from research, say which study. If from data, show
  the query. If from web search, link the source.
- Flag confidence levels explicitly: high/medium/low with reasoning.
- When creating user stories, follow the team's conventions from memory.
- All created issues/tasks get labeled 'researcher-generated' for tracking.
- When reviewing specs, be constructive. Identify problems AND suggest fixes.
"""
```

### 4b. Custom Tools

```python
@tool
def synthesize_research(
    input_type: str,
    s3_path: str = None,
    text_content: str = None,
    output_format: str = "structured"
) -> dict:
    """Synthesize qualitative research into structured findings.
    
    Args:
        input_type: One of 'transcript', 'survey', 'support_tickets', 
                    'app_reviews', 'slack_thread'
        s3_path: S3 path to input file (CSV, JSON, or plain text)
        text_content: Raw text input (for smaller inputs)
        output_format: 'structured' (JSON findings), 'narrative' (prose), 
                       'user_stories' (ready-to-file stories)
    
    Returns:
        Structured findings with themes, quotes, severity, frequency,
        and recommended actions.
    """
    pass  # LLM orchestrates: load data → Code Interpreter for 
          # quantitative clustering → synthesize themes → format output


@tool
def competitive_scan(
    competitors: list = None,
    focus_areas: list = None,
    depth: str = "standard"
) -> dict:
    """Run a competitive intelligence scan using web search.
    
    Args:
        competitors: List of competitor names/URLs. If None, uses 
                     known competitors from memory.
        focus_areas: Specific areas to investigate (e.g., 'pricing', 
                     'new features', 'partnerships')
        depth: 'quick' (headlines only), 'standard' (feature comparison),
               'deep' (full analysis with positioning recommendations)
    
    Returns:
        Competitive landscape update with changes since last scan,
        feature matrix, and strategic recommendations.
    """
    pass  # LLM orchestrates: recall competitors from memory → 
          # web_search each → compare to stored landscape → 
          # identify changes → update memory → return findings


@tool
def review_spec(
    source: str,
    identifier: str
) -> dict:
    """Review a user story or PRD for completeness and quality.
    
    Args:
        source: 'github' or 'asana'
        identifier: Issue number (GitHub) or task GID (Asana)
    
    Returns:
        Review with: completeness score, identified gaps, ambiguities,
        untestable conditions, missing edge cases, and suggested 
        improvements.
    """
    pass  # LLM orchestrates: fetch spec → analyze against checklist →
          # compare to similar past specs in memory → generate review


@tool  
def analyze_backlog(
    project: str,
    analysis_type: str = "full"
) -> dict:
    """Analyze the product backlog for quality and prioritization.
    
    Args:
        project: GitHub repo or Asana project identifier
        analysis_type: 
          'duplicates' — find duplicate/overlapping issues
          'gaps' — identify missing stories for known features
          'priority' — compute RICE scores and suggest ordering
          'health' — overall backlog health report
          'full' — all of the above
    
    Returns:
        Analysis results with specific actionable recommendations.
    """
    pass  # LLM orchestrates: fetch all issues → Code Interpreter for 
          # TF-IDF similarity (duplicates) → gap analysis against 
          # feature map → RICE computation → health metrics


@tool
def draft_user_stories(
    input_source: str,
    context: str = "",
    count: int = None
) -> list:
    """Generate user stories from research findings or direction.
    
    Args:
        input_source: Description of what to write stories for.
                      Can reference research findings, competitive gaps,
                      or product direction.
        context: Additional context (feature area, target persona, etc.)
        count: Max stories to generate. If None, generates as many 
               as the input warrants.
    
    Returns:
        List of user stories, each with: title, persona, goal, 
        acceptance criteria, edge cases, dependencies, RICE estimate,
        and suggested labels.
    """
    pass  # LLM orchestrates: interpret input → recall domain knowledge
          # and personas from memory → draft stories following team 
          # conventions → estimate RICE using Code Interpreter


@tool
def estimate_impact(
    feature_description: str,
    analytics_data_path: str = None,
    methodology: str = "rice"
) -> dict:
    """Estimate the impact of a proposed feature.
    
    Args:
        feature_description: What the feature does
        analytics_data_path: S3 path to usage data export (optional)
        methodology: 'rice', 'ice', 'wsjf', 'custom'
    
    Returns:
        Impact estimate with: quantitative score, confidence level,
        supporting data, assumptions, and sensitivity analysis.
    """
    pass  # LLM orchestrates: web_search for market context → 
          # Code Interpreter for quantitative modeling → 
          # combine with qualitative assessment → present with 
          # confidence intervals
```

---

## 5. Invocation Patterns

### 5a. Via Dispatch (@researcher mentions)

```
GitHub:  @researcher review this spec for completeness
Asana:   @researcher draft user stories from the Q3 research findings  
Slack:   @researcher what are our competitors doing with AI content tagging?
```

### 5b. Scheduled (EventBridge)

```
Weekly (Monday 6am):
  → "Run competitive scan for all tracked competitors. 
     Post summary to #product-intel Slack channel."

Bi-weekly (Friday 3pm):
  → "Analyze backlog health for the main project. 
     Post report to Asana project status."

Monthly (1st of month):
  → "Generate monthly product intelligence brief: 
     competitive changes, feature request trends, 
     backlog health trajectory. Post to #leadership."
```

### 5c. Event-Driven

```
GitHub issue labeled 'needs-spec-review':
  → Researcher reviews the issue and posts findings as a comment

Asana task moved to 'Needs Requirements':
  → Researcher reads the task and drafts acceptance criteria

New support tickets batch (daily):
  → Researcher synthesizes themes from yesterday's tickets
```

### 5d. Agent-to-Agent (A2A)

```
Workitems detects 5 stale issues in the same feature area:
  → Workitems invokes Researcher: "Analyze these 5 stale issues. 
     Are they duplicates? Should they be consolidated?"

Uat finds recurring test failures in search:
  → Uat invokes Researcher: "Search tests fail 
     frequently. Research whether the acceptance criteria 
     are correct or need revision."

Researcher drafts user stories:
  → Researcher invokes Workitems: "I've created 8 new stories in 
     the backlog. Update the sprint plan and notify the team."
```

---

## 6. Input/Output Formats

### 6a. Research Synthesis Output

```json
{
  "study_id": "research-2026-q2-interviews",
  "input_type": "transcript",
  "sample_size": 12,
  "themes": [
    {
      "name": "Content discovery is too slow",
      "frequency": 9,
      "severity": "high",
      "representative_quotes": [
        "I spend 30 minutes after every session just scrolling..."
      ],
      "affected_personas": ["admin_user", "individual_user"],
      "suggested_action": "Improve search relevance and add notification for new content matching team profile",
      "related_backlog_items": ["#142", "#167"]
    }
  ],
  "insights": [
    "Enterprise teams consume 3x more content than small teams",
    "83% of interviewees check competitor content within 24h of an event"
  ],
  "recommended_stories": [
    {
      "title": "As an admin, I want to be notified when new content featuring my entity is posted",
      "acceptance_criteria": [
        "Given my team profile includes item #47 in the Partner A segment",
        "When new content is posted from a Partner A event I attended",
        "And the content references item #47",
        "Then I receive a push notification within 1 hour of upload"
      ],
      "edge_cases": [
        "Entity identifier partially obscured",
        "Multiple entities with same identifier across different segments",
        "Content from different event types"
      ],
      "rice_estimate": {"reach": 450, "impact": 3, "confidence": 0.85, "effort_weeks": 6, "score": 191}
    }
  ],
  "confidence": "high",
  "methodology_notes": "12 semi-structured interviews, 45min avg, thematic analysis via TF-IDF clustering + manual review"
}
```

### 6b. Spec Review Output

```markdown
## Spec Review: #142 — Search by Team Name

**Completeness Score: 6/10**

### Missing Acceptance Criteria
- No criteria for partial matches ("Team Alph" → "Team Alpha")
- No criteria for case sensitivity
- No criteria for teams with special characters ("O'Brien & Associates")
- No performance requirement (search should return in < Xs)

### Ambiguities
- "relevant results" — what defines relevance? By recency? By match confidence? 
  Suggest: "results sorted by match confidence score, descending"
- "team name" — does this include abbreviations? Nicknames? 
  The team "Acme Corp" might also appear as "Acme Inc"

### Untestable Conditions
- "good user experience" in AC #4 — replace with measurable criteria
  Suggest: "search results page loads within 2 seconds with up to 50 results"

### Missing Edge Cases
- Zero results state (what does the user see?)
- Very common team names with many matches (pagination?)
- Deleted/private content appearing in search results

### Dependencies Not Listed
- Requires: content metadata indexing pipeline (#89)
- Requires: team profile creation flow (#103)
- Blocked by: search infrastructure migration (#118)

### Suggested Revised Acceptance Criteria
1. Given a user searches for "Team Alpha"...
[full rewrite provided]
```

### 6c. Competitive Brief

```markdown
## Competitive Intelligence Brief — April 2026

### Changes Since Last Scan (March 2026)

**Competitor A (RivalApp)**
- NEW: Launched AI-powered content classification (beta)
- PRICING: Raised team plan from $49 → $59/mo
- SIGNAL: Job posting for "ML Engineer" suggests 
  doubling down on auto-tagging

**Competitor B (AltPlatform)**  
- NEW: Partnership with Partner A for official content hosting
- RISK: This could lock us out of a key content source
- OPPORTUNITY: Their product still lacks team-level notifications

### Feature Matrix Update
[table comparing features across competitors]

### Strategic Recommendations
1. URGENT: Monitor the AltPlatform/Partner A partnership. If exclusive,
   we need an alternative content acquisition strategy.
2. DIFFERENTIATE: Our notification system is still unique. Double down
   with per-segment alerts, not just per-item.
3. PRICE: Competitor A's price increase gives us room. Hold current 
   pricing to capture switchers.

### Confidence: Medium
Competitor A's beta feature is self-reported; no independent verification.
AltPlatform partnership terms are unknown — may be non-exclusive.
```

---

## 7. Integration with Analytics Platform

For production use, Researcher should pull usage data directly rather than requiring CSV exports.

**PostHog Integration (via API key in AgentCore Identity):**

```python
@tool
def query_analytics(
    query_type: str,
    parameters: dict
) -> dict:
    """Query the analytics platform for usage data.
    
    Args:
        query_type: One of 'events', 'funnel', 'retention', 
                    'trends', 'persons'
        parameters: Query-specific parameters matching PostHog API
    
    Returns:
        Raw analytics data for further analysis in Code Interpreter.
    """
    # Uses PostHog API via requests library
    # API key retrieved from AgentCore Identity token vault
    headers = {"Authorization": f"Bearer {posthog_api_key}"}
    response = requests.get(
        f"https://app.posthog.com/api/projects/{project_id}/{query_type}/",
        headers=headers,
        params=parameters
    )
    return response.json()
```

This enables queries like:
- "How many teams used search in the last 30 days?"
- "What's the conversion rate from search → content view → share?"
- "Which features have declining usage?"

The agent pulls the data, runs it through Code Interpreter for analysis, and incorporates findings into its recommendations.

---

## 8. Data Flow

```
Raw Signals                    Researcher Processing              Outputs
────────────                   ──────────────────              ───────

Interview transcripts  ──┐
Survey responses       ──┤     ┌──────────────────┐
Support tickets        ──┼────►│ SYNTHESIZE        │──► Research findings
App store reviews      ──┤     │ (NLP clustering,  │    (themes, severity,
Slack feedback         ──┘     │  theme extraction) │    quotes, actions)
                               └────────┬─────────┘
                                        │
Competitor websites    ──┐              │
Industry news          ──┼────►┌────────┴─────────┐
Market reports         ──┘     │ COMPETE           │──► Competitive brief
                               │ (web search,      │    (changes, matrix,
                               │  comparison)      │    recommendations)
                               └────────┬─────────┘
                                        │
Research findings      ──┐              │
Product direction      ──┼────►┌────────┴─────────┐
Competitive gaps       ──┘     │ SPECIFY           │──► User stories
                               │ (story drafting,  │    (with AC, edge
                               │  spec review)     │    cases, deps)
                               └────────┬─────────┘
                                        │
Backlog (GitHub/Asana) ──┐              │
Usage analytics        ──┼────►┌────────┴─────────┐
RICE parameters        ──┘     │ PRIORITIZE / SIZE │──► Decision packages
                               │ (Code Interpreter │    (options with
                               │  quantitative     │    trade-offs,
                               │  modeling)        │    visualizations)
                               └───────────────────┘
```

---

## 9. Implementation Phases

| Phase | Scope | Weeks |
|-------|-------|-------|
| **1. Foundation** | Deploy Strands agent to AgentCore Runtime. Gateway access to GitHub + Asana (read-only). Web search tool enabled. Memory initialized with domain knowledge. | 1–2 |
| **2. Spec Review** | `review_spec` tool working. Triggered by `@researcher` mention and `needs-spec-review` label in GitHub. Posts review findings as comments. | 3–4 |
| **3. Research Synthesis** | Code Interpreter integration. `synthesize_research` tool with S3 input. Support for transcripts, surveys, and ticket CSVs. | 4–5 |
| **4. Competitive Intel** | `competitive_scan` using web search. Scheduled weekly runs. Competitive landscape stored in memory. Brief posted to Slack. | 5–6 |
| **5. Story Drafting** | `draft_user_stories` tool. Creates issues in GitHub / tasks in Asana with full AC. `researcher-generated` label applied. | 6–7 |
| **6. Backlog Analysis** | `analyze_backlog` tool with duplicate detection, gap analysis, RICE scoring via Code Interpreter. | 7–8 |
| **7. Analytics Integration** | PostHog/Mixpanel API connection via AgentCore Identity. `query_analytics` tool. Impact estimation with real usage data. | 8–9 |
| **8. A2A + Polish** | Agent-to-agent workflows with Workitems and Uat. Prompt tuning. Eval suite. Full Dispatch integration. | 9–10 |

---

## 10. What This Enables

| Before Researcher | After Researcher |
|----------------|---------------|
| Research findings sit in Google Docs for weeks before becoming stories | Findings are synthesized and user stories drafted within hours of transcript upload |
| Competitive monitoring happens when someone remembers to check | Weekly automated scans with change detection and strategic alerts |
| Specs go to dev with missing acceptance criteria, discovered during implementation | Every spec gets an automated review before entering development |
| RICE scores are gut-feel estimates in a spreadsheet | Quantitative scoring using real usage data from analytics platform |
| Backlog grows organically with duplicates and gaps nobody notices | Monthly backlog health reports with specific cleanup recommendations |
| Product decisions wait for someone to compile data from 5 different tools | Decision packages assembled automatically: data, context, options, trade-offs |
| The PO spends 60% of their time on analysis and 40% on decisions | The PO spends 20% reviewing Researcher's analysis and 80% on decisions |
