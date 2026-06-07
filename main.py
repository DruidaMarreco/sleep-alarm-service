"""
sleep-alarm-service
-------------------
FastAPI microservice that reads the "Dormir" Google Calendar event
and returns the wake time. Called by an iOS Shortcut at 05:00.

Auth: Google OAuth2 user credentials (stored refresh token) reading the
      calendar on behalf of the user, protected by a simple shared API key.

Endpoints:
  GET /wake-time          -> { "wake_time": "07:30", "iso": "2026-06-08T07:30:00+01:00", ... }
  GET /health             -> { "ok": true }
"""

import os
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Header
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

app = FastAPI(title="Sleep Alarm Service")

# Timezone is configurable via the TIMEZONE env var (IANA name, e.g.
# "Europe/Lisbon", "America/New_York"). Defaults to Europe/Lisbon.
TIMEZONE = os.environ.get("TIMEZONE", "Europe/Lisbon")
TZ = ZoneInfo(TIMEZONE)
CALENDAR_ID = "primary"
API_KEY = os.environ["ALARM_API_KEY"]          # simple shared secret
TOKEN_JSON = os.environ["GOOGLE_TOKEN_JSON"]    # full token JSON as env var string


def get_calendar_service():
    token_data = json.loads(TOKEN_JSON)
    creds = Credentials(
        token=token_data.get("token"),
        refresh_token=token_data["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=token_data["client_id"],
        client_secret=token_data["client_secret"],
        scopes=["https://www.googleapis.com/auth/calendar.readonly"],
    )
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("calendar", "v3", credentials=creds)


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/wake-time")
def wake_time(x_api_key: str = Header(...)):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")

    now = datetime.now(tz=TZ)
    # Search window: now -> 18 hours from now (covers tonight -> tomorrow morning)
    time_min = now.isoformat()
    time_max = (now + timedelta(hours=18)).isoformat()

    service = get_calendar_service()
    events_result = service.events().list(
        calendarId=CALENDAR_ID,
        timeMin=time_min,
        timeMax=time_max,
        singleEvents=True,
        orderBy="startTime",
        q="Dormir",
    ).execute()

    events = events_result.get("items", [])
    dormir = next(
        (e for e in events if "dormir" in e.get("summary", "").lower()),
        None
    )

    if not dormir:
        raise HTTPException(status_code=404, detail="No Dormir event found")

    end_raw = dormir["end"].get("dateTime") or dormir["end"].get("date")
    end_dt = datetime.fromisoformat(end_raw).astimezone(TZ)

    return {
        "wake_time": end_dt.strftime("%H:%M"),     # e.g. "07:30"
        "iso": end_dt.isoformat(),                  # e.g. "2026-06-08T07:30:00+01:00"
        "hour": end_dt.hour,
        "minute": end_dt.minute,
    }
