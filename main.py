"""
sleep-alarm-service
-------------------
FastAPI microservice that reads a sleep ("Dormir") Google Calendar event
and returns the wake time. Called by an iOS Shortcut at 05:00.

Auth: Google OAuth2 user credentials (stored refresh token) reading the
      calendar on behalf of the user, protected by a simple shared API key.

Endpoints:
  GET /health             -> { "ok": true, "timezone": "Europe/Lisbon" }
  GET /wake-time          -> { "wake_time": "07:30", "iso": "...", "hour": 7, "minute": 30 }

Configuration (environment variables):
  ALARM_API_KEY        (required)  shared secret expected in the X-API-Key header
  GOOGLE_TOKEN_JSON    (required)  OAuth token JSON produced by extract_token.py
  TIMEZONE             (optional)  IANA name, default "Europe/Lisbon"
  CALENDAR_ID          (optional)  calendar to read, default "primary"
  EVENT_KEYWORD        (optional)  case-insensitive event title to match, default "Dormir"
  SEARCH_WINDOW_HOURS  (optional)  how far ahead to look, default 18
"""

import os
import json
import logging
import secrets
import threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import FastAPI, HTTPException, Header
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google.auth.exceptions import GoogleAuthError
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sleep-alarm")

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


# --------------------------------------------------------------------------- #
# Configuration & validation (fail fast at startup with a clear message)
# --------------------------------------------------------------------------- #
class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ConfigError(f"Missing required environment variable: {name}")
    return value


def _load_config():
    api_key = _require_env("ALARM_API_KEY")
    token_raw = _require_env("GOOGLE_TOKEN_JSON")

    tz_name = os.environ.get("TIMEZONE", "Europe/Lisbon")
    try:
        tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ConfigError(
            f"Invalid TIMEZONE '{tz_name}'. Use an IANA name like "
            f"'Europe/Lisbon' or 'America/New_York'."
        ) from exc

    try:
        token_data = json.loads(token_raw)
    except json.JSONDecodeError as exc:
        raise ConfigError("GOOGLE_TOKEN_JSON is not valid JSON.") from exc

    required_token_keys = ("refresh_token", "client_id", "client_secret")
    missing = [k for k in required_token_keys if not token_data.get(k)]
    if missing:
        raise ConfigError(
            f"GOOGLE_TOKEN_JSON is missing keys: {', '.join(missing)}. "
            f"Regenerate it with extract_token.py."
        )

    try:
        window_hours = int(os.environ.get("SEARCH_WINDOW_HOURS", "18"))
    except ValueError as exc:
        raise ConfigError("SEARCH_WINDOW_HOURS must be an integer.") from exc
    if window_hours <= 0:
        raise ConfigError("SEARCH_WINDOW_HOURS must be a positive integer.")

    return {
        "api_key": api_key,
        "token_data": token_data,
        "tz_name": tz_name,
        "tz": tz,
        "calendar_id": os.environ.get("CALENDAR_ID", "primary"),
        "event_keyword": os.environ.get("EVENT_KEYWORD", "Dormir"),
        "window_hours": window_hours,
    }


CONFIG = _load_config()

app = FastAPI(title="Sleep Alarm Service")


# --------------------------------------------------------------------------- #
# Google Calendar credentials (cached & refreshed under a lock)
# --------------------------------------------------------------------------- #
_creds_lock = threading.Lock()
_creds: Credentials | None = None


def _get_credentials() -> Credentials:
    global _creds
    with _creds_lock:
        if _creds is None:
            td = CONFIG["token_data"]
            _creds = Credentials(
                token=td.get("token"),
                refresh_token=td["refresh_token"],
                token_uri=td.get("token_uri", "https://oauth2.googleapis.com/token"),
                client_id=td["client_id"],
                client_secret=td["client_secret"],
                scopes=SCOPES,
            )
        if not _creds.valid:
            _creds.refresh(Request())
        return _creds


def _get_calendar_service():
    creds = _get_credentials()
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _parse_event_end(dormir: dict, tz: ZoneInfo) -> datetime:
    """Return the event end as an aware datetime in `tz`.

    Handles both timed events (end.dateTime, RFC3339 with offset) and
    all-day events (end.date, a bare YYYY-MM-DD treated as midnight in tz).
    """
    end = dormir.get("end", {})
    end_raw = end.get("dateTime") or end.get("date")
    if not end_raw:
        raise HTTPException(status_code=502, detail="Event has no end time.")

    try:
        end_dt = datetime.fromisoformat(end_raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Could not parse event end time: {end_raw!r}",
        ) from exc

    if end_dt.tzinfo is None:
        # All-day event (date only) — anchor it to midnight in the configured tz.
        end_dt = end_dt.replace(tzinfo=tz)
    return end_dt.astimezone(tz)


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
@app.get("/health")
def health():
    return {"ok": True, "timezone": CONFIG["tz_name"]}


@app.get("/wake-time")
def wake_time(x_api_key: str = Header(default="")):
    # Constant-time comparison to avoid leaking the key via timing.
    if not secrets.compare_digest(x_api_key, CONFIG["api_key"]):
        raise HTTPException(status_code=401, detail="Unauthorized")

    tz = CONFIG["tz"]
    now = datetime.now(tz=tz)
    time_min = now.isoformat()
    time_max = (now + timedelta(hours=CONFIG["window_hours"])).isoformat()

    try:
        service = _get_calendar_service()
        events_result = service.events().list(
            calendarId=CONFIG["calendar_id"],
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
            q=CONFIG["event_keyword"],
        ).execute()
    except HttpError as exc:
        status = getattr(getattr(exc, "resp", None), "status", "?")
        logger.warning("Google Calendar API error (status=%s): %s", status, exc)
        raise HTTPException(
            status_code=502, detail="Upstream calendar API error."
        ) from exc
    except GoogleAuthError as exc:
        logger.warning("Google auth/refresh failed: %s", exc)
        raise HTTPException(
            status_code=502,
            detail="Calendar authentication failed. The token may be revoked or expired.",
        ) from exc
    except Exception as exc:  # network errors, timeouts, etc.
        logger.exception("Unexpected error talking to Google Calendar")
        raise HTTPException(
            status_code=502, detail="Could not reach the calendar service."
        ) from exc

    events = events_result.get("items", [])
    keyword = CONFIG["event_keyword"].lower()
    dormir = next(
        (e for e in events if keyword in (e.get("summary") or "").lower()),
        None,
    )

    if not dormir:
        raise HTTPException(
            status_code=404,
            detail=f"No '{CONFIG['event_keyword']}' event found in the next "
                   f"{CONFIG['window_hours']}h.",
        )

    end_dt = _parse_event_end(dormir, tz)

    return {
        "wake_time": end_dt.strftime("%H:%M"),     # e.g. "07:30"
        "iso": end_dt.isoformat(),                  # e.g. "2026-06-08T07:30:00+01:00"
        "hour": end_dt.hour,
        "minute": end_dt.minute,
    }
