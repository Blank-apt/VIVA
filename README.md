# Viva — Adaptive Interview & Viva Prep Coach

Full stack: a FastAPI backend (three integrated parts) plus a Streamlit
frontend for actually using it.

```
viva/
  backend/    FastAPI app — Interviewer/Evaluator agents, SQLite persistence
              (see backend/README.md for the full integration report)
  frontend/   Streamlit UI — talks to the backend over HTTP
              (see frontend/README.md for details)
```

## Fastest path to running it

**Terminal 1 — backend:**
```bash
cd backend
python -m venv venv && source venv/Scripts/activate   # Git Bash on Windows; use venv/bin/activate on Mac/Linux
pip install -r requirements.txt --break-system-packages
cp part_c/.env.example part_c/.env
# edit part_c/.env: set LLM_PROVIDER + a matching API key (Mistral's free tier needs no card)
cd part_c
uvicorn main:app --reload
```

**Terminal 2 — frontend:**
```bash
cd frontend
pip install -r requirements.txt --break-system-packages
streamlit run app.py
```

Open the URL Streamlit prints (`http://localhost:8501`). Pick a mode,
click **Get next question**, type an answer, click **Submit answer** —
you'll see a real LLM-generated question and a real evaluator score, and
watch the mastery bar chart on the right update.

## Run the automated tests (no API key or frontend needed)

```bash
cd backend
python -m pytest tests/ part_b/tests/ -v
```
38 tests, covering the database layer, EMA mastery math, difficulty
adaptation, session persistence/rollback, and the full FastAPI request
flow (with the LLM call mocked so no network/API key is required).

## Why a text box instead of a microphone

Real speech-to-text (Part A) needs `ffmpeg` + `faster-whisper`, a heavy,
platform-specific install. The Streamlit frontend's "Submit answer" button
sends typed text straight to the evaluator via the backend's
`transcript_override` field — functionally identical to a correct
transcription of speaking the same words. Real audio can be wired in later
by swapping that one field for a recorded/base64-encoded clip; nothing else
in the flow would need to change.

For full architecture, API contracts, database design, and integration
notes, see `backend/README.md`.
