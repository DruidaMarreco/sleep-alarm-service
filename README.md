# Sleep Alarm Service

[![CI](https://github.com/DruidaMarreco/sleep-alarm-service/actions/workflows/ci.yml/badge.svg)](https://github.com/DruidaMarreco/sleep-alarm-service/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11-blue)
![Coverage](https://img.shields.io/badge/coverage-100%25-brightgreen)

A tiny, production-hardened **FastAPI** microservice that reads a sleep
(**"Dormir"**) event from your Google Calendar and returns the wake time.
Designed to be called by an **iOS Shortcut at 05:00** so your alarm is set
dynamically to whenever you actually planned to wake up.

```
05:00  iOS Shortcut ──GET /wake-time──▶  this service ──▶  Google Calendar
                                              │
                   { "hour": 7, "minute": 30 } ◀──┘
                          │
              Shortcut sets your alarm to 07:30
```

## How it works

1. You keep a calendar event titled **"Dormir"** (your sleep block).
2. At 05:00 an iOS Shortcut calls `GET /wake-time`.
3. The service finds the upcoming "Dormir" event and returns its **end time** — your wake time.
4. The Shortcut sets your alarm accordingly.

## Endpoints

| Method | Path         | Auth               | Response |
|--------|--------------|--------------------|----------|
| GET    | `/health`    | none               | `{ "ok": true, "timezone": "Europe/Lisbon" }` |
| GET    | `/wake-time` | `X-API-Key` header | `{ "wake_time": "07:30", "iso": "...", "hour": 7, "minute": 30 }` |

Error responses: `401` (bad/missing key), `404` (no matching event in the window),
`502` (calendar API/auth/network failure — never a raw 500).

## Configuration

All configuration is via environment variables. Invalid config **fails fast at
startup** with a clear message, so a misconfigured deploy can't silently serve
broken responses.

| Variable              | Required | Default          | Description |
|-----------------------|----------|------------------|-------------|
| `ALARM_API_KEY`       | ✅       | —                | Shared secret expected in the `X-API-Key` header |
| `GOOGLE_TOKEN_JSON`   | ✅       | —                | OAuth token JSON produced by `extract_token.py` |
| `TIMEZONE`            | ❌       | `Europe/Lisbon`  | IANA timezone name (e.g. `America/New_York`) |
| `CALENDAR_ID`         | ❌       | `primary`        | Which calendar to read |
| `EVENT_KEYWORD`       | ❌       | `Dormir`         | Case-insensitive event title to match |
| `SEARCH_WINDOW_HOURS` | ❌       | `18`             | How many hours ahead to search |

## Quick start (local)

```bash
python -m venv .venv && . .venv/Scripts/activate    # PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt

# PowerShell:
$env:ALARM_API_KEY = "dev-secret"
$env:GOOGLE_TOKEN_JSON = '<token json from extract_token.py>'
uvicorn main:app --reload
```

Then open http://127.0.0.1:8000/docs for the interactive API.

## Generating the Google token

1. In the [Google Cloud Console](https://console.cloud.google.com/), enable the
   **Google Calendar API** and create an **OAuth 2.0 Client ID** (type: *Desktop App*).
2. Download it as `client_secret.json` next to `extract_token.py`.
3. Run the one-time helper:

   ```bash
   pip install google-auth-oauthlib
   python extract_token.py
   ```

   Authorize read-only calendar access; copy the printed JSON into `GOOGLE_TOKEN_JSON`.

> `client_secret.json` and the token are secrets — they are git-ignored. Never commit them.

## Deploy (Railway)

1. Push to GitHub and create a Railway project from the repo
   (it auto-detects `railway.json` / `Procfile`, Python pinned via `.python-version`).
2. Set `ALARM_API_KEY` and `GOOGLE_TOKEN_JSON` (and optionally the others above).
3. Deploy, then test:

   ```bash
   curl https://<your-app>.up.railway.app/health
   curl -H "X-API-Key: $ALARM_API_KEY" https://<your-app>.up.railway.app/wake-time
   ```

## iOS Shortcut

Create an Automation that runs at 05:00:

1. **Get Contents of URL** → `https://<your-app>.up.railway.app/wake-time`,
   method `GET`, header `X-API-Key` = your key.
2. **Get Dictionary Value** → `hour` and `minute`.
3. **Create Alarm** using those values.

## Development

This repo is held to a strict quality bar, enforced in CI:

| Tool     | Purpose            | Config                          |
|----------|--------------------|---------------------------------|
| `black`  | formatting         | `pyproject.toml` (`--check` in CI) |
| `ruff`   | linting            | `select = ["ALL"]`              |
| `ty`     | type checking      | Astral type checker             |
| `pytest` | tests + coverage   | `--strict-markers`, `--cov-fail-under=90` (currently 100%) |

Run the whole suite locally:

```bash
black --check .
ruff check .
ty check
pytest
```

### Branching model

```
main ──── stable / deployable
  └── dev ──── integration branch
        └── feature/* ──── one branch per feature, PR'd into dev
```

Every feature branches off `dev` and is merged back via PR. `dev` is promoted to
`main` when ready to release.

## Project layout

```
sleep-alarm-service/
├── main.py              # FastAPI app
├── extract_token.py     # One-time OAuth helper
├── requirements.txt     # Runtime deps (used by Railway)
├── requirements-dev.txt # Dev/CI deps
├── pyproject.toml       # black / ruff / ty / pytest config
├── railway.json         # Railway deploy config
├── Procfile             # Start command
├── .python-version      # Pins Python 3.11
├── tests/               # pytest suite (mocks the Google API)
├── .github/workflows/   # CI pipeline
├── SETUP.md             # Detailed setup walkthrough
└── README.md
```

## License

Personal project — no license specified.
