"""
FastAPI app for Part C: Agent Orchestration.

Wires the Interviewer and Evaluator agents to Part A (voice/RAG) and
Part B (scoring/session state). Run with:

    uvicorn main:app --reload

Required environment variable:
    MOONSHOT_API_KEY   Kimi API key (see config.py)

See README.md for the full integration contract (request/response JSON,
assumptions made about Part A/B, and what to confirm with your teammates).
"""
from __future__ import annotations

import base64

from fastapi import FastAPI, HTTPException

from evaluator import evaluate
from interviewer import generate_next_question
from schemas import (
    GeneratedQuestion,
    NextQuestionRequest,
    SubmitAnswerRequest,
    SubmitAnswerResponse,
)
from session_store import discard_question_context, get_question_context

# --- Part A / Part B imports ---------------------------------------------
# Replace with real imports once available, e.g.:
#   from part_a.voice import transcribe
#   from part_b.scoring import update_mastery, save_session, get_next_difficulty
# Stubs below let the API run standalone for testing until then.
try:
    from part_a import transcribe  # type: ignore
except ImportError:
    def transcribe(audio: bytes) -> str:
        return "[STUB transcribe] Part A module not found — wire in the real transcribe()"

try:
    from part_b import update_mastery, save_session, get_next_difficulty  # type: ignore
except ImportError:
    def update_mastery(topic: str, mode: str, score: float) -> None:
        print(f"[STUB update_mastery] topic={topic} mode={mode} score={score}")

    def save_session(data: dict) -> int:
        print(f"[STUB save_session] {data}")
        return -1

    def get_next_difficulty(topic: str, mode: str) -> str:
        return "medium"
# ---------------------------------------------------------------------------


app = FastAPI(title="Viva - Part C: Agent Orchestration")


@app.post("/interview/next-question", response_model=GeneratedQuestion)
def next_question(req: NextQuestionRequest) -> GeneratedQuestion:
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

    try:
        audio_bytes = base64.b64decode(req.audio_base64)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid base64 audio: {exc}")

    # --- Part A: speech-to-text ---
    try:
        transcript = transcribe(audio_bytes)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"transcribe() failed: {exc}")

    # --- Part C: evaluate ---
    try:
        evaluation = evaluate(question, transcript)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Evaluator failed: {exc}")

    # --- Part B: update mastery + persist session ---
    try:
        update_mastery(question.topic, question.mode, evaluation.score)
        save_session(
            {
                "session_id": req.session_id,
                "question_id": question.question_id,
                "mode": question.mode,
                "topic": question.topic,
                "difficulty": question.difficulty,
                "question_text": question.question_text,
                "transcript": transcript,
                "score": evaluation.score,
                "rationale": evaluation.rationale,
            }
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


@app.get("/health")
def health():
    return {"status": "ok"}
