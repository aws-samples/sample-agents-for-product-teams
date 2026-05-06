"""One-shot Asana OAuth 2.0 bootstrap.

Opens a browser, walks through the Asana consent screen, catches the
redirect on localhost, exchanges the code for a refresh token, and
writes the refresh token to SSM at /sdlc-agents/asana-mcp-refresh-token.

Run this once whenever the Asana user that the agents should act as changes.

Usage:
    python scripts/bootstrap_asana_oauth.py
"""

import argparse
import http.server
import secrets
import sys
import threading
import urllib.parse
import webbrowser

import boto3
import requests

REDIRECT_URI = "http://localhost:8976/callback"
AUTHORIZE_URL = "https://app.asana.com/-/oauth_authorize"
TOKEN_URL = "https://app.asana.com/-/oauth_token"  # nosec B105 — OAuth endpoint URL, not a credential
USER_ME_URL = "https://app.asana.com/api/1.0/users/me"

CLIENT_ID_PARAM = "/sdlc-agents/asana-mcp-client-id"
CLIENT_SECRET_PARAM = "/sdlc-agents/asana-mcp-client-secret"  # nosec B105 — SSM parameter name, not a secret value
REFRESH_TOKEN_PARAM = "/sdlc-agents/asana-mcp-refresh-token"  # nosec B105 — SSM parameter name, not a secret value


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
        body = (
            f"<h1>Error: {CallbackHandler.error}</h1>"
            if CallbackHandler.error
            else "<h1>Authorized. You can close this tab.</h1>"
        )
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
        print(f"Asana returned error: {CallbackHandler.error}", file=sys.stderr)
        sys.exit(1)
    return CallbackHandler.code, CallbackHandler.state


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--region", default="us-west-2")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the refresh token instead of writing to SSM.")
    args = parser.parse_args()

    ssm = boto3.client("ssm", region_name=args.region)
    client_id = ssm.get_parameter(Name=CLIENT_ID_PARAM, WithDecryption=True)["Parameter"]["Value"]
    client_secret = ssm.get_parameter(Name=CLIENT_SECRET_PARAM, WithDecryption=True)["Parameter"]["Value"]

    state = secrets.token_urlsafe(16)
    # Use Asana's "default" scope bundle, which matches the "Full permissions"
    # checkbox in the OAuth app config. The app must have Full permissions
    # checked (and no explicit granular scopes selected) — mixing the two
    # triggers Asana's "forbidden_scopes: default identity" error.
    authorize_url = f"{AUTHORIZE_URL}?" + urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "state": state,
        "scope": "default",
    })

    print("Log in to Asana as the account you want the agents to act as,")
    print("then click Allow on the consent screen.\n")
    print(f"Opening browser:\n  {authorize_url}\n")
    webbrowser.open(authorize_url)

    code, returned_state = wait_for_code(8976)
    if returned_state != state:
        print("State mismatch — possible CSRF. Aborting.", file=sys.stderr)
        sys.exit(1)

    token_resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": REDIRECT_URI,
        },
        timeout=15,
    )
    if not token_resp.ok:
        print(f"Token exchange failed: {token_resp.status_code} {token_resp.text}", file=sys.stderr)
        sys.exit(1)
    tokens = token_resp.json()

    access_token = tokens["access_token"]
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        print("No refresh_token returned. Asana should return one by default.", file=sys.stderr)
        sys.exit(1)

    if args.dry_run:
        print(f"\n[dry-run] refresh_token = {refresh_token}")
        return

    ssm.put_parameter(
        Name=REFRESH_TOKEN_PARAM,
        Value=refresh_token,
        Type="SecureString",
        Overwrite=True,
    )
    print(f"\nStored new refresh token in SSM {REFRESH_TOKEN_PARAM}.")

    # Best-effort identity probe — don't fail the bootstrap if this errors.
    try:
        me_resp = requests.get(USER_ME_URL, headers={"Authorization": f"Bearer {access_token}"}, timeout=10)
        body = me_resp.json()
        who = body.get("data")
        if who:
            print(f"Authorized as: {who.get('name')} ({who.get('email')}) gid={who.get('gid')}")
            for w in who.get("workspaces", []):
                print(f"  - workspace: {w['name']} ({w['gid']})")
        else:
            print(f"(identity probe returned {me_resp.status_code}: {body})")
    except Exception as e:
        print(f"(identity probe skipped: {e})")

    print("\nNext: rebuild and redeploy the agent containers so they pick up the rotated token.")


if __name__ == "__main__":
    main()
