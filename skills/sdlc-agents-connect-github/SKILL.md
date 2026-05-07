---
name: sdlc-agents-connect-github
description: Use when the user needs to connect SDLC agents to GitHub. Walks through installing GitHub's official remote MCP server access, capturing credentials, configuring the deploy-role OIDC trust, and verifying agent + CI paths. Knows the specific GitHub pitfalls (GitHub App vs PAT, fine-grained vs classic PAT, org SSO enforcement).
---

# Connect the SDLC Agent Fleet to GitHub

## Two access channels

Like Asana, GitHub access splits:

- **Agent runtime → GitHub MCP server** (`https://api.githubcopilot.com/mcp/`). Uses a **GitHub App** installation token, OR a PAT stored at `/sdlc-agents/github-mcp-token`. GitHub's official MCP supports both.
- **CI (deploy workflow) → AWS** (no GitHub side needed beyond OIDC). The deploy role is assumed via GitHub Actions OIDC. No secret stored in GitHub beyond `AWS_DEPLOY_ROLE_ARN` and `AWS_ACCOUNT_ID`.

## Decide: PAT or GitHub App?

Ask the user which they prefer:

| | PAT | GitHub App |
|---|---|---|
| **Setup time** | ~2 min | ~15 min |
| **Scope** | user-wide (acts as the PAT owner) | repo- or org-scoped (acts as the App) |
| **Rate limits** | 5000 req/hr per user | 5000+ per installation, better for high-volume |
| **Revocation** | manual token delete | single click in org settings |
| **Org SSO** | need to "authorize" the PAT for each SSO-protected org | works cleanly with SSO |
| **Right for** | demos, single-repo projects, solo dev | production, orgs with SSO, multi-repo |

For a demo, PAT is fine. For production, push toward GitHub App.

## Path A — PAT (fast path)

1. User goes to https://github.com/settings/personal-access-tokens/new (fine-grained, preferred) or https://github.com/settings/tokens/new (classic)
2. For fine-grained: select the target repo(s), grant **Contents: Read**, **Issues: Read and Write**, **Pull requests: Read and Write**, **Metadata: Read**. For Docwriter-style agents that open doc PRs, also grant **Contents: Read and Write**. For agents reading releases: **Code: Read**.
3. For classic: `repo` scope is the blunt-but-working option.
4. If the repo is in an SSO-protected org, the user must click **Configure SSO** on the PAT and authorize it for the org.
5. Copy the token, store in SSM:

   ```bash
   read -r GH_TOKEN
   aws ssm put-parameter \
     --name /sdlc-agents/github-mcp-token \
     --value "$GH_TOKEN" \
     --type SecureString \
     --region "$REGION" \
     --overwrite
   unset GH_TOKEN
   ```

## Path B — GitHub App (production path)

1. User goes to https://github.com/organizations/<org>/settings/apps → **New GitHub App**
2. Fill the required fields:
   - Name: `SDLC Agent Fleet (<stage>)`
   - Homepage: any URL
   - Webhook: can be disabled for MCP-only usage (the agent-dispatch workflow is what listens for `@agent` mentions, not this app)
   - Permissions (Repository): Contents Read & Write, Issues R&W, Pull requests R&W, Metadata Read
   - Permissions (Organization): Members Read (optional, for routing by team)
3. Generate a private key. Download the PEM.
4. Install the app on the target repos.
5. Store the App ID, installation ID, and PEM in SSM:

   ```bash
   aws ssm put-parameter --name /sdlc-agents/github-app-id --value "<app_id>" --type String --region "$REGION" --overwrite
   aws ssm put-parameter --name /sdlc-agents/github-app-installation-id --value "<installation_id>" --type String --region "$REGION" --overwrite
   aws ssm put-parameter --name /sdlc-agents/github-app-private-key --value "$(cat app.pem)" --type SecureString --region "$REGION" --overwrite
   rm app.pem  # don't leave it on disk
   ```

6. The agents mint installation tokens at runtime via JWT signed with the PEM; existing tool code in `agents/*/tools/github_mcp.py` reads either SSM shape.

## Verify

```bash
# Reads $REGION from the environment — same AWS region used in
# sdlc-agents-provision-aws (recorded at .sdlc-agents/selection.yaml → aws.region).
python3 <<'PY'
import os, boto3, requests
ssm = boto3.client("ssm", region_name=os.environ["REGION"])
# Path A: PAT
try:
    tok = ssm.get_parameter(Name="/sdlc-agents/github-mcp-token", WithDecryption=True)["Parameter"]["Value"]
    r = requests.get("https://api.github.com/user", headers={"Authorization": f"Bearer {tok}", "Accept":"application/vnd.github+json"}, timeout=15)
    print(f"PAT user: {r.status_code} {r.json().get('login','?')}")
    r = requests.get("https://api.githubcopilot.com/mcp/", headers={"Authorization": f"Bearer {tok}","Accept":"application/json, text/event-stream"}, timeout=15)
    print(f"MCP: {r.status_code}")
except Exception as e:
    print(f"PAT path not configured: {e}")

# Path B: GitHub App — skipped here unless the user set it up
PY
```

MCP should return 200 or a JSON-RPC response on POST. A 401 means the token isn't MCP-enabled (GitHub's MCP requires tokens with specific scopes; fine-grained tokens must have at least "Contents" and "Issues").

## Configure CI OIDC

Separate from the MCP credential: the deploy workflows assume an AWS role via OIDC. The OIDC provider and deploy role are **not** created by the foundation stack — `sdlc-agents-provision-aws` Step 0 creates them manually (one-time per AWS account). By the time you're in this skill, that role exists and its ARN was captured as `$DEPLOY_ROLE_ARN`. The target GitHub repo needs:

- Secret `AWS_DEPLOY_ROLE_ARN` — the role ARN from `sdlc-agents-provision-aws` Step 0b
- Secret `AWS_ACCOUNT_ID` — the 12-digit account ID

Both are already written by `sdlc-agents-provision-aws` Step 5 if you ran it first. If the user skipped that step or set them manually, confirm they exist here.

Walk the user through:
- Repo → Settings → Secrets and variables → Actions → New repository secret
- Add both

No AWS credentials stored in GitHub. The OIDC trust only permits `token.actions.githubusercontent.com` for the configured repo.

## Record GitHub state

Append to `.sdlc-agents/selection.yaml`:

```yaml
github:
  auth_mode: pat        # or: app
  owner: <owner>        # the user's GitHub org or username
  repo: <repo>          # the target repository name
  default_branch: main
```

(`owner/repo/default_branch` are used by `docwriter` and `adr`, and by any future agent that opens PRs.)

## What this skill does NOT do

- Configure the `agent-dispatch.yml` workflow triggers. That's `sdlc-agents-register-triggers`.
- Install Claude Code Action for `@claude` in issues. That's a separate Anthropic-provided action, not part of this fleet.
- Handle GitLab. If the user is on GitLab, use `sdlc-agents-connect-gitlab` (not yet written — flag it as a gap if asked).
