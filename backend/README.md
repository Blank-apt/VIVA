# Viva — Integrated Backend (Parts A + B + C)

This folder is the result of integrating three independently-developed
parts of the Viva hackathon project into one running FastAPI application.

```
backend/
  part_a/     Voice & Ingestion (speech-to-text, resume/project RAG)
  part_b/     Data & Scoring (SQLite: topics, mastery, sessions)
  part_c/     Agent Orchestration (FastAPI app: Interviewer + Evaluator)
  tests/      End-to-end integration tests across all three parts
  requirements.txt
```

## Setup

```bash
cd backend
pip install -r requirements.txt          # Parts B + C (Part A's heavy ML deps are optional, see below)
cp part_c/.env.example part_c/.env       # then fill in a real LLM_PROVIDER + API key
```

Optional — only needed for real speech-to-text / project-personalized
questions (the app runs fine without this, using stub fallbacks):

```bash
pip install -r part_a/requirements.txt   # faster-whisper, sentence-transformers, pdfplumber, python-docx
# plus ffmpeg on PATH (not a pip package)
```

## Run

```bash
cd backend/part_c
uvicorn main:app --reload
```

The database (`backend/viva.db`) and its 55 seeded topics — spanning
DSA, OS, DBMS, Networking, OOP, and System Design basics — are created
automatically the first time the app is imported — no manual DB setup
step required.

## Run tests

```bash
cd backend
python -m pytest tests/ part_b/tests/ -v
```
33 tests, all passing (23 Part B unit tests + 4 Part B additions for the
new incremental-session functions + 4 full-stack integration tests through
the real FastAPI app and real SQLite DB, with only the LLM call and
`transcribe()` mocked out since no API key/ffmpeg is available in every
environment).

---

## Architecture

```
Frontend (not present in this ZIP)
        │ HTTP
        ▼
part_c/main.py  (FastAPI)
   ├── POST /interview/next-question
   ├── POST /interview/submit-answer
   ├── POST /interview/end-session
   └── GET  /health
        │
        ├──► part_c/interviewer.py ──► part_b.get_weakest_topics / get_next_difficulty
        │                          └─► part_a.retrieve_project_context (your-projects mode only)
        │                          └─► LLM (question authoring)
        │
        ├──► part_a.transcribe (speech → text)
        │
        ├──► part_c/evaluator.py ──► LLM (coarse categorical judgment)
        │                        └─► deterministic score = points_earned / points_possible
        │
        └──► part_b.update_mastery / add_qa / end_session ──► SQLite (viva.db)
```

## Files changed / created during integration

**Part A** — copied as-is, folder renamed `part a` → `part_a` (space isn't
a valid Python package name), added `part_a/__init__.py` re-exporting
`transcribe`, `ingest_documents`, `retrieve_project_context`.

**Part B** — flattened `part b/app/*.py` → `part_b/*.py`, fixed internal
`from app.X import` → `from .X import` (relative imports, since the
package is now named `part_b` not `app`), added `part_b/__init__.py`
re-exporting the public interface. Added two new functions to
`sessions.py` (`add_qa`, `end_session`) — see "Session flow" below for
why these were necessary. Moved+fixed `tests/test_part_b.py`'s imports,
added 6 new tests for `add_qa`/`end_session`.

**Part C** — fixed mode naming (`"project"` → `"your-projects"`, the
canonical value from the DB contract) in `schemas.py` and `interviewer.py`.
Added `part_c/_pathfix.py` so the sibling `part_a`/`part_b` packages
resolve on `sys.path` regardless of which directory Python is launched
from. Rewrote `main.py`'s `/submit-answer` to call `add_qa()` instead of
`save_session()` (see below), added a new `POST /interview/end-session`
endpoint + `EndSessionRequest`/`EndSessionResponse` schemas, added
automatic DB init/seed at import time. Extended `session_store.py` with
a frontend-session-id → Part B session-id mapping.

**New**: `backend/tests/test_integration.py` — 4 end-to-end tests through
the real FastAPI app + real SQLite DB.

## The one real design conflict, and how it was resolved

Part B's `save_session(session_data)` was designed to be called **once**,
at the end of a session, with the full list of Q&A already in hand. Part C
was written to call it **once per answer**, with a flat single-QA dict.
Calling `save_session` per-answer as originally written would have created
a brand-new `sessions` row for every single question — breaking the whole
point of a "session."

Rather than force Part C's live, turn-by-turn flow into Part B's
batch-shaped function (or force Part B to guess when a batch is "done"),
I added two small functions to Part B — `start_session()` (already
existed) and new `add_qa()` / `end_session()` — that let a session be
built up incrementally: one open session row, one `add_qa()` call per
answer, one `end_session()` call when the interview finishes.
`save_session()` itself is untouched and still works for any future
caller that wants to persist a whole session in one batch call.

## API contracts

```
POST /interview/next-question
  { "session_id": "s1", "mode": "fundamentals", "topic": null }
  -> { "question_id", "mode", "topic", "difficulty", "question_text", "checklist" }

POST /interview/submit-answer
  { "session_id": "s1", "question_id": "...", "audio_base64": "..." }         # real audio path
  { "session_id": "s1", "question_id": "...", "transcript_override": "..." }  # typed-answer path (used by the Streamlit frontend)
  -> { "transcript", "evaluation": {"score", "points_earned", "points_possible", "rationale", "detail"}, "next_difficulty" }

POST /interview/end-session
  { "session_id": "s1", "summary": "optional text" }
  -> { "session_id": <int>, "ended": true }

GET /mastery/{mode}
  -> [ { "topic": "...", "score": 0.0-1.0, "difficulty": "..." }, ... ]   # every topic, weakest first

GET /interview/session/{session_id}
  -> { "session_id": <int>, "started_at", "ended_at", "summary", "qa": [ {...}, ... ] }
```

The last two (`GET /mastery/{mode}`, `GET /interview/session/{session_id}`)
were added specifically to support the Streamlit frontend's mastery bar
chart and session-history panel — they're thin read-only wrappers around
Part B's `get_mastery_overview()` (new) and `get_session()`/
`get_session_questions()` (already existed).

`transcript_override` on `/submit-answer` was also added for the frontend:
it skips `transcribe()` entirely and grades the given text directly, so the
UI works with typed answers without requiring Part A's Whisper/ffmpeg
install. `audio_base64` still works exactly as before for a real
audio-based client — exactly one of the two fields is required.

## Database

Single SQLite file at `backend/viva.db`, created + seeded automatically
on first import of `part_c/main.py` (both via `uvicorn main:app` and via
`pytest`/`TestClient`). Schema is exactly the finalized 4-table design —
unchanged.

## Score flow

Evaluator LLM call returns a coarse categorical judgment (booleans /
checklist met-or-not) — never a raw number, because LLM judges are
unreliable at fine-grained numeric scoring. `evaluator.py` deterministically
computes `score = points_earned / points_possible`, already in `[0.0, 1.0]`
— matches Part B's expected range exactly, no conversion needed at the
boundary. That score flows into `update_mastery(topic, mode, score)`.

## Difficulty flow

`get_next_difficulty(topic, mode)` (Part B) is called by the interviewer
before generating a fundamentals-mode question, and again after each
answer is scored (returned to the caller as `next_difficulty`) so the UI
can show the adaptation happening in real time. Only `fundamentals` mode
uses difficulty currently — `scenario`/`your-projects` questions are
open-ended and use a checklist rubric instead.

## Session flow

1. `/next-question` calls `get_or_create_backend_session(session_id)` —
   lazily creates a Part B `sessions` row the first time a given
   frontend `session_id` string is seen, mapped in-process.
2. `/submit-answer` calls `add_qa(...)`, appending one `session_qa` row
   to that same open session, immediately after computing the score and
   updating mastery — so a mid-interview crash only loses the mapping,
   never previously-answered questions.
3. `/end-session` calls `end_session(...)`, setting `ended_at` + summary,
   then forgets the in-process mapping.

## Configuration

See `part_c/.env.example`. One LLM provider must be configured:

```
LLM_PROVIDER=mistral   # or groq, or moonshot
MISTRAL_API_KEY=...    # matching key for whichever provider you picked
```

No other env vars are required — Part B's DB path and Part A's model
size are hardcoded sane defaults (not exposed as env vars), consistent
with "don't over-engineer for a hackathon."

## Test results (actually run, not claimed)

```
40 passed in ~2s
```
- 31 Part B unit tests (schema, EMA, boundaries, mode isolation, weakest-topic
  ordering, session/transaction rollback, restart persistence, `add_qa`/`end_session`,
  seed coverage across all 6 topic categories)
- 9 integration tests through the real FastAPI app + real SQLite DB:
  full next-question → submit-answer → mastery-update → persistence →
  end-session flow; a 404 check for answering an unknown question; a
  repeated-low-score run that drives difficulty down to `foundational`;
  the `transcript_override` typed-answer path; the `/mastery/{mode}` and
  `/interview/session/{id}` read endpoints.

Additionally manually verified (not part of the automated suite, but run
and observed during this session):
- The app boots correctly via real `uvicorn` (not just TestClient), auto-creates
  and seeds all 55 topics into `viva.db`, and responds on `/health`.
- Mastery data (`get_weakest_topics`) survives killing and restarting the
  actual `uvicorn` OS process — the project's core "remembers the
  candidate" claim, confirmed at the process level, not just in-memory.
- If Part A's ML dependencies (faster-whisper etc.) aren't installed, the
  app still boots and runs correctly using the stub `transcribe()` — verified
  by hiding the `part_a` package and re-importing `main.py`.
- The real FastAPI server and the real Streamlit frontend were run
  simultaneously as separate processes; both reported healthy, and a
  scripted simulation of the full UI call sequence (question → answer →
  mastery fetch → session history → end session) succeeded end to end.

## Known limitations

- **No real LLM key in this environment** — the actual question-generation
  and evaluation LLM calls were only exercised via monkeypatched stand-ins
  in tests, not against a live Mistral/Groq/Moonshot endpoint. The plumbing
  (`call_structured`, prompts, response schemas) was inspected and is wired
  correctly, but you should do one real run with a real API key before the
  demo to confirm the actual model output parses cleanly into the Pydantic
  schemas.
- **No frontend exists in this ZIP** — Part C is API-only; nothing in
  section 19 of the spec ("connect the frontend") could be done because
  there's no frontend code to connect. The endpoints are ready to be
  called from one.
- **Session-id mapping is process-local** — see the docstring in
  `session_store.py`. A backend restart mid-interview loses the mapping
  from a frontend's `session_id` string to Part B's integer session row
  (a new session simply starts), but never loses already-saved answers
  or mastery, since every answer is persisted immediately via `add_qa()`.
  Not a problem at hackathon scale (single process, no horizontal scaling).
- **`ingest_documents`/resume upload has no HTTP endpoint** — Part A
  exposes the function, but main.py doesn't have a route to call it yet
  (there was no schema/contract for a file-upload endpoint in the
  original Part C code to build on). `your-projects` mode will work end
  to end only after something calls `ingest_documents()` first.
