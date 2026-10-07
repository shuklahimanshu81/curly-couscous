"""Run this once on your laptop to mint a YouTube refresh token.

    python scripts/get_youtube_token.py

You need a Google Cloud project with the YouTube Data API v3 enabled and an OAuth
client of type "Desktop app". Put the resulting refresh token into the repo secret
YT_REFRESH_TOKEN. It does not expire as long as it keeps being used, though Google
will revoke it if the OAuth consent screen stays in Testing mode for more than a
week -- push the app to Production (external, no verification needed for your own
channel) to avoid that.

Nothing here touches the repo or any secret store. The token is printed once and
it is on you to paste it into GitHub.
"""

import http.server
import secrets
import socketserver
import sys
import threading
import urllib.parse
import webbrowser

import requests

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/youtube.upload"
PORT = 8723
REDIRECT = f"http://localhost:{PORT}/"

_code: str | None = None
_state = secrets.token_urlsafe(16)


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        global _code
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()

        if params.get("state", [""])[0] != _state:
            self.wfile.write(b"<h2>State mismatch. Start over.</h2>")
            return
        if "code" not in params:
            self.wfile.write(b"<h2>No code returned. Start over.</h2>")
            return

        _code = params["code"][0]
        self.wfile.write(b"<h2>Done. You can close this tab.</h2>")

    def log_message(self, *args):
        pass  # keep the console clean


def main() -> int:
    client_id = input("OAuth client id: ").strip()
    client_secret = input("OAuth client secret: ").strip()
    if not (client_id and client_secret):
        print("Both values are required.")
        return 1

    query = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": REDIRECT,
            "response_type": "code",
            "scope": SCOPE,
            "access_type": "offline",     # this is what produces a refresh token
            "prompt": "consent",          # force one even on a repeat authorisation
            "state": _state,
        }
    )
    url = f"{AUTH_URL}?{query}"

    server = socketserver.TCPServer(("", PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    print(f"\nOpening your browser. If it does not open, visit:\n{url}\n")
    webbrowser.open(url)

    while _code is None:
        threading.Event().wait(0.4)
    server.shutdown()

    resp = requests.post(
        TOKEN_URL,
        data={
            "code": _code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": REDIRECT,
            "grant_type": "authorization_code",
        },
        timeout=30,
    )
    if resp.status_code >= 400:
        print(f"Token exchange failed: {resp.text}")
        return 1

    refresh = resp.json().get("refresh_token")
    if not refresh:
        print("No refresh_token came back. Revoke the app's access at "
              "https://myaccount.google.com/permissions and run this again.")
        return 1

    print("\n" + "=" * 60)
    print("Add these three as repository secrets:\n")
    print(f"  YT_CLIENT_ID      = {client_id}")
    print(f"  YT_CLIENT_SECRET  = {client_secret}")
    print(f"  YT_REFRESH_TOKEN  = {refresh}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
