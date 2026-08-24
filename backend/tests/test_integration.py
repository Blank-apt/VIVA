"""
End-to-end integration test for the assembled Viva backend.

Exercises the real FastAPI app (part_c/main.py) wired to the real Part B
SQLite layer. The only things monkeypatched are the two points that need
network/hardware we don't have in CI/sandbox:

  - the LLM call inside interviewer.py / evaluator.py (no API key here)
  - transcribe() (no ffmpeg/Whisper model download here)

Everything else — session creation, mastery updates, difficulty
adaptation, session_qa persistence, session end — runs for real against
backend/viva.db, the same database the app uses when you actually run it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # backend/ for part_b
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "part_c"))

import interviewer  # noqa: E402
import evaluator  # noqa: E402
import main  # noqa: E402
from schemas import GeneratedQuestionRaw, FundamentalsEvaluationRaw  # noqa: E402
from part_b.db import get_connection  # noqa: E402


@pytest.fixture()
def client(monkeypatch):
    # --- stub the LLM call used to author questions ---
    def fake_generate_question(*, system_prompt, user_prompt, response_model, **kwargs):
        return GeneratedQuestionRaw(
            question_text="What is the time complexity of binary search?",
            checklist=[],
        )

    monkeypatch.setattr(interviewer, "call_structured", fake_generate_question)

    # --- stub the LLM call used to grade answers: always "mostly correct" ---
    def fake_grade_answer(*, system_prompt, user_prompt, response_model, **kwargs):
        return FundamentalsEvaluationRaw(
            concept_correct=True,
            reasoning_sound=True,
            no_major_misconception=False,  # 2/3 -> score 0.667
            missed_concepts=["edge case: empty array"],
            rationale="Correct approach, missed one edge case.",
        )

    monkeypatch.setattr(evaluator, "call_structured", fake_grade_answer)

    # --- stub transcription (no ffmpeg/Whisper available here) ---
    monkeypatch.setattr(main, "transcribe", lambda audio_bytes: "O(log n) because we halve the search space each step.")

    # TestClient must be used as a context manager for FastAPI's startup
    # event (DB init + seed) to actually run before the first request.
    with TestClient(main.app) as test_client:
        yield test_client


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_full_interview_turn_updates_mastery_and_persists_qa(client):
    session_id = "integration-test-session-1"

    # 1. Ask for the next question (auto-picks weakest topic in fundamentals)
    resp = client.post(
        "/interview/next-question",
        json={"session_id": session_id, "mode": "fundamentals", "topic": "Binary Search"},
    )
    assert resp.status_code == 200
    question = resp.json()
    assert question["mode"] == "fundamentals"
    assert question["topic"] == "Binary Search"
    assert question["question_text"]
    question_id = question["question_id"]

    # Record mastery before the turn, so we can prove EMA moved it.
    conn = get_connection()
    topic_id = conn.execute(
        "SELECT id FROM topics WHERE name = 'Binary Search'"
    ).fetchone()["id"]
    before = conn.execute(
        "SELECT score FROM topic_mastery WHERE topic_id=? AND mode='fundamentals'",
        (topic_id,),
    ).fetchone()
    before_score = before["score"] if before else 0.5
    conn.close()

    # 2. Submit an answer (audio content is irrelevant, transcribe() is stubbed)
    resp = client.post(
        "/interview/submit-answer",
        json={
            "session_id": session_id,
            "question_id": question_id,
            "audio_base64": "ZmFrZSBhdWRpbyBieXRlcw==",  # "fake audio bytes"
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["transcript"] == "O(log n) because we halve the search space each step."
    # 2 of 3 fundamentals criteria met -> 2/3 = 0.666...
    assert body["evaluation"]["score"] == pytest.approx(2 / 3)
    assert body["next_difficulty"] in ("foundational", "medium", "edge_cases")

    # 3. Mastery should have moved via EMA: new = 0.7*before + 0.3*(2/3)
    conn = get_connection()
    after = conn.execute(
        "SELECT score FROM topic_mastery WHERE topic_id=? AND mode='fundamentals'",
        (topic_id,),
    ).fetchone()
    assert after is not None
    expected = 0.7 * before_score + 0.3 * (2 / 3)
    assert after["score"] == pytest.approx(expected)

    # 4. The Q&A should be persisted under this session with real content.
    qa_rows = conn.execute(
        """
        SELECT sq.question, sq.transcript, sq.score, sq.mode, t.name AS topic
        FROM session_qa sq
        JOIN topics t ON t.id = sq.topic_id
        JOIN sessions s ON s.id = sq.session_id
        ORDER BY sq.id DESC LIMIT 1
        """
    ).fetchone()
    conn.close()
    assert qa_rows["topic"] == "Binary Search"
    assert qa_rows["mode"] == "fundamentals"
    assert qa_rows["score"] == pytest.approx(2 / 3)
    assert "log n" in qa_rows["transcript"]

    # 5. End the session: ended_at should be set.
    resp = client.post(
        "/interview/end-session",
        json={"session_id": session_id, "summary": "Practiced Binary Search"},
    )
    assert resp.status_code == 200
    end_body = resp.json()
    assert end_body["ended"] is True
    backend_session_id = end_body["session_id"]

    conn = get_connection()
    session_row = conn.execute(
        "SELECT ended_at, summary FROM sessions WHERE id = ?", (backend_session_id,)
    ).fetchone()
    conn.close()
    assert session_row["ended_at"] is not None
    assert session_row["summary"] == "Practiced Binary Search"


def test_submit_answer_without_prior_question_returns_404(client):
    resp = client.post(
        "/interview/submit-answer",
        json={
            "session_id": "some-session",
            "question_id": "does-not-exist",
            "audio_base64": "ZmFrZQ==",
        },
    )
    assert resp.status_code == 404


def test_repeated_low_scores_move_difficulty_toward_foundational(client, monkeypatch):
    """
    Adaptive-difficulty demo scenario (spec section 14/22): repeatedly
    score an answer low and confirm get_next_difficulty eventually
    reflects "foundational" for that topic/mode.
    """
    def fake_grade_low(*, system_prompt, user_prompt, response_model, **kwargs):
        return FundamentalsEvaluationRaw(
            concept_correct=False,
            reasoning_sound=False,
            no_major_misconception=False,
            missed_concepts=["everything"],
            rationale="Incorrect.",
        )

    monkeypatch.setattr(evaluator, "call_structured", fake_grade_low)

    session_id = "integration-test-difficulty-drop"
    last_difficulty = None
    for _ in range(6):  # enough EMA steps from 0.5 to cross below 0.4
        resp = client.post(
            "/interview/next-question",
            json={"session_id": session_id, "mode": "fundamentals", "topic": "Hashing"},
        )
        question_id = resp.json()["question_id"]
        resp = client.post(
            "/interview/submit-answer",
            json={
                "session_id": session_id,
                "question_id": question_id,
                "audio_base64": "ZmFrZQ==",
            },
        )
        last_difficulty = resp.json()["next_difficulty"]

    assert last_difficulty == "foundational"
