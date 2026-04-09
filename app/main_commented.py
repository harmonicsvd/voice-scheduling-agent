"""
Learning version of `main.py`.

This file keeps the same behavior as `main.py`, but adds detailed comments so
you can study how a FastAPI backend is structured line by line.
"""

# FastAPI core classes:
# - FastAPI: creates the web application object.
# - Request: gives access to incoming HTTP request data.
from fastapi import FastAPI, Request

# JSONResponse lets us return explicit JSON payloads and status codes.
from fastapi.responses import JSONResponse

# Google auth helper to build credentials from a service-account JSON.
from google.oauth2 import service_account

# Google API client builder used to create a Calendar API service object.
from googleapiclient.discovery import build

# Loads variables from `.env` into environment variables for local development.
from dotenv import load_dotenv

# datetime: parse incoming date/time strings.
# timedelta: add duration to start time to compute end time.
from datetime import datetime, timedelta

# Standard library imports:
# - os: read environment variables.
# - json: parse JSON strings from env variables.
# - re: regular expressions for duration parsing.
import os
import json
import re

# CORS middleware allows your frontend origin to call this backend from browser.
from fastapi.middleware.cors import CORSMiddleware


# Load `.env` values once at startup.
load_dotenv()

# Create the FastAPI app instance.
app = FastAPI()

# Add CORS settings so only trusted frontend origins can call this API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        # Production frontend (Vercel)
        "https://voice-scheduling-agent-pi.vercel.app",
        # Local frontend (common dev ports/tools)
        "http://localhost:3000",
        "http://127.0.0.1:5500",
    ],
    # Allow cookies/auth headers if needed.
    allow_credentials=True,
    # Allow all HTTP methods (GET, POST, etc.) for this project.
    allow_methods=["*"],
    # Allow all request headers.
    allow_headers=["*"],
)


# Google Calendar API scope: full calendar access for the connected account.
SCOPES = ["https://www.googleapis.com/auth/calendar"]

# Which calendar to insert events into (comes from environment variable).
CALENDAR_ID = os.getenv("CALENDAR_ID")


def parse_duration_to_minutes(duration_str):
    """
    Convert natural-language duration text into minutes.

    Examples:
    - "1 hour" -> 60
    - "one hour thirty min" -> 90
    - "45 min" -> 45

    If parsing fails, default to 60 minutes.
    """

    # Normalize input to lowercase so matching is case-insensitive.
    duration_str = duration_str.lower()

    # Replace common words with numeric equivalents to make regex parsing easier.
    # Note: this is a simple parser, not a full NLP parser.
    word_to_num = {
        "one": "1",
        "two": "2",
        "three": "3",
        "four": "4",
        "half": "30 min",
        "thirty": "30",
        "forty five": "45",
        "twenty": "20",
        "fifteen": "15",
        "ninety": "90",
    }

    # Apply all replacements to the duration string.
    for word, num in word_to_num.items():
        duration_str = duration_str.replace(word, num)

    # Find hour part, supports integers or decimal values like "1.5 hour".
    hours = re.search(r"(\d+\.?\d*)\s*hour", duration_str)

    # Find minute part like "30 min".
    minutes = re.search(r"(\d+)\s*min", duration_str)

    # Build total duration in minutes.
    total_minutes = 0
    if hours:
        total_minutes += float(hours.group(1)) * 60
    if minutes:
        total_minutes += int(minutes.group(1))

    # Return parsed value, else fallback to 60 minutes.
    return int(total_minutes) if total_minutes > 0 else 60


def get_calendar_service():
    """
    Build and return a Google Calendar API service client.

    Reads the service account JSON from env variable `SERVICE_ACCOUNT_JSON`.
    """

    # Read JSON string from env and convert to dict.
    service_account_info = json.loads(os.getenv("SERVICE_ACCOUNT_JSON"))

    # Build credentials object with required scope.
    credentials = service_account.Credentials.from_service_account_info(
        service_account_info, scopes=SCOPES
    )

    # Build Google Calendar v3 client using those credentials.
    service = build("calendar", "v3", credentials=credentials)
    return service


@app.get("/vapi-key")
async def get_vapi_key():
    """
    Return VAPI public key to frontend.

    Why this exists:
    - Keeps key out of hardcoded frontend source.
    - Frontend fetches it at runtime from backend.
    """
    return JSONResponse(content={"apiKey": os.getenv("VAPI_PUBLIC_KEY")})


@app.get("/")
def root():
    """Health-check endpoint for quick "is server alive?" checks."""
    return {"status": "Voice Scheduling Agent is running!"}


@app.post("/create-event")
async def create_event(request: Request):
    """
    Main webhook endpoint called by VAPI tool-call flow.

    Expected payload shape (simplified):
    {
      "message": {
        "toolCalls": [
          {
            "id": "...",
            "function": {
              "arguments": {
                "name": "...",
                "date": "YYYY-MM-DD",
                "time": "HH:MM",
                "title": "...",
                "duration": "1 hour"
              }
            }
          }
        ]
      }
    }
    """

    # Parse JSON request body.
    data = await request.json()
    print("Received from VAPI:", data)

    try:
        # Extract tool calls list from nested payload.
        tool_calls = data.get("message", {}).get("toolCalls", [])

        # If no tool calls, request is invalid for this endpoint.
        if not tool_calls:
            return JSONResponse(content={"error": "No tool calls found"}, status_code=400)

        # Extract function arguments from first tool call.
        arguments = tool_calls[0].get("function", {}).get("arguments", {})

        # Read fields with safe defaults.
        name = arguments.get("name", "Guest")
        date = arguments.get("date", "")
        time = arguments.get("time", "")
        title = arguments.get("title", "Meeting")
        duration = arguments.get("duration", "1 hour")

        print(f"Creating event for: {name}, {date}, {time}, {title}, {duration}")

        # Combine date and time and parse into Python datetime object.
        event_datetime_str = f"{date} {time}"
        event_start = datetime.strptime(event_datetime_str, "%Y-%m-%d %H:%M")

        # Convert natural-language duration to integer minutes.
        duration_minutes = parse_duration_to_minutes(duration)

        # End time = start time + duration.
        event_end = event_start + timedelta(minutes=duration_minutes)

        print(f"Duration: {duration_minutes} minutes")

        # Create Google Calendar API client.
        service = get_calendar_service()

        # Build the Google Calendar event payload.
        event = {
            "summary": title,
            "description": f"Scheduled by {name} via Voice Scheduling Agent.",
            "start": {
                "dateTime": event_start.isoformat(),
                "timeZone": "Europe/Berlin",
            },
            "end": {
                "dateTime": event_end.isoformat(),
                "timeZone": "Europe/Berlin",
            },
        }

        # Insert event into target calendar.
        created_event = service.events().insert(calendarId=CALENDAR_ID, body=event).execute()

        print(f"Event created: {created_event.get('htmlLink')}")

        # Return tool-call result in format expected by VAPI.
        return JSONResponse(
            content={
                "results": [
                    {
                        "toolCallId": tool_calls[0].get("id"),
                        "result": (
                            f"Calendar event '{title}' has been successfully created for "
                            f"{name} on {date} at {time} for {duration}."
                        ),
                    }
                ]
            }
        )

    except Exception as e:
        # Catch and return all unexpected errors with status 500.
        print("Error:", e)
        return JSONResponse(content={"error": str(e)}, status_code=500)
