"""One-shot Jira/Atlassian OAuth 2.0 (3LO) bootstrap.

Opens a browser, walks through the Atlassian consent screen, catches the
redirect on localhost, exchanges the code for tokens, and prints the
refresh token + cloud ID so they can be stored in SSM.

Usage:
    python scripts/bootstrap_jira_oauth.py \\
        --client-id ... \\
        --client-secret ...

After running, stash the outputs in SSM (or set them as env vars for local
runs):
    /sdlc-agents/jira-mcp-client-id
    /sdlc-agents/jira-mcp-client-secret
    /sdlc-agents/jira-mcp-refresh-token
    /sdlc-agents/jira-cloud-id
"""

import argparse
import http.server
import secrets
import sys
import threading
import urllib.parse
import webbrowser

import requests

REDIRECT_URI = "http://localhost:8976/callback"
AUTHORIZE_URL = "https://auth.atlassian.com/authorize"
TOKEN_URL = "https://auth.atlassian.com/oauth/token"  # nosec B105 — OAuth endpoint URL, not a credential
ACCESSIBLE_RESOURCES_URL = "https://api.atlassian.com/oauth/token/accessible-resources"

SCOPES = [
    "read:jira-work",
    "write:jira-work",
    "read:jira-user",
    "read:me",
    "offline_access",
]


class CallbackHandler(http.server.BaseHTTPRequestHandler):
    code = None
    state = None
    error = None

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return

        params = urllib.parse.parse_qs(parsed.query)
        CallbackHandler.code = params.get("code", [None])[0]
        CallbackHandler.state = params.get("state", [None])[0]
        CallbackHandler.error = params.get("error", [None])[0]

        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        if CallbackHandler.error:
            body = f"<h1>Error: {CallbackHandler.error}</h1>"
        else:
            body = "<h1>Authorized. You can close this tab.</h1>"
        self.wfile.write(body.encode())

    def log_message(self, *_):
        pass


def wait_for_code(port: int) -> tuple[str, str]:
    server = http.server.HTTPServer(("127.0.0.1", port), CallbackHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    while CallbackHandler.code is None and CallbackHandler.error is None:
        pass

    server.shutdown()
    if CallbackHandler.error:
        print(f"Atlassian returned error: {CallbackHandler.error}", file=sys.stderr)
        sys.exit(1)
    return CallbackHandler.code, CallbackHandler.state


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--client-secret", required=True)
    args = parser.parse_args()

    state = secrets.token_urlsafe(16)
    authorize_params = {
        "audience": "api.atlassian.com",
        "client_id": args.client_id,
        "scope": " ".join(SCOPES),
        "redirect_uri": REDIRECT_URI,
        "state": state,
        "response_type": "code",
        "prompt": "consent",
    }
    authorize_url = f"{AUTHORIZE_URL}?{urllib.parse.urlencode(authorize_params)}"

    print(f"Opening browser to:\n  {authorize_url}\n")
    webbrowser.open(authorize_url)

    code, returned_state = wait_for_code(8976)
    if returned_state != state:
        print("State mismatch — possible CSRF. Aborting.", file=sys.stderr)
        sys.exit(1)

    token_resp = requests.post(
        TOKEN_URL,
        json={
            "grant_type": "authorization_code",
            "client_id": args.client_id,
            "client_secret": args.client_secret,
            "code": code,
            "redirect_uri": REDIRECT_URI,
        },
        timeout=15,
    )
    token_resp.raise_for_status()
    tokens = token_resp.json()

    access_token = tokens["access_token"]
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        print("No refresh_token returned. Is offline_access in the app scopes?", file=sys.stderr)
        sys.exit(1)

    resources_resp = requests.get(
        ACCESSIBLE_RESOURCES_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=15,
    )
    resources_resp.raise_for_status()
    resources = resources_resp.json()

    print("\n--- Atlassian accessible sites ---")
    for r in resources:
        print(f"  {r['name']:30s} cloud_id={r['id']}  url={r['url']}")

    print("\n--- Save to SSM (or set as env vars) ---")
    print(f"JIRA_MCP_CLIENT_ID       = {args.client_id}")
    print(f"JIRA_MCP_CLIENT_SECRET   = <the value you passed in>")
    print(f"JIRA_MCP_REFRESH_TOKEN   = {refresh_token}")
    if len(resources) == 1:
        print(f"JIRA_CLOUD_ID            = {resources[0]['id']}")
    else:
        print("JIRA_CLOUD_ID            = <pick the right cloud_id from above>")


if __name__ == "__main__":
    main()
