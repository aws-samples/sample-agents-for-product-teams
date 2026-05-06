# Docwriter: Autonomous Technical Writer Agent
## Agent Specification on Amazon Bedrock AgentCore

> **Status: target design.** The shipping agent under `agents/docwriter/` implements the core capabilities — API doc generation, release notes, doc PRs, gap detection, freshness checks — but uses **direct MCP connections** (not AgentCore Gateway) and **SSM Parameter Store** for credentials (not AgentCore Identity). AgentCore **Browser** and **Code Interpreter** features described in this spec are not wired up; they remain roadmap items. For current behavior, read `agents/docwriter/prompts.py` and the code under `agents/docwriter/tools/`.

---

## 1. What This Agent Does

Docwriter is an autonomous technical writer agent that keeps documentation in sync with the codebase, generates user-facing guides from features, maintains API docs, and ensures the team never ships a feature without documentation.

**Core Capabilities:**
- **API doc generation**: Reads OpenAPI specs, code comments, and route handlers — produces and maintains API reference documentation
- **User guide authoring**: Translates shipped features into end-user documentation with screenshots and step-by-step flows
- **Changelog & release notes**: Auto-generates changelogs from merged PRs, categorized by type (feature, fix, breaking change, internal)
- **Doc gap detection**: Scans the codebase for undocumented endpoints, components, and features — files issues for missing docs
- **Doc maintenance**: When PRs change behavior, identifies affected docs and updates them or flags staleness
- **README management**: Keeps repo READMEs, setup guides, and onboarding docs current as infrastructure evolves
- **Style enforcement**: Reviews doc PRs against a team style guide (tone, terminology, structure)

**What it does NOT do:**
- Write marketing copy or sales collateral (that's Researcher's territory)
- Generate architectural decision records (the developer writes the reasoning, Docwriter formats and files)
- Approve doc changes — it drafts, humans review

---

## 2. Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                       AgentCore Runtime                              │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │              Strands Agent — Docwriter                           │  │
│  │                                                                │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌─────────────────────┐  │  │
│  │  │ API Doc      │  │ Guide Writer │  │ Doc Maintenance     │  │  │
│  │  │ Generator    │  │ (user-facing │  │ (staleness detect,  │  │  │
│  │  │ (OpenAPI →   │  │  guides from │  │  PR-triggered       │  │  │
│  │  │  reference)  │  │  features)   │  │  updates)           │  │  │
│  │  └──────┬───────┘  └──────┬───────┘  └──────────┬──────────┘  │  │
│  │         └─────────────────┼──────────────────────┘             │  │
│  │                           │                                    │  │
│  │  ┌────────────────┐  ┌───┴────────────┐  ┌─────────────────┐  │  │
│  │  │ AgentCore      │  │ AgentCore      │  │ AgentCore       │  │  │
│  │  │ Gateway (MCP)  │  │ Browser        │  │ Code Interpreter│  │  │
│  │  │                │  │ (screenshot    │  │ (OpenAPI parse, │  │  │
│  │  │ ┌──────┐       │  │  capture for   │  │  doc validation,│  │  │
│  │  │ │GitHub│       │  │  user guides)  │  │  link checking) │  │  │
│  │  │ └──────┘       │  │                │  │                 │  │  │
│  │  │ ┌──────┐       │  └────────────────┘  └─────────────────┘  │  │
│  │  │ │Asana │       │                                           │  │
│  │  │ └──────┘       │  ┌─────────────────────────────────────┐  │  │
│  │  │ ┌──────┐       │  │ AgentCore Memory                   │  │  │
│  │  │ │Slack │       │  │ • Style guide & terminology         │  │  │
│  │  │ └──────┘       │  │ • Doc inventory (what exists where) │  │  │
│  │  └────────────────┘  │ • Feature→doc mapping               │  │  │
│  │                      │ • Audience profiles                 │  │  │
│  │  ┌────────────┐      └─────────────────────────────────────┘  │  │
│  │  │ AgentCore  │                                               │  │
│  │  │ Identity   │  ┌──────────────┐  ┌────────────────────┐     │  │
│  │  │ (GitHub,   │  │ AgentCore    │  │ AgentCore          │     │  │
│  │  │  Asana)    │  │ Policy       │  │ Observability      │     │  │
│  │  └────────────┘  └──────────────┘  └────────────────────┘     │  │
└───────────────────────────────────────────────────────────────────────┘
```

---

## 3. AgentCore Services

### 3a. AgentCore Browser — Screenshot Capture for Guides

Docwriter uses AgentCore Browser for a specific purpose: capturing annotated screenshots for user-facing documentation. When writing a guide for "How to use advanced search filters," it navigates the actual app, captures each step, and includes the screenshots in the doc.

```python
async def capture_guide_screenshots(steps: list, target_url: str) -> list:
    """Navigate the app and capture screenshots for each guide step."""
    screenshots = []
    
    with browser_session(region="us-west-2") as client:
        ws_url, headers = client.generate_ws_headers()
        async with async_playwright() as pw:
            browser = await pw.chromium.connect_over_cdp(
                endpoint_url=ws_url, headers=headers
            )
            page = await browser.new_page()
            await page.goto(target_url)
            
            for step in steps:
                # Execute the step action
                await execute_step_action(page, step)
                
                # Capture with element highlighting
                if step.get('highlight_selector'):
                    await page.evaluate(f"""
                        document.querySelector('{step["highlight_selector"]}')
                            .style.outline = '3px solid #FF6B35';
                    """)
                
                path = f"/tmp/guide/{step['id']}.png"
                await page.screenshot(path=path, full_page=False)
                screenshots.append({
                    'step_id': step['id'],
                    'path': path,
                    'caption': step['caption']
                })
            
            await browser.close()
    
    return screenshots
```

### 3b. AgentCore Code Interpreter — Doc Tooling

Docwriter uses Code Interpreter for technical doc tasks:

- **OpenAPI parsing**: Load and parse OpenAPI/Swagger specs to generate structured API reference
- **Link validation**: Check all internal and external links in documentation for 404s
- **Doc coverage analysis**: Compare documented endpoints against actual route definitions
- **Markdown linting**: Run markdownlint or custom rules against generated content
- **Diff analysis**: Parse PR diffs to identify which docs need updating

```python
@tool
def parse_openapi_spec(spec_path: str) -> dict:
    """Parse OpenAPI spec and extract structured endpoint documentation."""
    # Runs in Code Interpreter
    code = f"""
import json
import yaml

with open('{spec_path}') as f:
    spec = yaml.safe_load(f) if '{spec_path}'.endswith('.yaml') else json.load(f)

endpoints = []
for path, methods in spec.get('paths', {{}}).items():
    for method, details in methods.items():
        if method in ('get', 'post', 'put', 'patch', 'delete'):
            endpoints.append({{
                'method': method.upper(),
                'path': path,
                'summary': details.get('summary', ''),
                'description': details.get('description', ''),
                'parameters': details.get('parameters', []),
                'request_body': details.get('requestBody', {{}}),
                'responses': details.get('responses', {{}}),
                'tags': details.get('tags', []),
            }})

print(json.dumps({{'endpoint_count': len(endpoints), 'endpoints': endpoints}}))
"""
    return ci_client.invoke("executeCode", {"code": code, "language": "python"})
```

### 3c. AgentCore Gateway — GitHub, Asana, Slack

**GitHub tools (emphasis on file access):**
- `github_get_file` — read existing docs, code, OpenAPI specs
- `github_list_files` — enumerate docs directory structure
- `github_get_pr` — read PR diffs to identify doc-impacting changes
- `github_create_pr` — open doc update PRs
- `github_add_comment` — post doc review findings on PRs
- `github_create_issue` — file issues for missing documentation
- `github_search_code` — find undocumented endpoints and components

**Asana tools:**
- `asana_get_task` — read feature descriptions for guide authoring
- `asana_add_comment` — post doc status updates
- `asana_create_task` — create doc tasks when gaps are found

**Slack tools:**
- `slack_post_message` — notify team of doc updates, release notes
- `slack_upload_file` — share generated docs for review

### 3d. AgentCore Memory — Documentation Intelligence

```python
memory = client.create_memory_and_wait(
    name="InkwellMemory",
    description="Style guide, doc inventory, feature mappings, audience profiles",
    strategies=[
        {"semanticMemoryStrategy": {
            "name": "StyleGuide",
            "namespaceTemplates": ["/style"],
            # Tone: direct, second person ("you"), avoid jargon
            # Terminology: use product glossary terms consistently
            # Structure: overview → prerequisites → steps → troubleshooting
            # Code samples: always include curl + SDK examples
        }},
        {"semanticMemoryStrategy": {
            "name": "DocInventory",
            "namespaceTemplates": ["/inventory/{section}"],
            # Maps every doc file to: topic, last updated, source PR,
            # related features, target audience, freshness status
        }},
        {"semanticMemoryStrategy": {
            "name": "FeatureDocMap",
            "namespaceTemplates": ["/features/{feature_id}"],
            # Maps features to their documentation:
            # feature → [api_ref, user_guide, changelog_entry, readme_section]
            # Enables: "this PR changes search → these 4 docs need review"
        }},
        {"userPreferenceMemoryStrategy": {
            "name": "AudienceProfiles",
            "namespaceTemplates": ["/audiences"],
            # API docs: developer audience, technical depth, code samples
            # User guides: admin user audience, task-oriented, screenshots
            # Setup guides: DevOps audience, infrastructure focus
        }}
    ]
)
```

### 3e. AgentCore Policy

```cedar
// Read broadly
permit(
    principal == AgentCore::Agent::"Docwriter",
    action == AgentCore::Action::"InvokeTool",
    resource
) when {
    resource.toolName.startsWith("github_get_") ||
    resource.toolName.startsWith("github_list_") ||
    resource.toolName.startsWith("github_search_") ||
    resource.toolName.startsWith("asana_get_") ||
    resource.toolName.startsWith("asana_list_")
};

// Write: create doc PRs, issues, comments
permit(
    principal == AgentCore::Agent::"Docwriter",
    action == AgentCore::Action::"InvokeTool",
    resource
) when {
    resource.toolName == "github_create_pr" ||
    resource.toolName == "github_add_comment" ||
    resource.toolName == "github_create_issue" ||
    resource.toolName == "asana_create_task" ||
    resource.toolName == "asana_add_comment" ||
    resource.toolName == "slack_post_message" ||
    resource.toolName == "slack_upload_file"
};

// Browser for screenshots, Code Interpreter for tooling
permit(
    principal == AgentCore::Agent::"Docwriter",
    action == AgentCore::Action::"StartBrowserSession",
    resource
);
permit(
    principal == AgentCore::Agent::"Docwriter",
    action == AgentCore::Action::"ExecuteCode",
    resource
);

// Cannot merge, close, or delete
forbid(
    principal == AgentCore::Agent::"Docwriter",
    action == AgentCore::Action::"InvokeTool",
    resource
) when {
    resource.toolName == "github_merge_pr" ||
    resource.toolName == "github_close_issue" ||
    resource.toolName == "github_delete_branch" ||
    resource.toolName == "asana_delete_task"
};
```

---

## 4. Agent Implementation

### 4a. System Prompt

```python
SYSTEM_PROMPT = """You are Docwriter, an autonomous technical writer agent for a 
SaaS platform.

You have six operating modes:

1. API_DOCS — Generate and maintain API reference documentation from OpenAPI 
   specs and code. Every endpoint must have: description, parameters with 
   types and examples, request/response samples, error codes, and rate limits.
   Include both curl and SDK (Python, TypeScript) examples.

2. USER_GUIDE — Write end-user documentation for features. Navigate the actual
   app using AgentCore Browser to capture screenshots for each step. Structure:
   overview → who this is for → prerequisites → step-by-step → tips → 
   troubleshooting. Write in second person ("you"), task-oriented, minimal 
   jargon. Remember: your readers are administrators and end users, not 
   software engineers.

3. RELEASE_NOTES — Generate changelogs from merged PRs. Categorize as:
   New Feature, Improvement, Bug Fix, Breaking Change, Internal. Write for
   end users (what changed FOR THEM), not developers (what code changed).
   
4. DOC_REVIEW — Review documentation PRs for: accuracy against code, 
   completeness, style guide compliance, broken links, and stale content. 
   Post findings as PR comments.

5. GAP_DETECT — Scan the codebase for undocumented features: API endpoints 
   without reference docs, UI features without user guides, config options 
   without README entries. File GitHub issues for each gap found.

6. MAINTAIN — When a code PR changes behavior, identify which docs are 
   affected using the feature→doc map in memory. Either update the docs 
   directly (open a doc PR) or flag them as stale.

Style Rules (also stored in memory, which takes precedence):
- Tone: direct, friendly, confident. Not corporate, not casual.
- Person: second person ("you") for guides, third person for API reference.
- Terminology: use the team's glossary. Follow the product terminology 
  guide stored in memory.
- Structure: lead with what the reader wants to accomplish, not how the 
  system works internally.
- Length: as short as possible, as long as necessary. Cut filler ruthlessly.
- Code samples: always tested. If you include a curl command, verify it 
  matches the actual API spec.
- Screenshots: captured from the live app, not mocked. Include element 
  highlighting for clarity.
- Label all doc PRs with 'docwriter-generated' for tracking.
"""
```

### 4b. Custom Tools

```python
@tool
def generate_api_docs(
    spec_source: str,
    output_format: str = "markdown",
    sections: list = None
) -> dict:
    """Generate API reference documentation from OpenAPI spec or code.
    
    Args:
        spec_source: Path to OpenAPI spec file in repo, or 'scan' to 
                     discover endpoints from route definitions
        output_format: 'markdown', 'docusaurus', 'mintlify', 'readme'
        sections: Specific sections to generate. None = all.
    
    Returns:
        Generated doc files ready to PR, with per-endpoint coverage status.
    """


@tool
def write_user_guide(
    feature: str,
    target_audience: str = "admin_user",
    include_screenshots: bool = True,
    target_url: str = None
) -> dict:
    """Write a user-facing guide for a feature.
    
    Args:
        feature: Feature name or GitHub issue/Asana task reference
        target_audience: Persona from memory (admin_user, end_user, developer)
        include_screenshots: Capture live screenshots via AgentCore Browser
        target_url: App URL for screenshots. Defaults to staging.
    
    Returns:
        Guide document with embedded screenshots, ready to PR to docs/.
    """


@tool
def generate_release_notes(
    since_tag: str = None,
    since_date: str = None,
    pr_numbers: list = None,
    audience: str = "end_user"
) -> dict:
    """Generate release notes from merged PRs.
    
    Args:
        since_tag: Git tag to start from (e.g., 'v2.3.0')
        since_date: ISO date to start from (alternative to tag)
        pr_numbers: Specific PRs to include (overrides date/tag range)
        audience: 'end_user' (what changed for them) or 'developer' 
                  (technical changes)
    
    Returns:
        Categorized release notes in markdown.
    """


@tool
def detect_doc_gaps(
    scope: str = "full",
    section: str = None
) -> dict:
    """Scan for undocumented features and file issues.
    
    Args:
        scope: 'full' (entire repo), 'api' (endpoints only), 
               'ui' (user features only), 'config' (setup/config)
        section: Limit to specific section of codebase
    
    Returns:
        List of gaps found with severity and suggested doc structure.
        Issues filed in GitHub for each gap.
    """


@tool
def check_doc_freshness(
    doc_path: str = None,
    project: str = None
) -> dict:
    """Check if existing docs are stale relative to the code.
    
    Args:
        doc_path: Specific doc file to check. None = check all.
        project: Limit to docs related to a specific project/feature.
    
    Returns:
        Staleness report: which docs are outdated, what changed in code,
        and which PRs caused the drift.
    """


@tool
def review_doc_pr(pr_number: int, repo: str) -> dict:
    """Review a documentation PR for quality and accuracy.
    
    Checks: accuracy against code, style guide compliance, link validity,
    completeness, and consistency with existing docs.
    
    Posts review findings as a PR comment.
    """


@tool
def update_docs_for_code_change(pr_number: int, repo: str) -> dict:
    """Analyze a code PR and update affected documentation.
    
    Uses the feature→doc map in memory to identify which docs
    need updating. Opens a doc PR with changes.
    """
```

---

## 5. Invocation Patterns

### 5a. Via Dispatch (@docbot / @docwriter mentions)

```
GitHub PR:          @docbot review this doc change
GitHub PR:          @docwriter update docs affected by this PR
GitHub issue:       @docbot write a user guide for content discovery
Asana task:         @docwriter generate API docs for the new endpoints
Slack:              @docbot what docs are out of date?
```

### 5b. Scheduled (EventBridge)

```
Weekly (Monday 7am):
  → "Check doc freshness across all docs. Post staleness report to #docs."

Per release (triggered by git tag):
  → "Generate release notes since last tag. Post to Slack and update 
     CHANGELOG.md."

Monthly (1st of month):
  → "Run full doc gap detection. File issues for anything missing."
```

### 5c. Event-Driven

```
PR merged with label 'feature':
  → Docwriter checks if user guide exists for this feature
  → If not, creates a doc task in Asana

PR merged that changes API routes:
  → Docwriter updates API reference docs, opens doc PR

PR opened that modifies docs/:
  → Docwriter auto-reviews for style guide compliance
```

### 5d. Agent-to-Agent (A2A)

```
Researcher drafts new user stories:
  → Docwriter checks if the feature area has documentation
  → If gaps exist, creates doc tasks alongside dev tasks

Uat generates test scripts:
  → Docwriter reads test descriptions to verify docs match 
     the tested behavior

Workitems generates release status:
  → Docwriter drafts release notes for the completed items
```

---

## 6. Documentation Workflows

### 6a. New Feature → Docs Pipeline

```
1. Researcher creates user story (#200: "Search with advanced filters")
2. Developer implements feature, merges PR #47
3. PR merge triggers Docwriter:
   a. Reads PR #47 diff — identifies new API endpoint /api/v1/search
   b. Reads existing OpenAPI spec — new endpoint is defined
   c. Generates API reference for /api/v1/search
   d. Reads related Asana task — has user-facing description
   e. Writes user guide "How to use advanced search filters"
   f. Captures screenshots by navigating staging app
   g. Opens doc PR #48 with: API ref + user guide + updated nav
   h. Posts to Slack: "📝 Docs ready for review: PR #48"
4. Human reviews and merges doc PR
5. Docwriter updates feature→doc map in memory
```

### 6b. Release Notes Generation

```
1. Release manager tags v2.4.0
2. EventBridge triggers Docwriter: "Generate release notes since v2.3.0"
3. Docwriter:
   a. Lists PRs merged between tags
   b. Reads each PR title, description, and labels
   c. Categorizes: 3 features, 5 fixes, 1 breaking change
   d. Rewrites for end users:
      - Developer PR: "Refactor query engine for Elasticsearch 8.x"
      - User-facing note: "Search results now load up to 40% faster"
   e. Flags breaking change prominently with migration steps
   f. Commits to CHANGELOG.md
   g. Posts formatted notes to #releases Slack channel
```

### 6c. Doc Freshness Maintenance

```
1. Weekly scan compares doc last-modified dates against code changes
2. For each doc:
   a. Find the feature it documents (from feature→doc map)
   b. Find PRs that modified that feature since doc was last updated
   c. If divergence found, classify severity:
      - STALE: behavior changed, doc is wrong
      - DRIFT: minor detail changed, doc is imprecise
      - OK: code changed but documented behavior is unchanged
3. For STALE docs: open update PR directly
4. For DRIFT docs: file issue with low priority
5. Post weekly freshness report to Slack
```

---

## 7. Style Guide Enforcement

Docwriter reviews all doc PRs (including human-written ones) against the style guide stored in memory.

**Review checklist:**
- Tone: direct, friendly, second person for guides
- Terminology: matches team glossary (stored in memory)
- Structure: follows template for doc type (API ref, guide, README)
- Code samples: syntax-valid (checked via Code Interpreter)
- Links: all internal links resolve (checked via Code Interpreter)
- Screenshots: present where needed, not outdated
- Length: no unnecessary filler paragraphs

**Review output posted as PR comment:**
```markdown
## 📝 Docwriter Doc Review

**Style Score: 8/10**

### Issues Found
- Line 14: "utilize" → "use" (simpler word preferred)
- Line 23: "the system processes the request" → rewrite in second 
  person ("when you submit a search")
- Line 45: Link to /docs/api/auth points to deleted page
- Code sample on line 67: missing `Authorization` header in curl example

### Looks Good
- Clear step-by-step structure
- Good use of screenshots
- Troubleshooting section covers common errors
```

---

## 8. Implementation Phases

| Phase | Scope | Weeks |
|-------|-------|-------|
| **1. Foundation** | AgentCore Runtime + Identity + Gateway. Read access to GitHub. Memory with style guide and doc inventory. | 1–2 |
| **2. Release Notes** | `generate_release_notes` from merged PRs. Triggered by git tags. Posts to Slack and CHANGELOG.md. | 2–3 |
| **3. API Docs** | `generate_api_docs` from OpenAPI spec via Code Interpreter. Opens doc PRs. | 3–5 |
| **4. Doc Review** | `review_doc_pr` for style, accuracy, and links. Auto-triggered on doc PR opens. | 5–6 |
| **5. Gap Detection** | `detect_doc_gaps` scanning codebase. Monthly scheduled runs. Files issues. | 6–7 |
| **6. User Guides** | `write_user_guide` with AgentCore Browser screenshot capture. Full guide generation from feature descriptions. | 7–9 |
| **7. Maintenance** | `check_doc_freshness` and `update_docs_for_code_change`. PR-triggered doc updates. Feature→doc mapping. | 9–10 |
| **8. A2A + Dispatch** | Full Dispatch integration. A2A with Researcher, Uat, Workitems. | 10–11 |

---

## 9. Integration with AWS Security Agent

Since the team uses AWS Security Agent (frontier agent) for security rather than a custom @sentinel agent, Docwriter has a specific integration point: when Security Agent posts findings on PRs, Docwriter can translate security recommendations into documentation updates.

```
AWS Security Agent posts finding on PR #50:
  "Authentication endpoint vulnerable to timing-based enumeration"

Docwriter reads the finding and:
  1. Checks if auth docs mention rate limiting → if not, flags as doc gap
  2. Updates API reference with security notes for the auth endpoint
  3. Adds troubleshooting entry: "429 responses on login"
```

This keeps security documentation current without requiring the security team to also be technical writers.

---

## 10. What This Enables

| Before Docwriter | After Docwriter |
|----------------|---------------|
| Docs written weeks after features ship, if at all | Docs generated as part of the merge pipeline |
| API reference is perpetually out of date | API docs auto-updated from OpenAPI spec on every change |
| Release notes cobbled together from memory on release day | Release notes auto-generated, categorized, and user-facing |
| Nobody knows which docs are stale | Weekly freshness reports with specific staleness flags |
| Doc PRs reviewed inconsistently | Every doc PR gets automated style guide review |
| Screenshots in guides are from 6 months ago | Screenshots captured from live staging on every guide update |
| New engineers spend days figuring out setup because the README is wrong | README auto-updated when infrastructure changes |
