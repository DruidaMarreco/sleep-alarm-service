# Sleep Alarm Service

A tiny FastAPI microservice that reads your **"Dormir"** Google Calendar event and
returns the wake time. Designed to be called by an iOS Shortcut at 05:00 so your
alarm can be set dynamically based on when you actually planned to wake up.

## How it works

1. You keep a calendar event titled **"Dormir"** (the sleep block) on your Google Calendar.
2. At 05:00, an iOS Shortcut calls `GET /wake-time` on this service.
3. The service finds the upcoming "Dormir" event and returns its **end time** — that's your wake time.
4. The Shortcut sets your alarm to that time.

## Endpoints

| Method | Path          | Auth                 | Returns |
|--------|---------------|----------------------|---------|
| GET    | `/health`     | none                 | `{ "ok": true }` |
| GET    | `/wake-time`  | `X-API-Key` header   | `{ "wake_time": "07:30", "iso": "...", "hour": 7, "minute": 30 }` |

## Project layout

```
sleep-alarm-service/
├── main.py            # FastAPI app
├── requirements.txt   # Python dependencies
├── railway.json       # Railway deploy config (Nixpacks)
├── Procfile           # Start command (uvicorn)
├── extract_token.py   # One-time OAuth helper to generate GOOGLE_TOKEN_JSON
├── SETUP.md           # This file
└── .gitignore
```

## Setup

### 1. Create Google OAuth credentials

1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Create (or pick) a project and enable the **Google Calendar API**.
3. Create an **OAuth 2.0 Client ID** of type **Desktop App**.
4. Download the JSON and save it next to `extract_token.py` as `client_secret.json`.

### 2. Generate the token (run once, locally)

```bash
pip install google-auth-oauthlib
python extract_token.py
```

A browser opens; authorize **read-only** calendar access. The script prints a JSON
string — copy it. You'll paste it as the `GOOGLE_TOKEN_JSON` environment variable.

> `client_secret.json` and the printed token are secrets. They are git-ignored — never commit them.

### 3. Deploy to Railway

1. Push this repo to GitHub and create a new Railway project from it
   (Railway auto-detects `railway.json` / `Procfile`).
2. Set these environment variables in Railway:

   | Variable              | Required | Value |
   |-----------------------|----------|-------|
   | `ALARM_API_KEY`       | yes      | any strong random string (your shared secret) |
   | `GOOGLE_TOKEN_JSON`   | yes      | the JSON string printed by `extract_token.py` |
   | `TIMEZONE`            | no       | IANA timezone name, e.g. `Europe/Lisbon`, `America/New_York`. Defaults to `Europe/Lisbon`. |
   | `CALENDAR_ID`         | no       | which calendar to read. Defaults to `primary`. |
   | `EVENT_KEYWORD`       | no       | case-insensitive event title to match. Defaults to `Dormir`. |
   | `SEARCH_WINDOW_HOURS` | no       | how many hours ahead to search. Defaults to `18`. |

   Invalid config (missing required vars, a bad `TIMEZONE`, malformed `GOOGLE_TOKEN_JSON`,
   or a non-integer `SEARCH_WINDOW_HOURS`) fails fast at startup with a clear error,
   so a misconfigured deploy won't silently serve broken responses.

3. Deploy. Note your public URL, e.g. `https://your-service.up.railway.app`.

### 4. Test

```bash
curl https://your-service.up.railway.app/health
# {"ok":true}

curl -H "X-API-Key: YOUR_ALARM_API_KEY" \
     https://your-service.up.railway.app/wake-time
# {"wake_time":"07:30","iso":"2026-06-08T07:30:00+01:00","hour":7,"minute":30}
```

### 5. iOS Shortcut

Create a Shortcut that runs at 05:00 (via an Automation):

1. **Get Contents of URL** → `https://your-service.up.railway.app/wake-time`
   - Method: `GET`
   - Header: `X-API-Key` = your `ALARM_API_KEY`
2. **Get Dictionary Value** → `hour` and `minute` from the response.
3. **Set Alarm** (or **Create Alarm**) using those values.

## Local development

```bash
pip install -r requirements.txt
export ALARM_API_KEY=dev-secret          # PowerShell: $env:ALARM_API_KEY="dev-secret"
export GOOGLE_TOKEN_JSON='<token json>'  # PowerShell: $env:GOOGLE_TOKEN_JSON='...'
export TIMEZONE=Europe/Lisbon            # optional; PowerShell: $env:TIMEZONE="Europe/Lisbon"
uvicorn main:app --reload
```

Then visit http://127.0.0.1:8000/docs for the interactive API.

## Notes & caveats

- **Timezone** is set via the `TIMEZONE` env var (any IANA name), defaulting to `Europe/Lisbon`.
- The search window is **now → +18h**, so it picks up tonight's sleep into tomorrow morning.
- Matching is by the substring `"dormir"` (case-insensitive) in the event summary.
