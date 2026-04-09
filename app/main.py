import hmac
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Query, Header
from fastapi.responses import JSONResponse
from app.config import settings
from app.google_clients import get_calendar_service, build_oauth

from pydantic import BaseModel, Field
from typing import Literal

from app.db import init_db, get_db



from datetime import datetime, timedelta, timezone

import re
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware



@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()   # runs once when server starts
    yield       # app serves requests here
    # optional cleanup when server stops

app = FastAPI(lifespan=lifespan)


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


class ProfileUpdate(BaseModel):
    default_city: str = Field(min_length=2, max_length=80)
    timezone: str = Field(default="Europe/Berlin", min_length=3, max_length=80)


class CreateEventArguments(BaseModel):
    name: str = "Guest"
    date: str
    time: str
    title: str = "Meeting"
    duration: str = "1 hour"
    meeting_mode: Literal["online", "in_person"]
    location: str | None = None
    city: str | None = None


class CreateEventFunctionPayload(BaseModel):
    arguments: CreateEventArguments


class CreateEventToolCall(BaseModel):
    id: str
    function: CreateEventFunctionPayload


class CreateEventMessage(BaseModel):
    toolCalls: list[CreateEventToolCall] = Field(default_factory=list)


class CreateEventRequest(BaseModel):
    message: CreateEventMessage
    

@app.get("/profile")
async def get_profile(request: Request):
    user, error = get_current_user_or_401(request)
    if error:
        return error

    with get_db() as conn:
        row = conn.execute(
            """
            SELECT sub, email, default_city, timezone, updated_at
            FROM user_profiles
            WHERE sub = ?
            """,
            (user["sub"],),
        ).fetchone()

    if not row:
        return {"has_profile": False, "profile": None}

    return {"has_profile": True, "profile": dict(row)}

@app.put("/profile")
async def put_profile(payload: ProfileUpdate, request: Request):
    user, error = get_current_user_or_401(request)
    if error:
        return error

    updated_at = datetime.now(timezone.utc).isoformat()

    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO user_profiles (sub, email, default_city, timezone, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(sub) DO UPDATE SET
                email = excluded.email,
                default_city = excluded.default_city,
                timezone = excluded.timezone,
                updated_at = excluded.updated_at
            """,
            (
                user["sub"],
                user.get("email", ""),
                payload.default_city.strip(),
                payload.timezone.strip(),
                updated_at,
            ),
        )
        conn.commit()

    return {"ok": True}

def require_internal_api_key(x_internal_api_key: str | None):
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
    err = require_internal_api_key(x_internal_api_key)
    if err:
        return err

    with get_db() as conn:
        row = conn.execute(
            """
            SELECT sub, email, default_city, timezone, updated_at
            FROM user_profiles
            WHERE sub = ?
            """,
            (sub,),
        ).fetchone()

    if not row:
        return JSONResponse({"error": "profile_not_found"}, status_code=404)

    return {"profile": dict(row)}

def parse_duration_to_minutes(duration_str):
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
    return JSONResponse(content={
        "apiKey": settings.vapi_public_key
    })

@app.get("/")
def root():
    return {"status": "Voice Scheduling Agent is running!"}

@app.post("/create-event")
async def create_event(payload: CreateEventRequest, request: Request):
    user, error = get_current_user_or_401(request)
    if error:
        return error

    print("Received from VAPI:", payload.model_dump())

    try:
        tool_calls = payload.message.toolCalls
        if not tool_calls:
            return JSONResponse(
                content={"error": "No tool calls found"},
                status_code=400
            )

        tool_call = tool_calls[0]
        arguments = tool_call.function.arguments

        name = arguments.name
        date = arguments.date
        time = arguments.time
        title = arguments.title
        duration = arguments.duration
        meeting_mode = arguments.meeting_mode
        requested_city = (arguments.city or "").strip() or None
        location = (arguments.location or "").strip() or None

        resolved_city = None
        city_source = None
        if meeting_mode == "in_person":
            if requested_city:
                resolved_city = requested_city
                city_source = "provided"
            elif location:
                derived_city = _derive_city_from_location(location)
                if derived_city:
                    resolved_city = derived_city
                    city_source = "from_location"

            if not resolved_city:
                with get_db() as conn:
                    row = conn.execute(
                        "SELECT default_city FROM user_profiles WHERE sub = ?",
                        (user["sub"],),
                    ).fetchone()

                profile_city = (row["default_city"] or "").strip() if row else ""
                if profile_city:
                    resolved_city = profile_city
                    city_source = "profile_default"
                else:
                    return JSONResponse(
                        content={
                            "error": "city is required for in-person meetings (or set default city in profile)"
                        },
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
            f"user_sub:{user.get('sub')}",
        ]
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
                "toolCallId": tool_call.id,
                "result": f"Calendar event '{title}' has been successfully created for {name} on {date} at {time} for {duration}."
            }]
        })

    except Exception as e:
        print("Error:", e)
        return JSONResponse(
            content={"error": str(e)},
            status_code=500
        )

def _list_events_payload(from_iso: str, to_iso: str) -> dict:
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

        # Backward-compatible fallback for older events that don't have
        # weather_city metadata yet.
        if not weather_city and meeting_mode == "in_person" and location:
            weather_city = _derive_city_from_location(location)
            if weather_city and not city_source:
                city_source = "from_location"

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
    err = require_internal_api_key(x_internal_api_key)
    if err:
        return err

    try:
        return _list_events_payload(from_iso, to_iso)
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.get("/auth/google/login")
async def auth_google_login(request: Request):
    redirect_uri = request.url_for("auth_google_callback")
    return await oauth.google.authorize_redirect(request, redirect_uri)


@app.get("/auth/google/callback")
async def auth_google_callback(request: Request):
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

    return JSONResponse({"ok": True, "user": request.session["user"]})

@app.get("/auth/me")
async def auth_me(request: Request):
    user = request.session.get("user")
    if not user:
        return JSONResponse({"authenticated": False}, status_code=401)
    return {"authenticated": True, "user": user}


@app.post("/auth/logout")
async def auth_logout(request: Request):
    request.session.clear()
    return {"ok": True}


def get_current_user_or_401(request: Request):
    user = request.session.get("user")
    if not user:
        return None, JSONResponse({"error": "authentication required"}, status_code=401)
    return user, None
