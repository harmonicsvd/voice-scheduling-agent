from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from google.oauth2 import service_account
from googleapiclient.discovery import build
from dotenv import load_dotenv
from datetime import datetime, timedelta
import os
import json

load_dotenv()

app = FastAPI()

# Google Calendar setup
SCOPES = ['https://www.googleapis.com/auth/calendar']
SERVICE_ACCOUNT_FILE = 'service_account.json'
CALENDAR_ID = os.getenv('CALENDAR_ID')

def get_calendar_service():
    credentials = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    service = build('calendar', 'v3', credentials=credentials)
    return service

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

        name = arguments.get("name", "Guest")
        date = arguments.get("date", "")
        time = arguments.get("time", "")
        title = arguments.get("title", "Meeting")

        print(f"Creating event for: {name}, {date}, {time}, {title}")

        # Parse date and time
        event_datetime_str = f"{date} {time}"
        event_start = datetime.strptime(event_datetime_str, "%Y-%m-%d %H:%M")
        event_end = event_start + timedelta(hours=1)

        # Create Google Calendar event
        service = get_calendar_service()
        event = {
            'summary': f"{title} with {name}",
            'description': f"Meeting scheduled via Voice Scheduling Agent for {name}",
            'start': {
                'dateTime': event_start.isoformat(),
                'timeZone': 'Europe/Berlin',
            },
            'end': {
                'dateTime': event_end.isoformat(),
                'timeZone': 'Europe/Berlin',
            },
        }

        created_event = service.events().insert(
            calendarId=CALENDAR_ID, 
            body=event
        ).execute()

        print(f"Event created: {created_event.get('htmlLink')}")

        return JSONResponse(content={
            "results": [{
                "toolCallId": tool_calls[0].get("id"),
                "result": f"Calendar event '{title}' has been successfully created for {name} on {date} at {time}. You will receive a confirmation shortly."
            }]
        })

    except Exception as e:
        print("Error:", e)
        return JSONResponse(
            content={"error": str(e)}, 
            status_code=500
        )
