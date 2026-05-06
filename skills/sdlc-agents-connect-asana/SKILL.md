---
name: sdlc-agents-connect-asana
description: Use when the user needs to connect SDLC agents to Asana. Walks through creating an Asana MCP OAuth app, capturing the refresh token, storing the PAT for the webhook Lambda, and verifying MCP + REST access. Knows the specific Asana pitfalls (MCP vs API app type, redirect URL registration, the Full permissions checkbox vs granular scopes, default-identity error).
---

# Connect the SDLC Agent Fleet to Asana

## Two auth paths, two purposes

Asana access splits cleanly into two channels — and this is the single most confusing thing about the setup:

- **Agent runtime → Asana MCP server** (`https://mcp.asana.com/v2/mcp`). Requires **OAuth** tokens issued by an app **registered as an MCP app**. Access tokens have audience `mcp-service`. Used by every agent that reads/writes Asana.
- **Webhook Lambda → Asana REST API** (`https://app.asana.com/api/1.0/*`). Needs to read story text, task details, and custom fields. Uses a **PAT** (Personal Access Token) — simplest path, no OAuth dance, and the webhook Lambda already reads it from `/sdlc-agents/asana-pat`.

Don't try to unify these into one credential. Asana's MCP apps can't call REST; API apps can't get MCP tokens. You need both.

## Step 1 — Get a PAT for the webhook Lambda

User logs in to https://app.asana.com/0/my-apps → **Personal access tokens** → **+ New access token** → name it something like `sdlc-webhook-dev` → copy once.

Store in SSM:

```bash
read -r PAT  # paste when prompted; avoids echoing to history
aws ssm put-parameter \
  --name /sdlc-agents/asana-pat \
  --value "$PAT" \
  --type SecureString \
  --region "$REGION" \
  --overwrite
unset PAT
```

Verify:

```bash
PAT=$(aws ssm get-parameter --name /sdlc-agents/asana-pat --with-decryption --region "$REGION" --query 'Parameter.Value' --output text)
curl -s -H "Authorization: Bearer $PAT" "https://app.asana.com/api/1.0/users/me?opt_fields=name,email,workspaces.name,workspaces.gid" | jq .data
unset PAT
```

You should see the user's name, email, and workspace list. Capture the workspace GID the user wants the fleet pointed at.

## Step 2 — Create an Asana MCP OAuth app

The user does this in the browser. Walk them through it:

1. Open https://app.asana.com/0/my-apps → **+ New app**
2. Name it e.g. `SDLC Agent Fleet`
3. In the app's **OAuth & permissions** panel:
   - **App type**: choose **MCP app**, NOT API app. (Default is API app. Wrong choice here = hours of debugging. Error you'll see if you pick API app: `Token audience must be 'mcp-service' for MCP access`.)
   - **Redirect URLs**: add exactly `http://localhost:8976/callback` — no trailing slash, http not https. Save.
   - **Permission scopes**: MCP apps say "Scopes are not yet available for MCP apps" and automatically request full access. No action needed.
4. Copy the **Client ID** and **Client secret**. Save both to SSM:

   ```bash
   aws ssm put-parameter --name /sdlc-agents/asana-mcp-client-id --value "<client_id>" --type SecureString --region "$REGION" --overwrite
   read -r CS  # paste secret
   aws ssm put-parameter --name /sdlc-agents/asana-mcp-client-secret --value "$CS" --type SecureString --region "$REGION" --overwrite
   unset CS
   ```

## Step 3 — Run the OAuth consent flow to capture a refresh token

```bash
python3 scripts/bootstrap_asana_oauth.py
```

What the script does:
- Reads client_id + client_secret from SSM
- Opens browser to Asana's consent page with `scope=default`
- You click **Allow** (logged in as the Asana user the agents should act as)
- Script catches the callback at `http://localhost:8976/callback`, exchanges the code for a refresh token
- Writes the refresh token to `/sdlc-agents/asana-mcp-refresh-token`

### Known errors and fixes

| Error | Cause | Fix |
|---|---|---|
| `invalid_request: This app is not available to your Asana workspace` | App's Distribution is set to "My workspace only" and the authorizing user isn't in that workspace. | Switch Distribution to "Anyone with an Asana account" in the app's **Manage Distribution** panel. (Only matters if the app was created in a different workspace than the authorizing user.) |
| `invalid_request: The redirect_uri parameter does not match a valid url for the application` | `http://localhost:8976/callback` isn't in the app's Redirect URLs list, or wasn't saved. | Go back to the app, add the URL exactly, click Save. Reload and retry. |
| `forbidden_scopes: Your app is not allowed to request user authorization for default identity scopes` | App has explicit granular scopes checked AND the script requests `scope=default`. They're mutually exclusive. | In the app's Permission scopes section, select only "Full permissions" (deselect individual scopes). Save. Retry. |
| `Token audience must be 'mcp-service' for MCP access` (on MCP probe) | App was registered as API app, not MCP app. | Switch App type to MCP app in the app settings. Delete the stale refresh token from SSM, re-run the script. |

## Step 4 — Verify

After the script completes, verify both channels work:

```bash
# Reads $REGION from the environment (set it to the AWS region where the
# SSM parameters live — same region you used in sdlc-agents-provision-aws,
# recorded at .sdlc-agents/selection.yaml → aws.region).
python3 <<'PY'
import os, boto3, requests
ssm = boto3.client("ssm", region_name=os.environ["REGION"])
cid = ssm.get_parameter(Name="/sdlc-agents/asana-mcp-client-id", WithDecryption=True)["Parameter"]["Value"]
cs  = ssm.get_parameter(Name="/sdlc-agents/asana-mcp-client-secret", WithDecryption=True)["Parameter"]["Value"]
rt  = ssm.get_parameter(Name="/sdlc-agents/asana-mcp-refresh-token", WithDecryption=True)["Parameter"]["Value"]
pat = ssm.get_parameter(Name="/sdlc-agents/asana-pat", WithDecryption=True)["Parameter"]["Value"]

# MCP path
r = requests.post("https://app.asana.com/-/oauth_token", data={
    "grant_type":"refresh_token","client_id":cid,"client_secret":cs,"refresh_token":rt}, timeout=15)
assert r.ok, f"refresh failed: {r.status_code} {r.text}"
tok = r.json()["access_token"]
r = requests.post("https://mcp.asana.com/v2/mcp",
    headers={"Authorization": f"Bearer {tok}","Content-Type":"application/json","Accept":"application/json, text/event-stream"},
    json={"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"probe","version":"0.1"}}},
    timeout=15)
assert r.ok, f"MCP initialize failed: {r.status_code} {r.text}"
print("MCP path: OK")

# REST path
r = requests.get("https://app.asana.com/api/1.0/users/me",
    headers={"Authorization": f"Bearer {pat}"}, timeout=15)
assert r.ok, f"REST failed: {r.status_code} {r.text}"
print(f"REST path: OK — acting as {r.json()['data']['name']} ({r.json()['data']['email']})")
PY
```

Both should print OK. If either fails, don't move on — diagnose first.

## Step 5 — Record Asana state in the dispatch config

Capture these values; later skills read them:

- Workspace GID (the one the agents should operate in)
- Target project GID (the specific project to be watched by webhooks, if scoped) or "workspace-wide" if the user wants broad coverage
- Agent custom-field GID (if they want the custom-field trigger) — if it doesn't exist yet, create it:
  ```bash
  PAT=$(aws ssm get-parameter --name /sdlc-agents/asana-pat --with-decryption --region "$REGION" --query 'Parameter.Value' --output text)
  curl -sS -X POST "https://app.asana.com/api/1.0/custom_fields" \
    -H "Authorization: Bearer $PAT" -H "Content-Type: application/json" \
    -d '{"data":{"workspace":"<WORKSPACE_GID>","resource_subtype":"enum","name":"Agent","description":"Assign an SDLC agent to this task","enum_options":[{"name":"Workitems"},{"name":"Researcher"},{"name":"Docwriter"}]}}'
  unset PAT
  ```
  (Adjust enum options to match the user's selected agents.)

Write these to `.sdlc-agents/asana.yaml` or append to `.sdlc-agents/selection.yaml` under `asana:`.

## What this skill does NOT do

- Register the Asana webhook itself. That's `sdlc-agents-register-triggers`.
- Configure bot accounts in Asana. If the user wants assignment-based triggers, they need to create a dedicated bot user; for dev demos, their own user GID works fine.
- Handle the old-style "I'm migrating from one Asana account to another" flow. It creates fresh credentials every run. If the user is migrating, tell them to delete the old SSM params first (or the agents will keep using the old workspace's credentials).
