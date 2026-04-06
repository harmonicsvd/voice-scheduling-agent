
from fastapi import FastAPI, Request, Query
from fastapi.responses import JSONResponse
from google.oauth2 import service_account
from googleapiclient.discovery import build
from dotenv import load_dotenv
from datetime import datetime, timedelta
import os
import json
import re
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

app = FastAPI()

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


# Google Calendar setup
SCOPES = ['https://www.googleapis.com/auth/calendar']
CALENDAR_ID = os.getenv('CALENDAR_ID')

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

def get_calendar_service():
    raw = os.getenv("SERVICE_ACCOUNT_JSON")
    if raw:
        service_account_info = json.loads(raw)
        credentials = service_account.Credentials.from_service_account_info(
            service_account_info, scopes=SCOPES
        )
    else:
        key_path = os.getenv("SERVICE_ACCOUNT_FILE", "service_account.json")
        credentials = service_account.Credentials.from_service_account_file(
            key_path, scopes=SCOPES
        )

    service = build("calendar", "v3", credentials=credentials)
    return service


@app.get("/vapi-key")
async def get_vapi_key():
    return JSONResponse(content={
        "apiKey": os.getenv('VAPI_PUBLIC_KEY')
    })

@app.get("/")
def root():
    return {"status": "Voice Scheduling Agent is running!"}

@app.post("/create-event")
async def create_event(request: Request):
    data = await request.json()
    print("Received from VAPI:", data)

    try:
        tool_calls = data.get("message", {}).get("toolCalls", [])
        if not tool_calls:
            return JSONResponse(
                content={"error": "No tool calls found"},
                status_code=400
            )

        arguments = tool_calls[0].get("function", {}).get("arguments", {})
        
        if isinstance(arguments, str):
            arguments = json.loads(arguments)
            
        name = arguments.get("name", "Guest")
        date = arguments.get("date", "")
        time = arguments.get("time", "")
        title = arguments.get("title", "Meeting")
        duration = arguments.get("duration", "1 hour")
        meeting_mode = (arguments.get("meeting_mode") or "").strip().lower()
        location = (arguments.get("location") or "").strip() or None
        
        if meeting_mode not in {"online", "in_person"}:
            return JSONResponse(content={"error": "meeting_mode must be 'online' or 'in_person'"}, status_code=400)

        if meeting_mode == "in_person" and not location:
            return JSONResponse(content={"error": "location is required for in-person meetings"}, status_code=400)


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
        event = {
            'summary': title,
            'description': f"Scheduled by {name} via Voice Scheduling Agent. meeting_mode:{meeting_mode}",
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
            calendarId=CALENDAR_ID,
            body=event
        ).execute()

        print(f"Event created: {created_event.get('htmlLink')}")

        return JSONResponse(content={
            "results": [{
                "toolCallId": tool_calls[0].get("id"),
                "result": f"Calendar event '{title}' has been successfully created for {name} on {date} at {time} for {duration}."
            }]
        })

    except Exception as e:
        print("Error:", e)
        return JSONResponse(
            content={"error": str(e)},
            status_code=500
        )
        
@app.get("/events")
async def list_events(
    from_iso: str = Query(..., description="ISO start datetime"),
    to_iso: str = Query(..., description="ISO end datetime"),
):
    try:
        service = get_calendar_service()
        response = (
            service.events()
            .list(
                calendarId=CALENDAR_ID,
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

            meeting_mode = "unknown"
            if "meeting_mode:online" in description:
                meeting_mode = "online"
            elif "meeting_mode:in_person" in description:
                meeting_mode = "in_person"

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
                     "meeting_mode": meeting_mode,
                    "is_virtual": is_virtual,
                }
            )

        return {"events": events}
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)