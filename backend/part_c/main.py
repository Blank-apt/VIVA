"""
FastAPI app for Part C: Agent Orchestration.

Wires the Interviewer and Evaluator agents to Part A (voice/RAG) and
Part B (scoring/session state). Run with:

    uvicorn main:app --reload

Required environment variable (one of, depending on LLM_PROVIDER):
    MISTRAL_API_KEY / GROQ_API_KEY / MOONSHOT_API_KEY   (see config.py)

See README.md for the full integration contract (request/response JSON).
"""
from __future__ import annotations

import _pathfix  # noqa: F401  (must run before part_a/part_b imports below)
import base64

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from evaluator import evaluate
from interviewer import generate_next_question
from schemas import (
    EndSessionRequest,
    EndSessionResponse,
    GeneratedQuestion,
    MasteryTopic,
    NextQuestionRequest,
    SessionHistoryResponse,
    SessionQAItem,
    SubmitAnswerRequest,
    SubmitAnswerResponse,
)
from session_store import (
    discard_question_context,
    get_or_create_backend_session,
    get_question_context,
    forget_backend_session,
)

# --- Part A / Part B imports ----------------------------------------------
# part_a and part_b are real sibling packages now (see _pathfix.py). Stubs
# remain as a fallback so this app still boots (in a degraded mode) if a
# teammate's dependencies (e.g. faster-whisper) aren't installed locally.
try:
    from part_a import transcribe  # type: ignore
except ImportError:
    def transcribe(audio: bytes) -> str:
        return "[STUB transcribe] Part A module not found — wire in the real transcribe()"

try:
    from part_b import (  # type: ignore
        init_db,
        seed_topics,
        update_mastery,
        get_next_difficulty,
        get_mastery_overview,
        add_qa,
        end_session as end_session_in_db,
        get_session,
        get_session_questions,
    )
except ImportError:
    def init_db() -> None:
        print("[STUB init_db] Part B module not found")

    def seed_topics() -> int:
        print("[STUB seed_topics] Part B module not found")
        return 0

    def update_mastery(topic: str, mode: str, score: float) -> None:
        print(f"[STUB update_mastery] topic={topic} mode={mode} score={score}")

    def get_next_difficulty(topic: str, mode: str) -> str:
        return "medium"

    def get_mastery_overview(mode: str) -> list[dict]:
        return []

    def add_qa(session_id, question, topic, mode, **kwargs) -> int:
        print(f"[STUB add_qa] session={session_id} topic={topic} mode={mode}")
        return -1

    def end_session_in_db(session_id, summary=None) -> None:
        print(f"[STUB end_session] session={session_id} summary={summary}")

    def get_session(session_id):
        return None

    def get_session_questions(session_id):
        return []
# ---------------------------------------------------------------------------


app = FastAPI(title="Viva - Part C: Agent Orchestration")

# Allow a locally-running Streamlit frontend (different port) to call this
# API directly from the browser. Wide open for hackathon/dev purposes only.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _ensure_db_ready() -> None:
    """
    Create the SQLite schema and seed topics, so a fresh checkout "just
    works" with no manual setup step. Safe to call multiple times — both
    init_db() and seed_topics() are idempotent.

    Called both eagerly at import time (belt-and-suspenders for test
    clients / deployment setups that don't run FastAPI's lifespan) and
    again from the lifespan handler below (the normal `uvicorn main:app`
    path).
    """
    init_db()
    seed_topics()


_ensure_db_ready()


@app.post("/interview/next-question", response_model=GeneratedQuestion)
def next_question(req: NextQuestionRequest) -> GeneratedQuestion:
    # Ensure a Part B session row exists for this frontend session_id
    # before we generate a question, so add_qa() always has somewhere
    # to write to later.
    try:
        get_or_create_backend_session(req.session_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not start session: {exc}")

    try:
        return generate_next_question(mode=req.mode, topic=req.topic)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Question generation failed: {exc}")


@app.post("/interview/submit-answer", response_model=SubmitAnswerResponse)
def submit_answer(req: SubmitAnswerRequest) -> SubmitAnswerResponse:
    question = get_question_context(req.question_id)
    if question is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No stored question for question_id={req.question_id!r} "
                "(server restarted, or /next-question was never called for it)"
            ),
        )

    # --- Part A: speech-to-text, OR a typed-answer bypass ---
    # transcript_override lets a text-only frontend (or a real audio
    # frontend that also offers a "type instead" fallback) skip transcribe()
    # entirely — useful since real speech-to-text needs ffmpeg + a Whisper
    # model that not every environment has installed.
    if req.transcript_override is not None:
        transcript = req.transcript_override
    else:
        if not req.audio_base64:
            raise HTTPException(
                status_code=400,
                detail="Provide either audio_base64 or transcript_override.",
            )
        try:
            audio_bytes = base64.b64decode(req.audio_base64)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid base64 audio: {exc}")

        try:
            transcript = transcribe(audio_bytes)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"transcribe() failed: {exc}")

    # --- Part C: evaluate (score is already normalized to 0.0-1.0) ---
    try:
        evaluation = evaluate(question, transcript)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Evaluator failed: {exc}")

    # --- Part B: update mastery + persist this turn's Q&A ---
    try:
        backend_session_id = get_or_create_backend_session(req.session_id)

        update_mastery(question.topic, question.mode, evaluation.score)

        add_qa(
            session_id=backend_session_id,
            question=question.question_text,
            topic=question.topic,
            mode=question.mode,
            transcript=transcript,
            score=evaluation.score,
            difficulty=question.difficulty,
        )

        next_difficulty = get_next_difficulty(question.topic, question.mode)
    except Exception as exc:
        # Evaluation succeeded but persistence failed — surface it clearly
        # rather than silently dropping the candidate's earned evaluation.
        raise HTTPException(
            status_code=502, detail=f"Part B call failed after evaluation: {exc}"
        )

    discard_question_context(req.question_id)

    return SubmitAnswerResponse(
        transcript=transcript,
        evaluation=evaluation,
        next_difficulty=next_difficulty,
    )


@app.post("/interview/end-session", response_model=EndSessionResponse)
def end_session(req: EndSessionRequest) -> EndSessionResponse:
    """
    Closes out the interview session: sets ended_at (+ summary, if given)
    on the Part B session row, and forgets the frontend<->backend session
    mapping so a later call with the same frontend session_id starts a
    fresh session rather than reopening this one.
    """
    try:
        backend_session_id = get_or_create_backend_session(req.session_id)
        end_session_in_db(backend_session_id, summary=req.summary)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not end session: {exc}")

    forget_backend_session(req.session_id)

    return EndSessionResponse(session_id=backend_session_id, ended=True)


@app.get("/mastery/{mode}", response_model=list[MasteryTopic])
def mastery_overview(mode: str) -> list[MasteryTopic]:
    """
    Every topic's current mastery for `mode`, weakest first — powers a
    frontend dashboard (e.g. a bar chart) showing the full mastery picture,
    not just the single weakest topic used internally for question
    selection.
    """
    try:
        overview = get_mastery_overview(mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not load mastery: {exc}")
    return [MasteryTopic(**row) for row in overview]


@app.get("/interview/session/{session_id}", response_model=SessionHistoryResponse)
def session_history(session_id: str) -> SessionHistoryResponse:
    """
    Full history (summary + every Q&A) for a frontend session_id — powers
    a "review this session" screen. Looks up the mapped Part B integer
    session id the same way /submit-answer and /end-session do.
    """
    try:
        backend_session_id = get_or_create_backend_session(session_id)
        session = get_session(backend_session_id)
        qa_rows = get_session_questions(backend_session_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not load session: {exc}")

    if session is None:
        raise HTTPException(status_code=404, detail=f"No such session: {session_id}")

    return SessionHistoryResponse(
        session_id=backend_session_id,
        started_at=str(session.get("started_at")) if session.get("started_at") else None,
        ended_at=str(session.get("ended_at")) if session.get("ended_at") else None,
        summary=session.get("summary"),
        qa=[
            SessionQAItem(
                id=row["id"],
                question=row["question"],
                transcript=row.get("transcript"),
                score=row.get("score"),
                topic=row["topic"],
                mode=row["mode"],
                difficulty=row.get("difficulty"),
                created_at=str(row["created_at"]),
            )
            for row in qa_rows
        ],
    )


@app.get("/health")
def health():
    return {"status": "ok"}
