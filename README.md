# Viva

**An adaptive, voice-based interview coach that learns what you don't know — and asks about it next.**

Built for the AI Builders Hackathon 2026.

---

## The problem

Most interview prep tools are static question banks: they don't know what you actually got wrong, they're text-only when real interviews are spoken under pressure, and they never ask about the projects on your own resume. Viva is a mock interviewer that listens, grades what you actually said, and adapts in real time.

## What it does

Viva runs three interview modes over voice:

- **Fundamentals** — closed-form CS questions with adaptive difficulty. Difficulty climbs or eases based on your running mastery score.
- **Scenario** — open-ended system-design questions, each graded against its own checklist of specific, checkable criteria.
- **Your Projects** — questions generated from your own resume/project docs via RAG, so no two candidates get the same session.

Every spoken answer is transcribed live, scored by an LLM evaluator against a real rubric, and the score updates a per-topic mastery tracker that decides what to ask next — no human grading involved.

## How it's built

Three independently-developed backend modules, connected only by fixed function signatures — no shared internal state:

```
┌──────────────────┐      ┌───────────────────────┐      ┌──────────────────┐
│     Part A        │      │        Part C          │      │     Part B        │
│   Voice & RAG      │ ───▶ │  Agent Orchestration    │ ───▶ │  Adaptive Scoring   │
│                    │      │                         │      │                    │
│ Whisper speech-    │      │ Interviewer + Evaluator │      │ SQLite mastery     │
│ to-text. Resume/   │      │ agents. FastAPI routes. │      │ tracking. EMA      │
│ project ingestion  │      │ Structured LLM scoring. │      │ difficulty math.   │
│ and retrieval.     │      │                         │      │ Session state.     │
└──────────────────┘      └───────────────────────┘      └──────────────────┘
```

**Why the Evaluator is designed this way:** the LLM only ever makes coarse, checklist-style judgments (a boolean per criterion, never a numeric score) via strict JSON-schema structured output. The actual 0–1 score fed into mastery tracking is computed deterministically in Python from points earned vs. possible — LLMs are unreliable at fine-grained numeric scoring but reliably good at binary judgment calls, so the arithmetic never touches the model.

**LLM provider is swappable**, not hardcoded — Mistral, Groq, or Moonshot's Kimi behind one interface, switched with a single environment variable. Development runs on free tiers; the hackathon deployment can switch to a paid Kimi key without touching any code.

## Tech stack

| Layer | Technology |
|---|---|
| Backend framework | FastAPI |
| Database | SQLite |
| Speech-to-text | Whisper (`faster-whisper`) |
| LLM providers | Mistral / Groq / Moonshot (Kimi) — OpenAI-compatible API |
| Structured output | Strict JSON-schema grading (no free-text parsing) |
| Retrieval | Sentence-transformers embeddings over resume/project docs |
| Doc parsing | `pdfplumber`, `python-docx` |

## Project structure

```
backend/
├── part_a/              # Voice & RAG (Whisper, ingestion, retrieval)
├── part_b/              # Adaptive scoring (SQLite, mastery, sessions)
│   ├── schema.sql
│   └── seed.py
├── part_c/               # Agent orchestration (this is the FastAPI app)
│   ├── main.py            # Routes
│   ├── interviewer.py     # Question generation + selection
│   ├── evaluator.py       # Answer grading
│   ├── llm_client.py      # Provider-agnostic structured-output client
│   ├── schemas.py         # Pydantic models
│   ├── config.py          # Provider config, .env loading
│   ├── _pathfix.py        # Makes part_a/part_b importable as siblings
│   └── requirements.txt
├── tests/
│   └── test_integration.py
└── requirements.txt
```

## Setup

### 1. Clone and install

```bash
git clone https://github.com/Blank-apt/VIVA.git
cd VIVA/backend
python3 -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt -r part_a/requirements.txt -r part_b/requirements.txt -r part_c/requirements.txt
```

Part A's speech-to-text also needs `ffmpeg` installed as a system tool:

```bash
sudo apt install ffmpeg        # Debian/Ubuntu
brew install ffmpeg            # macOS
```

### 2. Configure your LLM provider

```bash
cd part_c
cp .env.example .env
```

Edit `.env` and set one provider block (uncomment/fill in exactly one):

```bash
LLM_PROVIDER=mistral
MISTRAL_API_KEY=your_real_key_here
```

Mistral's free tier (console.mistral.ai) needs no credit card — just phone verification. Groq is a supported alternative with its own free tier. Moonshot (Kimi) is the intended provider for the live hackathon run once credits are purchased.

### 3. Run

```bash
uvicorn main:app --reload
```

The boot log confirms which provider and model loaded:

```
[config] provider=mistral model=mistral-large-latest MISTRAL_API_KEY loaded (starts with 'AbCdEf...', length 32)
```

Visit `http://127.0.0.1:8000/docs` for interactive API docs.

## API

| Endpoint | Method | Description |
|---|---|---|
| `/interview/next-question` | `POST` | Generates the next question for a given mode (and optional topic) |
| `/interview/submit-answer` | `POST` | Submits spoken (base64) audio for a question, returns transcript + score |
| `/interview/end-session` | `POST` | Closes out a session with a summary |
| `/health` | `GET` | Health check |

Example request to start a fundamentals question:

```bash
curl -X POST http://127.0.0.1:8000/interview/next-question \
  -H "Content-Type: application/json" \
  -d '{"session_id": "demo-1", "mode": "fundamentals", "topic": null}'
```

## Testing

```bash
cd backend
python3 -m pytest tests/test_integration.py -v
```

The integration test exercises the full loop — question generation, answer submission, mastery updates, and adaptive difficulty — against the real Part B SQLite implementation.

## Team

| Name | Role |
|---|---|
| Kshitij | Part C — Agent Orchestration |
| [Teammate] | Part A — Voice & RAG Ingestion |
| [Teammate] | Part B — Adaptive Scoring |

## Roadmap

- Live streaming voice instead of record-then-upload
- Per-topic progress dashboard across sessions
- More modes (behavioral, take-home review)
- Periodic calibration of Evaluator scores against human graders

## License

MIT — see [LICENSE](LICENSE).
