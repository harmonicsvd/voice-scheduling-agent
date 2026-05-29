"""FastAPI backend for auth, calendar tools, and weather-summary delegation."""

import hmac
import json
from contextlib import asynccontextmanager
import logging
from fastapi import FastAPI, Request, Query, Header
from pathlib import Path
from fastapi.responses import JSONResponse, Response, RedirectResponse, FileResponse

from app.config import settings
from app.google_clients import get_calendar_service, build_oauth

from pydantic import BaseModel, Field, ValidationError
from typing import Literal, Any

from app.db import init_db, get_db, db_execute



from datetime import datetime, timedelta, timezone
import httpx
import time

import re
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware



@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize persistent resources once at process startup."""
    init_db()   # runs once when server starts
    yield       # app serves requests here
    # optional cleanup when server stops

app = FastAPI(lifespan=lifespan)
logger = logging.getLogger(__name__)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://voice-scheduling-agent-pi.vercel.app",
        "http://localhost:3000",
        "http://127.0.0.1:5500",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
   
)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.app_secret_key,
    same_site="lax",
    https_only=False,  # local dev
)


oauth = build_oauth()

BASE_DIR = Path(__file__).resolve().parent.parent
LOGIN_HTML = BASE_DIR / "login.html"
SETUP_HTML = BASE_DIR / "setup.html"
VOICE_HTML = BASE_DIR / "index.html"


class ProfileUpdate(BaseModel):
    """Validated payload for updating user profile preferences."""
    role: str = Field(min_length=2, max_length=80)
    default_city: str = Field(min_length=2, max_length=80)
    timezone: str = Field(default="Europe/Berlin", min_length=3, max_length=80)
    commute_mode: str = Field(min_length=2, max_length=40)
    risk_tolerance: str = Field(min_length=2, max_length=20)
    ppe_required: bool = False


class CreateEventArguments(BaseModel):
    """Arguments expected from VAPI create-event tool call."""
    name: str = Field(min_length=1)
    date: str
    time: str
    title: str = "Meeting"
    duration: str = "1 hour"
    meeting_mode: Literal["online", "in_person"]
    location: str | None = None
    city: str | None = None
    user_sub: str | None = None


class CreateEventFunctionPayload(BaseModel):
    """Wrapper for tool call `function.arguments` payload."""
    arguments: Any


class CreateEventToolCall(BaseModel):
    """Single tool call item from VAPI message envelope."""
    id: str
    function: CreateEventFunctionPayload


class CreateEventMessage(BaseModel):
    """VAPI message envelope containing one or more tool calls."""
    toolCalls: list[CreateEventToolCall] = Field(default_factory=list)


class CreateEventRequest(BaseModel):
    """Top-level create-event webhook body contract."""
    message: CreateEventMessage
    
def _parse_create_event_arguments(raw_arguments: dict) -> CreateEventArguments:
    """Support Pydantic v1/v2 parsing with one compatibility helper."""
    if hasattr(CreateEventArguments, "model_validate"):
        return CreateEventArguments.model_validate(raw_arguments)
    return CreateEventArguments.parse_obj(raw_arguments)


class MeetingsSummaryArguments(BaseModel):
    """Arguments expected from VAPI meetings-summary tool call."""
    user_sub: str | None = None
    date: str | None = None  # YYYY-MM-DD
    timezone: str = "Europe/Berlin"


def _parse_meetings_summary_arguments(raw_arguments: dict) -> MeetingsSummaryArguments:
    """Support Pydantic v1/v2 parsing for meetings-summary arguments."""
    if hasattr(MeetingsSummaryArguments, "model_validate"):
        return MeetingsSummaryArguments.model_validate(raw_arguments)
    return MeetingsSummaryArguments.parse_obj(raw_arguments)


def _extract_user_sub(raw_payload: dict, explicit_sub: str | None) -> str | None:
    """
    Resolve `user_sub` from explicit args or common VAPI override locations.

    Keeps backend resilient to slight payload-shape differences between
    dashboard tool tests, live calls, and SDK wrapper variants.
    """
    # Priority 1: explicit argument from parsed tool input.
    candidate = (explicit_sub or "").strip()
    if candidate:
        return candidate

    # Priority 2: common VAPI override/metadata locations.
    direct_paths = [
        raw_payload.get("user_sub"),
        (((raw_payload.get("assistantOverrides") or {}).get("variableValues") or {}).get("user_sub")),
        (((raw_payload.get("assistant_overrides") or {}).get("variable_values") or {}).get("user_sub")),
        (((raw_payload.get("message") or {}).get("assistantOverrides") or {}).get("variableValues", {}).get("user_sub")),
        (((raw_payload.get("call") or {}).get("assistantOverrides") or {}).get("variableValues", {}).get("user_sub")),
        (((raw_payload.get("call") or {}).get("assistantOverrides") or {}).get("metadata", {}).get("user_sub")),
        (((raw_payload.get("assistantOverrides") or {}).get("metadata") or {}).get("user_sub")),
    ]
    for value in direct_paths:
        if isinstance(value, str) and value.strip():
            return value.strip()

    # Priority 3: deep recursive search as final fallback for payload variants.
    def _walk(value: Any) -> str | None:
        """Recursively search nested dict/list payloads for any `user_sub` field."""
        if isinstance(value, dict):
            maybe = value.get("user_sub")
            if isinstance(maybe, str) and maybe.strip():
                return maybe.strip()
            for nested in value.values():
                found = _walk(nested)
                if found:
                    return found
        elif isinstance(value, list):
            for nested in value:
                found = _walk(nested)
                if found:
                    return found
        return None

    return _walk(raw_payload)


async def _fetch_meetings_summary_from_weather_agent(
    *,
    user_sub: str,
    target_date: str | None,
    timezone_name: str,
) -> dict[str, Any]:
    """
    Call weather-agent internal summary endpoint and validate minimal contract.

    This function is the cross-service boundary between voice backend and
    weather reasoning backend.
    """
    # Voice backend delegates weather reasoning to weather-agent API.
    if not settings.weather_agent_base_url:
        raise RuntimeError("WEATHER_AGENT_BASE_URL is not configured.")
    if not settings.weather_agent_internal_api_key:
        raise RuntimeError("WEATHER_AGENT_INTERNAL_API_KEY is not configured.")

    params: dict[str, str] = {
        "user_sub": user_sub,
        "tz": timezone_name,
    }
    if target_date:
        params["date"] = target_date
    started = time.perf_counter()
    status_code: int | None = None
    try:
        async with httpx.AsyncClient(timeout=settings.weather_agent_timeout_seconds) as client:
            response = await client.get(
                f"{settings.weather_agent_base_url}/internal/meeting-weather-summary",
                params=params,
                headers={"X-Internal-API-Key": settings.weather_agent_internal_api_key},
            )
            status_code = response.status_code
            response.raise_for_status()
            payload = response.json()

        if not isinstance(payload, dict):
            raise RuntimeError("Weather agent returned invalid summary payload.")
        if "summary_text" not in payload:
            raise RuntimeError("Weather agent response missing summary_text.")
        return payload
    finally:
        elapsed_ms = (time.perf_counter() - started) * 1000
        logger.info(
            "weather_delegate_done user_sub=%s date=%s tz=%s status=%s elapsed_ms=%.1f timeout_s=%.1f",
            user_sub,
            target_date,
            timezone_name,
            status_code,
            elapsed_ms,
            settings.weather_agent_timeout_seconds,
        )


@app.get("/login")
async def login_page(request: Request):
    """Serve login UI entrypoint."""
    return FileResponse(LOGIN_HTML)

@app.get("/assistant")
async def assistant_page(request: Request):
    """Serve assistant UI only for authenticated sessions."""
    user, _ = get_current_user_or_401(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    if not user.get("sub"):
        request.session.clear()
        return RedirectResponse(url="/login", status_code=302)
    if not _is_profile_complete(_get_profile_row(user["sub"])):
        return RedirectResponse(url="/setup", status_code=302)
    return FileResponse(VOICE_HTML)


@app.get("/setup")
async def setup_page(request: Request):
    """Serve onboarding UI for authenticated users who still need profile setup."""
    user, _ = get_current_user_or_401(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    if not user.get("sub"):
        request.session.clear()
        return RedirectResponse(url="/login", status_code=302)
    if _is_profile_complete(_get_profile_row(user["sub"])):
        return RedirectResponse(url="/assistant", status_code=302)
    return FileResponse(SETUP_HTML)


@app.get("/profile")
async def get_profile(request: Request):
    """Return current user profile from SQLite for authenticated browser user."""
    user, error = get_current_user_or_401(request)
    if error:
        return error

    row = _get_profile_row(user["sub"])

    if not row:
        return {"has_profile": False, "is_setup_complete": False, "profile": None}

    return {
        "has_profile": True,
        "is_setup_complete": _is_profile_complete(row),
        "profile": dict(row),
    }

@app.put("/profile")
async def put_profile(payload: ProfileUpdate, request: Request):
    """Upsert current user profile preferences."""
    user, error = get_current_user_or_401(request)
    if error:
        return error

    updated_at = datetime.now(timezone.utc).isoformat()

    with get_db() as conn:
        db_execute(
            conn,
            """
            INSERT INTO user_profiles (
                sub, email, default_city, timezone, role, commute_mode,
                ppe_required, risk_tolerance, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT(sub) DO UPDATE SET
                email = excluded.email,
                default_city = excluded.default_city,
                timezone = excluded.timezone,
                role = excluded.role,
                commute_mode = excluded.commute_mode,
                ppe_required = excluded.ppe_required,
                risk_tolerance = excluded.risk_tolerance,
                updated_at = excluded.updated_at
            """,
            (
                user["sub"],
                user.get("email", ""),
                payload.default_city.strip(),
                payload.timezone.strip(),
                payload.role.strip(),
                payload.commute_mode.strip(),
                payload.ppe_required,
                payload.risk_tolerance.strip(),
                updated_at,
            ),
        )

    return {"ok": True}

def require_internal_api_key(x_internal_api_key: str | None):
    """Guard internal endpoints with constant-time API key comparison."""
    if not settings.internal_api_key:
        return JSONResponse({"error": "internal api key not configured"}, status_code=500)
    if not x_internal_api_key or not hmac.compare_digest(x_internal_api_key, settings.internal_api_key):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    return None

@app.get("/internal/profile/{sub}")
async def get_internal_profile(
    sub: str,
    x_internal_api_key: str | None = Header(default=None),
):
    """Internal endpoint for backend callers to fetch profile by Google `sub`."""
    err = require_internal_api_key(x_internal_api_key)
    if err:
        return err

    with get_db() as conn:
        row = db_execute(
            conn,
            """
            SELECT sub, email, default_city, timezone, role, commute_mode, ppe_required, risk_tolerance, updated_at
            FROM user_profiles
            WHERE sub = %s
            """,
            (sub,),
        ).fetchone()

    if not row:
        return JSONResponse({"error": "profile_not_found"}, status_code=404)

    return {"profile": dict(row)}

def parse_duration_to_minutes(duration_str):
    """Convert natural duration text into integer minutes."""
    duration_str = duration_str.lower()
    
    # Convert word numbers to digits 
    word_to_num = {
        "one": "1", "two": "2", "three": "3", "four": "4",
        "half": "30 min", "thirty": "30", "forty five": "45",
        "twenty": "20", "fifteen": "15", "ninety": "90"
    }
    
    for word, num in word_to_num.items():
        duration_str = duration_str.replace(word, num)
    
    hours = re.search(r'(\d+\.?\d*)\s*hour', duration_str)
    minutes = re.search(r'(\d+)\s*min', duration_str)
    
    total_minutes = 0
    if hours:
        total_minutes += float(hours.group(1)) * 60
    if minutes:
        total_minutes += int(minutes.group(1))
    
    return int(total_minutes) if total_minutes > 0 else 60  # default 60 mins


def _derive_city_from_location(location: str | None) -> str | None:
    """
    Best-effort extraction of a city token from a free-form venue string.
    Examples:
    - "Berlin Office" -> "Berlin"
    - "Friedrichstrasse 10, Berlin" -> "Berlin"
    """
    if not location:
        return None

    text = location.strip()
    if not text:
        return None

    # Prefer trailing segment in comma-separated addresses.
    candidate = text.split(",")[-1].strip() or text
    candidate = re.sub(
        r"\b(office|hq|headquarters|campus|site|building|floor|room|client)\b",
        "",
        candidate,
        flags=re.IGNORECASE,
    )
    candidate = re.sub(r"[^A-Za-z\s\-']", " ", candidate)
    candidate = re.sub(r"\s+", " ", candidate).strip()

    if not candidate:
        return None

    # Preserve common city capitalization format.
    return candidate.title()




@app.get("/vapi-key")
async def get_vapi_key():
    """Return public VAPI key used by browser client."""
    return JSONResponse(content={
        "apiKey": settings.vapi_public_key
    })

@app.get("/")
def root():
    """Default root route redirects users to login."""
    return RedirectResponse(url="/login", status_code=302)


@app.head("/")
def root_head():
    """HEAD probe for root path (used by some hosting health checks)."""
    return Response(status_code=200)


@app.get("/health")
def health():
    """Simple liveness endpoint."""
    return {"ok": True}


@app.head("/health")
def health_head():
    """HEAD variant for liveness checks."""
    return Response(status_code=200)

@app.post("/create-event")
async def create_event(
    request: Request,
    x_internal_api_key: str | None = Header(default=None),
):
    """
    VAPI tool webhook endpoint.
    Accepts tool-call payload, validates args, resolves weather city metadata,
    and creates a Google Calendar event.
    """
    raw_payload = await request.json()
    message_preview = raw_payload.get("message") or {}
    tool_calls_preview = message_preview.get("toolCalls") or message_preview.get("tool_calls") or []
    print(
        "Received /create-event webhook: "
        f"tool_calls={len(tool_calls_preview)} "
        f"has_assistant_overrides={bool(raw_payload.get('assistantOverrides'))}"
    )

    try:
        message = raw_payload.get("message") or {}
        tool_calls = message.get("toolCalls") or message.get("tool_calls") or []
        if not tool_calls:
            return JSONResponse(
                content={"error": "No tool calls found"},
                status_code=400
            )

        tool_call = tool_calls[0] or {}
        function_payload = tool_call.get("function") or {}
        raw_arguments = function_payload.get("arguments")
        if isinstance(raw_arguments, str):
            raw_arguments = json.loads(raw_arguments)
        if not isinstance(raw_arguments, dict):
            return JSONResponse(
                content={"error": "Invalid function.arguments payload"},
                status_code=400,
            )
        arguments = _parse_create_event_arguments(raw_arguments)

        # Web browser flow: session-authenticated user.
        # VAPI server-to-server flow: internal API key + user_sub in payload.
        user, _ = get_current_user_or_401(request)
        if not user:
            internal_err = require_internal_api_key(x_internal_api_key)
            if internal_err:
                return JSONResponse({"error": "authentication required"}, status_code=401)

        name = (arguments.name or "").strip()
        date = (arguments.date or "").strip()
        time = (arguments.time or "").strip()
        title = (arguments.title or "").strip() or "Meeting"
        duration = (arguments.duration or "").strip() or "1 hour"
        meeting_mode = arguments.meeting_mode
        requested_city = (arguments.city or "").strip() or None
        caller_sub = user.get("sub") if user else _extract_user_sub(raw_payload, arguments.user_sub)
        location = (arguments.location or "").strip() or None

        if not name:
            return JSONResponse(content={"error": "name is required"}, status_code=400)
        if not date:
            return JSONResponse(content={"error": "date is required"}, status_code=400)
        if not time:
            return JSONResponse(content={"error": "time is required"}, status_code=400)
        if not caller_sub:
            return JSONResponse(
                content={
                    "error": "user_sub is required for server-to-server calls",
                    "hint": "Pass assistantOverrides.variableValues.user_sub and map tool arg user_sub to {{user_sub}}",
                },
                status_code=400,
            )

        resolved_city = None
        city_source = None

        if meeting_mode == "in_person":
            if requested_city:
                resolved_city = requested_city
                city_source = "provided"
            else:
                profile_city = _lookup_profile_city(caller_sub)
                if profile_city:
                    resolved_city = profile_city
                    city_source = "profile_default"
                else:
                    return JSONResponse(
                        content={"error": "city is required for in-person meetings (or set default city in profile)"},
                        status_code=400,
                    )


        print(f"Creating event for: {name}, {date}, {time}, {title}, {duration}")

        # Parse date and time
        event_datetime_str = f"{date} {time}"
        event_start = datetime.strptime(event_datetime_str, "%Y-%m-%d %H:%M")

        # Parse duration naturally
        duration_minutes = parse_duration_to_minutes(duration)
        event_end = event_start + timedelta(minutes=duration_minutes)

        print(f"Duration: {duration_minutes} minutes")

        # Create Google Calendar event
        service = get_calendar_service()
        metadata_parts = [
            f"meeting_mode:{meeting_mode}",
        ]
        if caller_sub:
            metadata_parts.append(f"user_sub:{caller_sub}")
        if resolved_city:
            metadata_parts.append(f"weather_city:{resolved_city}")
        if city_source:
            metadata_parts.append(f"city_source:{city_source}")

        event = {
            'summary': title,
            'description': (
                f"Scheduled by {name} via Voice Scheduling Agent. "
                f"{'; '.join(metadata_parts)}"
            ),

            'start': {
                'dateTime': event_start.isoformat(),
                'timeZone': 'Europe/Berlin',
            },
            'end': {
                'dateTime': event_end.isoformat(),
                'timeZone': 'Europe/Berlin',
            },
        }
        if location:
            event["location"] = location
            
        created_event = service.events().insert(
            calendarId=settings.calendar_id,
            body=event
        ).execute()

        print(f"Event created: {created_event.get('htmlLink')}")

        return JSONResponse(content={
            "results": [{
                "toolCallId": tool_call.get("id", ""),
                "result": f"Calendar event '{title}' has been successfully created for {name} on {date} at {time} for {duration}."
            }]
        })

    except ValidationError as e:
        return JSONResponse(
            content={"error": "invalid create-event arguments", "details": e.errors()},
            status_code=422,
        )
    except Exception as e:
        print("Error:", e)
        return JSONResponse(
            content={"error": str(e)},
            status_code=500
        )

def _list_events_payload(from_iso: str, to_iso: str) -> dict:
    """Unified event reader used by both public `/events` and internal `/internal/events`."""
    service = get_calendar_service()
    response = (
        service.events()
        .list(
            calendarId=settings.calendar_id,
            timeMin=from_iso,
            timeMax=to_iso,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )

    items = response.get("items", [])
    events = []
    for e in items:
        start = (e.get("start") or {}).get("dateTime") or (e.get("start") or {}).get("date")
        end = (e.get("end") or {}).get("dateTime") or (e.get("end") or {}).get("date")
        location = e.get("location")
        description_raw = e.get("description") or ""
        description = description_raw.lower()
        user_sub_match = re.search(r"\buser_sub:([0-9]+)\b", description_raw)
        user_sub = user_sub_match.group(1) if user_sub_match else None
        weather_city_match = re.search(r"\bweather_city:([^;]+)", description_raw)
        weather_city = weather_city_match.group(1).strip() if weather_city_match else None
        city_source_match = re.search(r"\bcity_source:([^;]+)", description_raw)
        city_source = city_source_match.group(1).strip() if city_source_match else None

        meeting_mode = "unknown"
        if "meeting_mode:online" in description:
            meeting_mode = "online"
        elif "meeting_mode:in_person" in description:
            meeting_mode = "in_person"

        # Backward compatibility for old calendar events that were created
        # before weather_city metadata existed.
        if not weather_city and meeting_mode == "in_person" and location:
            legacy_city = _derive_city_from_location(location)
            if legacy_city:
                weather_city = legacy_city
                if not city_source:
                    city_source = "legacy_from_location"

        heuristic_virtual = (
            ("zoom" in (location or "").lower())
            or ("meet.google.com" in description)
            or ("teams" in description)
        )

        if meeting_mode == "online":
            is_virtual = True
        elif meeting_mode == "in_person":
            is_virtual = False
        else:
            is_virtual = heuristic_virtual

        summary = e.get("summary", "Untitled")

        events.append(
            {
                "title": summary,
                "start": start,
                "end": end,
                "location": location,
                "city": weather_city,
                "city_source": city_source,
                "meeting_mode": meeting_mode,
                "is_virtual": is_virtual,
                "user_sub": user_sub,
            }
        )

    return {"events": events}


@app.get("/events")
async def list_events(
    request: Request,
    from_iso: str = Query(..., description="ISO start datetime"),
    to_iso: str = Query(..., description="ISO end datetime"),
):
    """Browser-authenticated calendar listing endpoint."""
    user, error = get_current_user_or_401(request)
    if error:
        return error

    try:
        return _list_events_payload(from_iso, to_iso)
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.get("/internal/events")
async def list_events_internal(
    from_iso: str = Query(..., description="ISO start datetime"),
    to_iso: str = Query(..., description="ISO end datetime"),
    x_internal_api_key: str | None = Header(default=None),
):
    """Internal calendar listing endpoint for backend callers."""
    err = require_internal_api_key(x_internal_api_key)
    if err:
        return err

    try:
        return _list_events_payload(from_iso, to_iso)
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.post("/meetings-weather-summary")
async def meetings_weather_summary(
    request: Request,
    x_internal_api_key: str | None = Header(default=None),
):
    """
    VAPI tool endpoint for "what are my meetings" requests.
    Delegates summary generation to weather-agent internal API.
    """
    raw_payload = await request.json()
    req_started = time.perf_counter()
    try:
        message = raw_payload.get("message") or {}
        tool_calls = message.get("toolCalls") or message.get("tool_calls") or []
        tool_call_id = ""

        if tool_calls:
            tool_call = tool_calls[0] or {}
            tool_call_id = tool_call.get("id", "")
            function_payload = tool_call.get("function") or {}
            raw_arguments = function_payload.get("arguments") or {}
        else:
            # Allow direct JSON body for local/manual testing without VAPI wrapper.
            raw_arguments = raw_payload

        if isinstance(raw_arguments, str):
            raw_arguments = json.loads(raw_arguments)

        if not isinstance(raw_arguments, dict):
            return JSONResponse(
                content={"error": "Invalid arguments payload"},
                status_code=400,
            )

        arguments = _parse_meetings_summary_arguments(raw_arguments)

        user, _ = get_current_user_or_401(request)
        if user:
            caller_sub = user.get("sub")
        else:
            internal_err = require_internal_api_key(x_internal_api_key)
            if internal_err:
                return JSONResponse({"error": "authentication required"}, status_code=401)
            caller_sub = _extract_user_sub(raw_payload, arguments.user_sub)

        if not caller_sub:
            return JSONResponse(
                content={
                    "error": "user_sub is required for server-to-server calls",
                    "hint": "Pass assistantOverrides.variableValues.user_sub and map tool arg user_sub to {{user_sub}}",
                },
                status_code=400,
            )

        summary = await _fetch_meetings_summary_from_weather_agent(
            user_sub=caller_sub,
            target_date=arguments.date,
            timezone_name=arguments.timezone,
        )

        if tool_call_id:
            return JSONResponse(
                content={
                    "results": [
                        {
                            "toolCallId": tool_call_id,
                            "result": summary["summary_text"],
                        }
                    ],
                    "data": summary,
                }
            )

        return JSONResponse(content=summary)
    

    except ValueError as e:
        return JSONResponse(content={"error": str(e)}, status_code=400)
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)
    finally:
         total_ms = (time.perf_counter() - req_started) * 1000
         logger.info("meetings_weather_summary_done elapsed_ms=%.1f", total_ms)


@app.get("/internal/meetings-weather-summary")
async def meetings_weather_summary_internal(
    user_sub: str = Query(..., description="Google user sub"),
    date: str | None = Query(default=None, description="YYYY-MM-DD"),
    tz: str = Query(default="Europe/Berlin", description="IANA timezone"),
    x_internal_api_key: str | None = Header(default=None),
):
    """Internal pass-through summary endpoint for trusted backend consumers."""
    err = require_internal_api_key(x_internal_api_key)
    if err:
        return err

    try:
        return await _fetch_meetings_summary_from_weather_agent(
            user_sub=user_sub,
            target_date=date,
            timezone_name=tz,
        )
    except ValueError as e:
        return JSONResponse(content={"error": str(e)}, status_code=400)
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.get("/auth/google/login")
async def auth_google_login(request: Request):
    """Start Google OAuth browser redirect flow."""
    redirect_uri = request.url_for("auth_google_callback")
    return await oauth.google.authorize_redirect(request, redirect_uri)


@app.get("/auth/google/callback")
async def auth_google_callback(request: Request):
    """Handle Google OAuth callback and persist session identity."""
    token = await oauth.google.authorize_access_token(request)
    user_info = token.get("userinfo")

    if not user_info:
        user_info = await oauth.google.parse_id_token(request, token)

    request.session["user"] = {
        "sub": user_info.get("sub"),
        "email": user_info.get("email"),
        "name": user_info.get("name"),
        "picture": user_info.get("picture"),
    }
    request.session["token"] = {
        "access_token": token.get("access_token"),
        "expires_at": token.get("expires_at"),
    }

    user_sub = request.session["user"].get("sub", "")
    destination = "/assistant" if _is_profile_complete(_get_profile_row(user_sub)) else "/setup"
    return RedirectResponse(url=f"{destination}?user_sub={user_sub}", status_code=302)


@app.get("/auth/me")
async def auth_me(request: Request):
    """Return current session user data for frontend bootstrapping."""
    user = request.session.get("user")
    if not user:
        return JSONResponse({"authenticated": False}, status_code=401)
    return {"authenticated": True, "user": user}


@app.post("/auth/logout")
async def auth_logout(request: Request):
    """Clear browser session data."""
    request.session.clear()
    return {"ok": True}


def get_current_user_or_401(request: Request):
    """Small auth helper returning `(user, error_response)` tuple."""
    user = request.session.get("user")
    if not user:
        return None, JSONResponse({"error": "authentication required"}, status_code=401)
    return user, None


def _get_profile_row(sub: str):
    """Load one profile row used by page routing and profile APIs."""
    with get_db() as conn:
        return db_execute(
            conn,
            """
            SELECT sub, email, default_city, timezone, role, commute_mode, ppe_required, risk_tolerance, updated_at
            FROM user_profiles
            WHERE sub = %s
            """,
            (sub,),
        ).fetchone()


def _is_profile_complete(row) -> bool:
    """Treat setup as complete only when all onboarding-required fields are present."""
    if not row:
        return False

    required_fields = [
        row["role"],
        row["default_city"],
        row["timezone"],
        row["commute_mode"],
        row["risk_tolerance"],
    ]
    return all(isinstance(value, str) and value.strip() for value in required_fields)


def _lookup_profile_city(sub: str | None) -> str | None:
    """Read default city from local profile DB for fallback event city logic."""
    if not sub:
        return None

    with get_db() as conn:
        row = db_execute(
            conn,
            "SELECT default_city FROM user_profiles WHERE sub = %s",
            (sub,),
        ).fetchone()
    city = (row["default_city"] or "").strip() if row else ""
    return city or None
