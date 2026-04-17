# Voice Scheduling Agent

FastAPI backend + web client for authenticated voice-based meeting scheduling.

## What It Does
- Handles Google OAuth login/session.
- Accepts VAPI tool webhooks to create calendar events.
- Exposes calendar read endpoints.
- Stores user profile defaults (`default_city`, `timezone`).
- Provides meetings summary endpoints by delegating weather scoring to `weather-agent`.

## Scope
This repository owns:
- Auth/session + profile persistence
- Calendar event creation and listing
- VAPI webhook integration (`create-event`, `meetings-weather-summary`)
- Frontend pages (`/login`, `/assistant`) and VAPI SDK bootstrap

It integrates with:
- Google Calendar API
- `weather-agent` internal API (`/internal/meeting-weather-summary`)

## API Surface
Defined in `app/main.py`.

### UI/Auth
- `GET /` -> redirect to `/login`
- `GET /login`
- `GET /assistant`
- `GET /auth/google/login`
- `GET /auth/google/callback`
- `GET /auth/me`
- `POST /auth/logout`

### Profile
- `GET /profile`
- `PUT /profile`
- `GET /internal/profile/{sub}`

### Calendar + Voice Tools
- `POST /create-event`
- `GET /events`
- `GET /internal/events`
- `POST /meetings-weather-summary`
- `GET /internal/meetings-weather-summary`

### Health
- `GET /health`
- `HEAD /health`

## Tool Contracts
### `createCalendarEvent`
Expected arguments:
- `name`, `date`, `time`
- `meeting_mode` (`online` or `in_person`)
- `location` (optional display location)
- `city` (optional weather city; backend falls back to profile default city for in-person)
- `user_sub` (required for server-to-server calls)

### `getMeetingsSummary`
Expected arguments:
- `user_sub` (required)
- `date` (`YYYY-MM-DD`, optional)
- `timezone` (optional, default `Europe/Berlin`)

## Integration With `weather-agent`
Summary flow:
1. `POST /meetings-weather-summary` receives tool call.
2. Backend validates auth/internal key + resolves `user_sub`.
3. Backend calls `GET {WEATHER_AGENT_BASE_URL}/internal/meeting-weather-summary`.
4. Returns `summary_text` back to VAPI tool result.

## Configuration
Use `example.env` as reference.

Required variables:
```env
CALENDAR_ID=
SERVICE_ACCOUNT_JSON=
GOOGLE_OAUTH_CLIENT_ID=
GOOGLE_OAUTH_CLIENT_SECRET=
APP_SECRET_KEY=
INTERNAL_API_KEY=
WEATHER_AGENT_BASE_URL=
WEATHER_AGENT_INTERNAL_API_KEY=
WEATHER_AGENT_TIMEOUT_SECONDS=20
VAPI_PUBLIC_KEY=
APP_DB_PATH=app.db
```

## Run
```bash
python -m uvicorn app.main:app --reload
```

## Tests
```bash
python -m pytest -q
```

## Notes
- Server-to-server calls require `X-Internal-API-Key`.
- Browser login session does not replace server-to-server auth headers.
- `user_sub` must be passed to tool calls (directly or via assistant variable mapping).
