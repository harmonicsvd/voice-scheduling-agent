# Voice Scheduling Agent

A real-time voice assistant that schedules meetings and creates Google Calendar events through natural conversation.

**Live Demo:** https://voice-scheduling-agent-pi.vercel.app

---

## How to Test

1. Open the live URL above
2. Click the microphone button
3. Speak naturally — the agent will ask for your name, date, time, and meeting title
4. Confirm the details
5. The event gets created on Google Calendar automatically

> The agent confirms name spelling letter by letter and always reads back the date in plain language before confirming.

---

## Demo Video

👉 [Watch Demo on Google Drive](https://drive.google.com/file/d/17kCrG0xyrFIFySx9AJ40cIILDZwRM4BB/view?usp=sharing)

---

## Stack

| Layer | Tool |
|---|---|
| Voice & STT/TTS | VAPI |
| LLM | GPT-4.1 (via VAPI) |
| Backend | FastAPI (Python) |
| Calendar | Google Calendar API |
| Frontend | HTML/CSS/JS |
| Backend hosting | Render |
| Frontend hosting | Vercel |

---

## Architecture

```
User speaks → VAPI (STT + LLM) → createCalendarEvent tool call
→ FastAPI backend (Render) → Google Calendar API → event created
→ confirmation sent back to VAPI → agent confirms verbally
→ frontend updates UI with new meeting
```

---

## Calendar Integration

When the user confirms their meeting details, VAPI triggers a function called `createCalendarEvent` with the collected information — name, date, time, and duration.

This sends a request to our FastAPI backend on Render at the `/create-event` endpoint. The backend parses the details and calculates the correct start and end times.

To create the event, we use a **Google Service Account** — a way to give our backend direct access to Google Calendar without requiring any user login. The credentials are stored securely as environment variables on Render and never exposed in the code.

The backend calls the **Google Calendar API v3**, creates the event, and returns a confirmation back to VAPI. VAPI reads the confirmation out loud, and the frontend updates the calendar grid and recent meetings tracker at the same time.

---

## Run Locally

The live deployed URL is the recommended way to test this project — no setup needed.

For running your own instance:

1. Clone the repo:
```bash
git clone https://github.com/harmonicsvd/voice-scheduling-agent.git
cd voice-scheduling-agent
```

2. Copy the example config and fill in your own credentials:
```bash
cp config.example.env .env
```

```
CALENDAR_ID=your-gmail@gmail.com
SERVICE_ACCOUNT_JSON={"type":"service_account",...}
VAPI_PUBLIC_KEY=your-vapi-public-key
```

3. Run the setup script:
```bash
chmod +x setup.sh
./setup.sh
```

4. Deploy the backend to any Python-compatible host (e.g. Render) so VAPI can reach it via a public URL.

5. Update the `createCalendarEvent` tool webhook URL in your VAPI dashboard to point to your deployed backend.

6. Open `index.html` in your browser.

---

## Creative Design Decisions

These were not part of the assignment brief — added to explore UX thinking and design ability.

- **Full-page calendar grid background** — a subtle frosted Google Calendar-style grid sits behind all content, making the scheduling context visually clear without being distracting
- **Date highlighting** — when a meeting is created, that date number in the background grid highlights green in real time, connecting the voice action to a visual calendar response
- **Recent meetings tracker** — a live in-memory list shows all meetings scheduled in the current session, acting like a lightweight local database
- **Circular mic button with ripple animation** — replaces the standard button with a more intentional voice-first interaction pattern
- **VAPI default button hidden** — the SDK's floating button is suppressed and replaced entirely with the custom UI

---

## Known Limitations

- **Calendar grid is decorative** — the background grid does not reflect the actual days of the month or week alignment. It is a visual design element. A future version would render a proper month calendar.

- **Shared calendar** — events are currently created on the developer's Google Calendar. Testers are welcome to create a few test events — they will be cleaned up periodically. In production, users would authenticate via Google OAuth to schedule on their own calendars.

- **STT accuracy on uncommon names** — speech-to-text occasionally mishears non-English names. The agent asks for letter-by-letter spelling confirmation to mitigate this.

- **LLM duration parsing** — the model occasionally returns duration as words instead of numbers (e.g. "one hour"). The backend handles this with a custom parser that combines a word-to-number mapping for common values with regex pattern matching to convert any duration format into minutes correctly.

- **Render cold starts** — the free Render tier sleeps after inactivity. First load may take 30-50 seconds while the backend wakes up.

---

## Submission

- **GitHub:** https://github.com/harmonicsvd/voice-scheduling-agent
- **Live URL:** https://voice-scheduling-agent-pi.vercel.app
- **Demo Video:** 👉 [Watch on Google Drive](https://drive.google.com/file/d/17kCrG0xyrFIFySx9AJ40cIILDZwRM4BB/view?usp=sharing)