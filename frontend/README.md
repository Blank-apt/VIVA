# Viva — Streamlit Frontend

A single-file Streamlit UI over the Part C FastAPI backend. It makes no
direct database or LLM calls — everything comes through the backend's
HTTP API (`/interview/next-question`, `/interview/submit-answer`,
`/interview/end-session`, `/mastery/{mode}`, `/interview/session/{id}`).

## What it does

- **Interview panel**: pick a mode (Fundamentals / Scenario / Your Projects),
  optionally name a specific topic, get a real LLM-generated question, type
  your answer, submit it, and see the real evaluator score/feedback.
- **Mastery dashboard**: a live bar chart of every topic's current mastery
  for the selected mode, so you can watch weak topics visibly change as
  you answer questions.
- **Session history**: every question/answer you've done in the current
  session, pulled straight from SQLite via the backend.
- **Session lifecycle**: new-session and end-session controls, matching
  the backend's actual session model (not just a UI concept).

## Why typed answers, not real audio

Part A's real speech-to-text needs `ffmpeg` + `faster-whisper` (a heavy,
platform-specific install — see `backend/part_a/requirements.txt`). Rather
than block the whole frontend on that being installed, the "Submit answer"
button sends your typed text via the backend's `transcript_override` field,
which skips `transcribe()` entirely and goes straight to the evaluator —
functionally identical to a correct transcription of you speaking it. If/when
real audio is wired in, only this one field would need to change to switch to
recording + base64-encoded audio instead of a text box.

## Setup

```bash
cd frontend
pip install -r requirements.txt --break-system-packages
```

## Run

**1. Start the backend first** (separate terminal):
```bash
cd backend/part_c
uvicorn main:app --reload
```

**2. Start the frontend:**
```bash
cd frontend
streamlit run app.py
```
It opens at `http://localhost:8501`. The backend URL is editable in the
sidebar if you're running it somewhere other than `127.0.0.1:8000`.

## Notes

- CORS is enabled on the backend (`main.py`) specifically so this frontend
  (a different port) can call it directly from the browser.
- Session IDs are auto-generated per Streamlit session (`streamlit-xxxxxxxxxx`)
  and persist across reruns until you click "New session".
- If the backend isn't running, the sidebar shows a clear "Backend
  unreachable" indicator instead of the app silently failing.
