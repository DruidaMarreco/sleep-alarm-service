"""
Run this ONCE locally to generate the GOOGLE_TOKEN_JSON env var value.

Usage:
  pip install google-auth-oauthlib
  python extract_token.py

It will open a browser, you authorize Google Calendar read access,
and it prints the JSON string to paste into Railway as GOOGLE_TOKEN_JSON.
"""

import json
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

# Download OAuth2 client credentials from Google Cloud Console
# (OAuth 2.0 Client ID -> Desktop App -> Download JSON) and save as client_secret.json
flow = InstalledAppFlow.from_client_secrets_file("client_secret.json", SCOPES)
creds = flow.run_local_server(port=0)

token_data = {
    "token": creds.token,
    "refresh_token": creds.refresh_token,
    "token_uri": creds.token_uri,
    "client_id": creds.client_id,
    "client_secret": creds.client_secret,
    "scopes": list(creds.scopes),
}

print("\n=== Paste this as GOOGLE_TOKEN_JSON in Railway ===\n")
print(json.dumps(token_data))
