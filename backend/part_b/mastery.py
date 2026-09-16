"""
Mastery engine for Viva Part B (spec sections 19-23).

Public interface:
    update_mastery(topic, mode, score) -> None
    get_next_difficulty(topic, mode) -> str
    get_weakest_topics(mode, n) -> list[str]

Callers interact only through these functions — no direct SQLite access
from other agents (spec section 11).
"""

from __future__ import annotations

from pathlib import Path

from .constants import (
    DEFAULT_MASTERY,
    DIFFICULTY_EDGE_CASES,
    DIFFICULTY_FOUNDATIONAL,
    DIFFICULTY_HIGH_THRESHOLD,
    DIFFICULTY_LOW_THRESHOLD,
    DIFFICULTY_MEDIUM,
    EMA_NEW_WEIGHT,
    EMA_OLD_WEIGHT,
    validate_mode,
    validate_score,
)
from .db import DEFAULT_DB_PATH, get_connection, transaction


def _get_topic_id(conn, topic: str) -> int:
    """Look up a topic's id by name, or raise ValueError if unknown."""
    row = conn.execute(
        "SELECT id FROM topics WHERE name = ?", (topic,)
    ).fetchone()
    if row is None:
        raise ValueError(f"Unknown topic: {topic!r}")
    return row["id"]


def _get_current_mastery(conn, topic_id: int, mode: str) -> float:
    """
    Return the current mastery score for (topic_id, mode), or the
    default (0.5) if no record exists yet — an "unseen" topic/mode
    (spec section 22).
    """
    row = conn.execute(
        "SELECT score FROM topic_mastery WHERE topic_id = ? AND mode = ?",
        (topic_id, mode),
    ).fetchone()
    if row is None:
        return DEFAULT_MASTERY
    return row["score"]


def update_mastery(
    topic: str,
    mode: str,
    score: float,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> None:
    """
    Update mastery for (topic, mode) using an EMA of the current answer score.

        new_score = 0.7 * old_score + 0.3 * current_answer_score

    If no mastery record exists yet, old_score defaults to 0.5.
    Uses an UPSERT so (topic_id, mode) stays unique (spec section 20).
    """
    validate_mode(mode)
    validate_score(score)

    with transaction(db_path) as conn:
        topic_id = _get_topic_id(conn, topic)
        old_score = _get_current_mastery(conn, topic_id, mode)
        new_score = EMA_OLD_WEIGHT * old_score + EMA_NEW_WEIGHT * score

        conn.execute(
            """
            INSERT INTO topic_mastery (topic_id, mode, score, last_updated)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(topic_id, mode) DO UPDATE SET
                score = excluded.score,
                last_updated = CURRENT_TIMESTAMP
            """,
            (topic_id, mode, new_score),
        )


def get_next_difficulty(
    topic: str,
    mode: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> str:
    """
    Map current mastery for (topic, mode) to a difficulty bucket
    (spec section 21):

        score < 0.4        -> foundational
        0.4 <= score <= 0.7 -> medium
        score > 0.7         -> edge_cases

    Unseen topics use the default mastery of 0.5 -> medium.
    """
    validate_mode(mode)

    conn = get_connection(db_path)
    try:
        topic_id = _get_topic_id(conn, topic)
        score = _get_current_mastery(conn, topic_id, mode)
    finally:
        conn.close()

    if score < DIFFICULTY_LOW_THRESHOLD:
        return DIFFICULTY_FOUNDATIONAL
    if score > DIFFICULTY_HIGH_THRESHOLD:
        return DIFFICULTY_EDGE_CASES
    return DIFFICULTY_MEDIUM


def get_weakest_topics(
    mode: str,
    n: int,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[str]:
    """
    Return the `n` topic names with the lowest mastery for `mode`
    (spec section 23).

    Topics never scored in this mode are treated as mastery 0.5
    (i.e. as if a topic_mastery row of 0.5 existed), so they compete
    fairly against topics with recorded mastery below/above 0.5.
    Ties are broken by topic name for determinism.
    """
    validate_mode(mode)
    if n < 0:
        raise ValueError("n must be non-negative")

    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """
            SELECT t.name AS name,
                   COALESCE(tm.score, ?) AS effective_score
            FROM topics t
            LEFT JOIN topic_mastery tm
                ON tm.topic_id = t.id AND tm.mode = ?
            ORDER BY effective_score ASC, t.name ASC
            LIMIT ?
            """,
            (DEFAULT_MASTERY, mode, n),
        ).fetchall()
    finally:
        conn.close()

    return [row["name"] for row in rows]


def get_mastery_overview(
    mode: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict]:
    """
    Return every topic's current mastery for `mode`, sorted weakest first —
    the full picture behind get_weakest_topics(), for UI dashboards that
    want to show all topics (e.g. a bar chart), not just the top-n weakest.

    Each item: {"topic": str, "score": float, "difficulty": str}.
    Unseen topics use the default mastery (0.5), same as get_weakest_topics.
    """
    validate_mode(mode)

    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """
            SELECT t.name AS name,
                   COALESCE(tm.score, ?) AS effective_score
            FROM topics t
            LEFT JOIN topic_mastery tm
                ON tm.topic_id = t.id AND tm.mode = ?
            ORDER BY effective_score ASC, t.name ASC
            """,
            (DEFAULT_MASTERY, mode),
        ).fetchall()
    finally:
        conn.close()

    overview = []
    for row in rows:
        score = row["effective_score"]
        if score < DIFFICULTY_LOW_THRESHOLD:
            difficulty = DIFFICULTY_FOUNDATIONAL
        elif score > DIFFICULTY_HIGH_THRESHOLD:
            difficulty = DIFFICULTY_EDGE_CASES
        else:
            difficulty = DIFFICULTY_MEDIUM
        overview.append({"topic": row["name"], "score": score, "difficulty": difficulty})
    return overview
