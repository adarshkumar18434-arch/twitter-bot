# -*- coding: utf-8 -*-
"""
=======================================================
 LinkedIn One-Time OAuth Token Generator
 Run this ONCE to get your Access Token + Person URN
 Then paste them into your .env file
=======================================================
"""

import sys
import os
import json
import urllib.parse
import http.server
import socketserver
import threading
import webbrowser
import urllib.request

# Fix Windows console encoding so emojis don't crash
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ─────────────────────────────────────────────
# YOUR APP CREDENTIALS
# ─────────────────────────────────────────────
CLIENT_ID     = "772lwop654dkah"
# Fetch client secret from .env or prompt user interactively
CLIENT_SECRET = os.getenv("LINKEDIN_CLIENT_SECRET") or input("Enter your LinkedIn Client Secret: ").strip()
REDIRECT_URI  = "http://localhost:8000/callback"

# Scopes: w_member_social = post on behalf of you personally
SCOPES = "openid profile w_member_social"

# ─────────────────────────────────────────────
# STEP 1: Build Auth URL
# ─────────────────────────────────────────────
auth_url = (
    "https://www.linkedin.com/oauth/v2/authorization"
    f"?response_type=code"
    f"&client_id={CLIENT_ID}"
    f"&redirect_uri={urllib.parse.quote(REDIRECT_URI, safe='')}"
    f"&scope={urllib.parse.quote(SCOPES, safe='')}"
)

auth_code_holder = {}

# ─────────────────────────────────────────────
# STEP 2: Local server to catch the redirect
# ─────────────────────────────────────────────
class CallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if "code" in params:
            auth_code_holder["code"] = params["code"][0]
            response_html = b"""
            <html><body style='font-family:sans-serif;text-align:center;margin-top:80px'>
            <h2 style='color:green'>&#10003; Authorization Successful!</h2>
            <p>You can close this tab and go back to your terminal.</p>
            </body></html>"""
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(response_html)
        else:
            error = params.get("error_description", ["Unknown error"])[0]
            self.send_response(400)
            self.end_headers()
            self.wfile.write(f"Error: {error}".encode())

        threading.Thread(target=self.server.shutdown).start()

    def log_message(self, format, *args):
        pass  # Suppress server logs

# ─────────────────────────────────────────────
# MAIN FLOW
# ─────────────────────────────────────────────
def main():
    print("\n" + "="*55)
    print("  🔗 LinkedIn OAuth Token Generator")
    print("="*55)
    print("\n📌 Step 1: Opening LinkedIn authorization page...")
    print(f"\n   If the browser doesn't open, visit this URL manually:\n")
    print(f"   {auth_url}\n")

    webbrowser.open(auth_url)

    print("⏳ Step 2: Waiting for you to authorize in the browser...")

    with socketserver.TCPServer(("", 8000), CallbackHandler) as httpd:
        httpd.serve_forever()

    code = auth_code_holder.get("code")
    if not code:
        print("\n❌ No authorization code received. Please try again.")
        return

    print(f"\n✅ Got authorization code! Exchanging for access token...")

    # ─────────────────────────────────────────────
    # STEP 3: Exchange code for access token
    # ─────────────────────────────────────────────
    token_data = urllib.parse.urlencode({
        "grant_type":    "authorization_code",
        "code":          code,
        "redirect_uri":  REDIRECT_URI,
        "client_id":     CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }).encode()

    token_req = urllib.request.Request(
        "https://www.linkedin.com/oauth/v2/accessToken",
        data=token_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST"
    )

    try:
        with urllib.request.urlopen(token_req) as resp:
            token_json = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"\n❌ Token exchange failed [{e.code} {e.reason}]")
        print(f"   LinkedIn says: {body}")
        print("\n   Most likely cause: Wrong Client Secret.")
        print("   Make sure you copied the FULL secret (click the eye icon).")
        return
    except Exception as e:
        print(f"\n❌ Token exchange failed: {e}")
        return

    access_token = token_json.get("access_token")
    expires_in   = token_json.get("expires_in", 5184000)
    expires_days = expires_in // 86400

    if not access_token:
        print(f"\n❌ No access token in response: {token_json}")
        return

    # ─────────────────────────────────────────────
    # STEP 4: Fetch Person URN (sub = person ID)
    # ─────────────────────────────────────────────
    me_req = urllib.request.Request(
        "https://api.linkedin.com/v2/userinfo",
        headers={"Authorization": f"Bearer {access_token}"}
    )
    try:
        with urllib.request.urlopen(me_req) as resp:
            me_json = json.loads(resp.read().decode())
    except Exception as e:
        print(f"\n⚠️ Could not fetch profile info: {e}")
        me_json = {}

    sub = me_json.get("sub", "")
    person_urn = f"urn:li:person:{sub}" if sub else "COULD_NOT_FETCH"
    name = me_json.get("name", "Unknown")

    # ─────────────────────────────────────────────
    # STEP 5: Print results
    # ─────────────────────────────────────────────
    print("\n" + "="*55)
    print("  ✅ SUCCESS! Copy these into your .env file:")
    print("="*55)
    print(f"\n  LINKEDIN_ACCESS_TOKEN={access_token}")
    print(f"  LINKEDIN_PERSON_URN={person_urn}")
    print(f"\n  👤 Logged in as: {name}")
    print(f"  ⏳ Token expires in: ~{expires_days} days")
    print("\n" + "="*55)
    print("  ⚠️  IMPORTANT: Token expires in ~60 days.")
    print("  Re-run this script every 60 days to refresh it.")
    print("="*55 + "\n")

if __name__ == "__main__":
    main()
