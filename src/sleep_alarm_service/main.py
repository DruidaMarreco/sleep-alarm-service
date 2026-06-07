"""Sleep Alarm Service.

FastAPI microservice that reads a sleep ("Dormir") Google Calendar event and
returns the wake time. Intended to be called by an iOS Shortcut at 05:00.

Auth: Google OAuth2 user credentials (stored refresh token) read the calendar
on behalf of the user, protected by a simple shared API key.

Endpoints:
    GET /health     -> {"ok": true, "timezone": "Europe/Lisbon"}
    GET /wake-time  -> {"wake_time": "07:30", "iso": "...", "hour": 7, "minute": 30}

Configuration (environment variables):
    ALARM_API_KEY        (required)  shared secret expected in the X-API-Key header
    GOOGLE_TOKEN_JSON    (required)  OAuth token JSON produced by extract_token.py
    TIMEZONE             (optional)  IANA name, default "Europe/Lisbon"
    CALENDAR_ID          (optional)  calendar to read, default "primary"
    EVENT_KEYWORD        (optional)  case-insensitive event title to match, default "Dormir"
    SEARCH_WINDOW_HOURS  (optional)  how many hours ahead to search, default 18
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import threading
from datetime import datetime, timedelta
from typing import Annotated, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import FastAPI, Header, HTTPException
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sleep-alarm")

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
DEFAULT_TIMEZONE = "Europe/Lisbon"
DEFAULT_CALENDAR_ID = "primary"
DEFAULT_EVENT_KEYWORD = "Dormir"
DEFAULT_WINDOW_HOURS = 18
TOKEN_URI = (
    "https://oauth2.googleapis.com/token"  # noqa: S105 - public OAuth endpoint, not a secret
)


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


def _require_env(name: str) -> str:
    """Return a required environment variable or raise :class:`ConfigError`."""
    value = os.environ.get(name)
    if not value:
        raise ConfigError(f"Missing required environment variable: {name}")
    return value


def load_config() -> dict[str, Any]:
    """Read and validate configuration from the environment.

    Raises:
        ConfigError: if anything required is missing or malformed.

    """
    api_key = _require_env("ALARM_API_KEY")
    token_raw = _require_env("GOOGLE_TOKEN_JSON")

    tz_name = os.environ.get("TIMEZONE", DEFAULT_TIMEZONE)
    try:
        tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        msg = (
            f"Invalid TIMEZONE '{tz_name}'. Use an IANA name like "
            f"'Europe/Lisbon' or 'America/New_York'."
        )
        raise ConfigError(msg) from exc

    try:
        token_data = json.loads(token_raw)
    except json.JSONDecodeError as exc:
        msg = "GOOGLE_TOKEN_JSON is not valid JSON."
        raise ConfigError(msg) from exc

    required_keys = ("refresh_token", "client_id", "client_secret")
    missing = [key for key in required_keys if not token_data.get(key)]
    if missing:
        msg = (
            f"GOOGLE_TOKEN_JSON is missing keys: {', '.join(missing)}. "
            f"Regenerate it with extract_token.py."
        )
        raise ConfigError(msg)

    try:
        window_hours = int(os.environ.get("SEARCH_WINDOW_HOURS", str(DEFAULT_WINDOW_HOURS)))
    except ValueError as exc:
        msg = "SEARCH_WINDOW_HOURS must be an integer."
        raise ConfigError(msg) from exc
    if window_hours <= 0:
        msg = "SEARCH_WINDOW_HOURS must be a positive integer."
        raise ConfigError(msg)

    return {
        "api_key": api_key,
        "token_data": token_data,
        "tz_name": tz_name,
        "tz": tz,
        "calendar_id": os.environ.get("CALENDAR_ID", DEFAULT_CALENDAR_ID),
        "event_keyword": os.environ.get("EVENT_KEYWORD", DEFAULT_EVENT_KEYWORD),
        "window_hours": window_hours,
    }


CONFIG = load_config()

app = FastAPI(title="Sleep Alarm Service")

# Credentials are built once and refreshed under a lock so concurrent requests
# (FastAPI runs sync endpoints in a threadpool) don't race on the refresh.
_creds_lock = threading.Lock()
_creds_cache: dict[str, Credentials] = {}


def _get_credentials() -> Credentials:
    """Return cached OAuth credentials, refreshing them if no longer valid."""
    with _creds_lock:
        creds = _creds_cache.get("creds")
        if creds is None:
            token = CONFIG["token_data"]
            creds = Credentials(
                token=token.get("token"),
                refresh_token=token["refresh_token"],
                token_uri=token.get("token_uri", TOKEN_URI),
                client_id=token["client_id"],
                client_secret=token["client_secret"],
                scopes=SCOPES,
            )
            _creds_cache["creds"] = creds
        if not creds.valid:
            creds.refresh(Request())
        return creds


def get_calendar_service() -> Any:  # noqa: ANN401 - google client is untyped
    """Build a Google Calendar API client from the cached credentials."""
    creds = _get_credentials()
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def parse_event_end(event: dict[str, Any], tz: ZoneInfo) -> datetime:
    """Return the event's end as an aware datetime in ``tz``.

    Handles timed events (``end.dateTime``, RFC3339 with offset) and all-day
    events (``end.date``, a bare ``YYYY-MM-DD`` treated as midnight in ``tz``).
    """
    end = event.get("end", {})
    end_raw = end.get("dateTime") or end.get("date")
    if not end_raw:
        raise HTTPException(status_code=502, detail="Event has no end time.")

    try:
        end_dt = datetime.fromisoformat(end_raw)
    except ValueError as exc:
        msg = f"Could not parse event end time: {end_raw!r}"
        raise HTTPException(status_code=502, detail=msg) from exc

    if end_dt.tzinfo is None:
        # All-day event (date only): anchor it to midnight in the configured tz.
        end_dt = end_dt.replace(tzinfo=tz)
    return end_dt.astimezone(tz)


@app.get("/health")
def health() -> dict[str, Any]:
    """Liveness probe; also reports the active timezone."""
    return {"ok": True, "timezone": CONFIG["tz_name"]}


@app.get("/wake-time")
def wake_time(x_api_key: Annotated[str, Header()] = "") -> dict[str, Any]:
    """Return the wake time derived from the next sleep event.

    Args:
        x_api_key: shared secret supplied in the ``X-API-Key`` header.

    Raises:
        HTTPException: 401 if unauthorized, 404 if no matching event,
            502 if the upstream calendar API fails.

    """
    if not secrets.compare_digest(x_api_key, CONFIG["api_key"]):
        raise HTTPException(status_code=401, detail="Unauthorized")

    tz: ZoneInfo = CONFIG["tz"]
    now = datetime.now(tz=tz)
    time_min = now.isoformat()
    time_max = (now + timedelta(hours=CONFIG["window_hours"])).isoformat()

    try:
        service = get_calendar_service()
        events_result = (
            service.events()
            .list(
                calendarId=CONFIG["calendar_id"],
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy="startTime",
                q=CONFIG["event_keyword"],
            )
            .execute()
        )
    except HttpError as exc:
        status = getattr(getattr(exc, "resp", None), "status", "?")
        logger.warning("Google Calendar API error (status=%s): %s", status, exc)
        raise HTTPException(status_code=502, detail="Upstream calendar API error.") from exc
    except GoogleAuthError as exc:
        logger.warning("Google auth/refresh failed: %s", exc)
        msg = "Calendar authentication failed. The token may be revoked or expired."
        raise HTTPException(status_code=502, detail=msg) from exc
    except Exception as exc:  # last-resort guard for network/timeout errors
        logger.exception("Unexpected error talking to Google Calendar")
        raise HTTPException(
            status_code=502, detail="Could not reach the calendar service."
        ) from exc

    events = events_result.get("items", [])
    keyword = CONFIG["event_keyword"].lower()
    event = next(
        (e for e in events if keyword in (e.get("summary") or "").lower()),
        None,
    )

    if event is None:
        detail = (
            f"No '{CONFIG['event_keyword']}' event found in the next " f"{CONFIG['window_hours']}h."
        )
        raise HTTPException(status_code=404, detail=detail)

    end_dt = parse_event_end(event, tz)

    return {
        "wake_time": end_dt.strftime("%H:%M"),
        "iso": end_dt.isoformat(),
        "hour": end_dt.hour,
        "minute": end_dt.minute,
    }
