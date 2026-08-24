# Viva — Part C: Agent Orchestration

Interviewer agent + Evaluator agent + FastAPI routes wiring Part A (voice/RAG)
and Part B (scoring/session state) together.

## Files

| File | Responsibility |
|---|---|
| `main.py` | FastAPI app, the two routes that drive an interview turn |
| `interviewer.py` | Picks topic/difficulty (via Part B), generates the question (via Kimi) |
| `evaluator.py` | Scores a transcribed answer against the question's rubric (via Kimi) |
| `llm_client.py` | Structured-output wrapper, works against Groq or Moonshot |
| `schemas.py` | All Pydantic models — Kimi's raw output schemas and the API request/response models |
| `session_store.py` | In-memory question_id -> checklist mapping (see limitation below) |
| `config.py` | Env-driven settings |

## Setup

Three LLM providers are supported behind one env var — `llm_client.py` and
every prompt/schema are identical across all of them. Config is read from
a `.env` file (via `python-dotenv`), which is more reliable than exporting
in a terminal — the app reads its own key every time it starts, so it
doesn't matter which terminal/tab you happen to run `uvicorn` from.

**Now, through Aug 20 (free, no Kimi credits needed) — Mistral (default):**
```bash
pip install -r requirements.txt
cp .env.example .env
# edit .env: set MISTRAL_API_KEY to your real key from console.mistral.ai
#            (free "Experiment" tier — no card, phone verification only)
uvicorn main:app --reload
```
Runs `mistral-large-latest`. Mistral's official API uses the exact same
strict `json_schema` shape (including `additionalProperties: false`) that
this code already builds, so no extra schema patching was needed beyond
what Groq already required. Free tier: ~1 request/second, ~500K
tokens/minute, ~1B tokens/month — the most headroom of the three options
here, and it applies to every Mistral model, not just the smallest one.

**Alternative free option — Groq:** edit `.env`, comment the Mistral
lines, uncomment the Groq lines (`LLM_PROVIDER=groq` + `GROQ_API_KEY`).
Runs `openai/gpt-oss-120b`. Free tier: 30 RPM, 1K RPD, 8K TPM, 200K TPD —
tighter on tokens/minute than Mistral, so prefer Mistral unless you have
a specific reason to compare model behavior.

The very first lines uvicorn prints on boot will confirm which provider
and model actually loaded, and whether it found a key:
```
[config] provider=mistral model=mistral-large-latest MISTRAL_API_KEY loaded (starts with 'AbCdEf...', length 32)
```
If instead you see a `WARNING: ... is NOT set`, the `.env` file either
doesn't exist yet, isn't named exactly `.env`, or isn't in the same
folder as `main.py` — fix that before testing anything else.

**From Aug 21 (once you've bought Kimi credits):** edit `.env` — comment
out whichever provider block is active, uncomment the Moonshot lines.
Restart uvicorn. Nothing else changes — same code, same schemas, same
prompts.

### Known gap to sanity-check before you rely on it

Mistral's docs show the identical strict-schema request shape this code
sends, which is reassuring — but run a handful of real calls early anyway
(not the night before demo day) to confirm the retry loop in
`llm_client.py` isn't firing more than expected, and that
`reasoning_effort: "none"` isn't degrading judgment quality on the
Evaluator specifically. If scores look off, try `thinking_enabled=True`
on evaluator calls (maps to `reasoning_effort: "high"` for Mistral,
`"medium"` for Groq) before assuming the schema design itself is wrong.

Verified: every module compiles and imports cleanly, and the full
`next-question -> submit-answer` round trip was smoke-tested end-to-end
with mocked Kimi responses (real API calls weren't made — you'll want to
run one real call against your actual key before demo day to confirm the
MFJS schema strictness note below doesn't bite).

## How this connects to Part A and Part B

This code imports Part A/B like this, falling back to stub implementations
if the real modules aren't importable yet (so you can develop against this
standalone):

```python
try:
    from part_a import transcribe
except ImportError:
    def transcribe(audio: bytes) -> str: ...
```

**Once your teammates' code is ready**, replace the `try/except ImportError`
blocks at the top of `main.py` and `interviewer.py` with real imports —
that's the only place integration touches. Everything else in
`interviewer.py`, `evaluator.py`, and `main.py` is written against the
signatures you gave me, not against my stub bodies.

### Expected from Part A

| Signature | Called from | Assumption I made |
|---|---|---|
| `transcribe(audio) -> str` | `main.py` | **`audio` is raw `bytes`.** The API receives base64-encoded audio in the request body and decodes it before calling this. If Part A actually expects a filepath or an `UploadFile`, change the decode step in `main.submit_answer()` — nothing else needs to change. |
| `ingest_documents(files) -> None` | not called by Part C | Assumed this runs once at session setup, outside the interview loop — not wired in here. Wire it into your own session-start flow if that's wrong. |
| `retrieve_project_context(query) -> list[str]` | `interviewer.py`, project mode only | Passed the topic as `query`. Confirm with your teammate whether it expects a topic string or something more specific (a question, a keyword). |

### Expected from Part B

| Signature | Called from | Assumption I made |
|---|---|---|
| `update_mastery(topic, mode, score) -> None` | `main.py` | **`score` is a `float` in `[0.0, 1.0]`** — computed in `evaluator._score_from_points()` as `points_earned / points_possible`. This was an open decision (confirmed as still-open in our design discussion), not something your teammate already committed to. **You need to confirm this with them before it's load-bearing.** If they need something else, the conversion function is the only place to change. |
| `get_next_difficulty(topic, mode) -> str` | `interviewer.py` (topic selection), `main.py` (after grading) | Assumed this is meaningful for all 3 modes since the signature takes `mode`, even though only fundamentals was specified as using adaptive difficulty. If scenario/project should skip this call, remove it from `main.py`'s post-grading step. |
| `save_session(data) -> int` | `main.py` | **The `data` dict shape is a guess** — see the exact keys in `main.submit_answer()`. Your teammate designed the `session_qa`/`sessions` schema, not me; confirm the keys line up or `save_session()` will silently accept a dict it doesn't fully use. |
| `get_weakest_topics(mode, n) -> list[str]` | `interviewer.py` | Used to auto-pick a topic when the caller doesn't specify one. |

### Mode strings

Used literally as `"fundamentals"`, `"scenario"`, `"project"` throughout.
Part B's `topics`/`topic_mastery` tables and Part A's ingestion need to
agree on these exact strings (case, spelling) or lookups will silently
return nothing instead of erroring.

## API contract (frontend-facing)

**`POST /interview/next-question`**
```json
{"session_id": "s1", "mode": "fundamentals", "topic": null}
```
→
```json
{"question_id": "...", "mode": "fundamentals", "topic": "arrays",
 "difficulty": "medium", "question_text": "...", "checklist": []}
```

**`POST /interview/submit-answer`**
```json
{"session_id": "s1", "question_id": "...", "audio_base64": "..."}
```
→
```json
{"transcript": "...",
 "evaluation": {"score": 0.67, "points_earned": 2, "points_possible": 3,
                "rationale": "...", "detail": {...}},
 "next_difficulty": "medium"}
```

## Things I deliberately did NOT decide for you

- **Mode selection** (when to run fundamentals vs scenario vs project) —
  the caller passes `mode` explicitly. We hadn't designed an orchestration
  heuristic for this yet; don't assume one is hiding in the code.
- **Checklist persistence across restarts** — `session_store.py` is
  in-memory only. Fine for a single-process demo; if you need durability,
  that requires a schema change on Part B's side (see the file's docstring).

## Budget notes

- Default model is `kimi-k2.6` with `thinking` **disabled** on every call —
  `kimi-k3` always reasons at `"max"` effort by default and that reasoning
  bills as output tokens, which is the fastest way to blow a $10.50 budget.
- `prompt_cache_key` is set per mode (e.g. `"evaluator-fundamentals"`) so
  the static rubric/system-prompt text is cache-eligible across repeated
  calls — keep those system prompt strings byte-identical if you edit them,
  or you lose the cache hit.
- Full cost math (calls-per-session × team size × session count vs. the
  $10.50 cap) hasn't been done yet — that was flagged as a separate topic.
  Do this before your first full team test run, not after.
