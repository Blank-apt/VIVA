"""
Session management for Viva Part B (spec sections 24-25).

Public interface:
    save_session(session_data: dict) -> int

Plus lightweight read helpers:
    get_session(session_id) -> dict | None
    get_session_questions(session_id) -> list[dict]

SQLite is the single source of truth; no separate in-memory state
machine is maintained here (spec section 25).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .constants import validate_mode, validate_score
from .db import DEFAULT_DB_PATH, get_connection, transaction


def save_session(
    session_data: dict[str, Any],
    db_path: str | Path = DEFAULT_DB_PATH,
) -> int:
    """
    Persist a finished (or in-progress) session and its Q&A history.

    Expected shape:
        {
            "summary": "Weak in trees and graphs",
            "qa": [
                {
                    "question": "Explain BFS.",
                    "transcript": "BFS is...",
                    "score": 0.8,
                    "topic": "Graphs",
                    "mode": "fundamentals",
                    "difficulty": "medium",
                },
                ...
            ]
        }

    Runs as a single transaction: creates the session row, then inserts
    each Q&A row referencing it. On any failure, the whole write is rolled
    back and no partial session remains. Returns the new session id.
    """
    summary = session_data.get("summary")
    qa_items = session_data.get("qa", [])

    # Validate everything up front so a bad row fails before any writes.
    for item in qa_items:
        if "question" not in item or not item["question"]:
            raise ValueError("Each qa item requires a non-empty 'question'")
        if "topic" not in item or not item["topic"]:
            raise ValueError("Each qa item requires a 'topic'")
        validate_mode(item.get("mode"))
        if item.get("score") is not None:
            validate_score(item["score"])
        difficulty = item.get("difficulty")
        if difficulty is not None and difficulty not in (
            "foundational",
            "medium",
            "edge_cases",
        ):
            raise ValueError(f"Invalid difficulty: {difficulty!r}")

    with transaction(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO sessions (summary, ended_at) VALUES (?, CURRENT_TIMESTAMP)",
            (summary,),
        )
        session_id = cur.lastrowid

        for item in qa_items:
            topic_row = conn.execute(
                "SELECT id FROM topics WHERE name = ?", (item["topic"],)
            ).fetchone()
            if topic_row is None:
                raise ValueError(f"Unknown topic: {item['topic']!r}")

            conn.execute(
                """
                INSERT INTO session_qa
                    (session_id, question, transcript, score, topic_id, mode, difficulty)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    item["question"],
                    item.get("transcript"),
                    item.get("score"),
                    topic_row["id"],
                    item["mode"],
                    item.get("difficulty"),
                ),
            )

    return session_id


def start_session(
    db_path: str | Path = DEFAULT_DB_PATH,
) -> int:
    """
    Create an open session row (ended_at left NULL) for cases where the
    caller wants to persist Q&A incrementally rather than all at once
    via save_session(). Returns the new session id.
    """
    with transaction(db_path) as conn:
        cur = conn.execute("INSERT INTO sessions DEFAULT VALUES")
        return cur.lastrowid


def add_qa(
    session_id: int,
    question: str,
    topic: str,
    mode: str,
    transcript: str | None = None,
    score: float | None = None,
    difficulty: str | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> int:
    """
    Append a single Q&A row to an already-open session (created via
    start_session()). This is the incremental counterpart to
    save_session(): use it when a live interview needs to persist each
    turn as it happens (e.g. so a mid-session server restart doesn't
    lose earlier answers), rather than batching everything until the
    session ends.

    Returns the new session_qa row id.
    """
    validate_mode(mode)
    if score is not None:
        validate_score(score)
    if difficulty is not None and difficulty not in (
        "foundational",
        "medium",
        "edge_cases",
    ):
        raise ValueError(f"Invalid difficulty: {difficulty!r}")
    if not question:
        raise ValueError("question must be non-empty")

    with transaction(db_path) as conn:
        session_row = conn.execute(
            "SELECT id FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if session_row is None:
            raise ValueError(f"Unknown session_id: {session_id}")

        topic_row = conn.execute(
            "SELECT id FROM topics WHERE name = ?", (topic,)
        ).fetchone()
        if topic_row is None:
            raise ValueError(f"Unknown topic: {topic!r}")

        cur = conn.execute(
            """
            INSERT INTO session_qa
                (session_id, question, transcript, score, topic_id, mode, difficulty)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, question, transcript, score, topic_row["id"], mode, difficulty),
        )
        return cur.lastrowid


def end_session(
    session_id: int,
    summary: str | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> None:
    """
    Close an open session: sets ended_at to now, and updates summary if
    one is provided (leaves the existing summary untouched otherwise).
    """
    with transaction(db_path) as conn:
        row = conn.execute(
            "SELECT id FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Unknown session_id: {session_id}")

        conn.execute(
            """
            UPDATE sessions
            SET ended_at = CURRENT_TIMESTAMP,
                summary = COALESCE(?, summary)
            WHERE id = ?
            """,
            (summary, session_id),
        )


def get_session(
    session_id: int,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any] | None:
    """Return high-level session info, or None if it doesn't exist."""
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT id, started_at, ended_at, summary FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def get_session_questions(
    session_id: int,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict[str, Any]]:
    """Return every Q&A row for a session, in the order they were asked."""
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """
            SELECT sq.id, sq.question, sq.transcript, sq.score,
                   t.name AS topic, sq.mode, sq.difficulty, sq.created_at
            FROM session_qa sq
            JOIN topics t ON t.id = sq.topic_id
            WHERE sq.session_id = ?
            ORDER BY sq.id ASC
            """,
            (session_id,),
        ).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]
