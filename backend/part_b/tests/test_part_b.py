"""
Tests for Viva Part B — Data & Scoring (spec section 26).

Each test gets a fresh temporary SQLite file so tests are isolated and
can run in any order without interfering with each other or with the
real viva.db used by the app.
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from part_b.db import init_db, get_connection
from part_b.seed import seed_topics
from part_b.mastery import update_mastery, get_next_difficulty, get_weakest_topics
from part_b.sessions import (
    save_session,
    start_session,
    add_qa,
    end_session,
    get_session,
    get_session_questions,
)


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "test_viva.db"
    init_db(path)
    seed_topics(path)
    return path


# ---------------------------------------------------------------------------
# Database tests
# ---------------------------------------------------------------------------

def test_tables_exist(db_path):
    conn = get_connection(db_path)
    tables = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    conn.close()
    assert {"topics", "topic_mastery", "sessions", "session_qa"} <= tables


def test_foreign_keys_enforced(db_path):
    conn = get_connection(db_path)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO topic_mastery (topic_id, mode, score) VALUES (9999, 'fundamentals', 0.5)"
        )
        conn.commit()
    conn.close()


def test_duplicate_topic_rejected(db_path):
    conn = get_connection(db_path)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO topics (name, category) VALUES ('Arrays', 'DSA')"
        )
        conn.commit()
    conn.close()


def test_duplicate_mastery_pair_rejected(db_path):
    conn = get_connection(db_path)
    topic_id = conn.execute(
        "SELECT id FROM topics WHERE name = 'Arrays'"
    ).fetchone()["id"]
    conn.execute(
        "INSERT INTO topic_mastery (topic_id, mode, score) VALUES (?, 'fundamentals', 0.6)",
        (topic_id,),
    )
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO topic_mastery (topic_id, mode, score) VALUES (?, 'fundamentals', 0.7)",
            (topic_id,),
        )
        conn.commit()
    conn.close()


def test_seeding_is_idempotent(db_path):
    conn = get_connection(db_path)
    before = conn.execute("SELECT COUNT(*) AS c FROM topics").fetchone()["c"]
    conn.close()

    inserted = seed_topics(db_path)  # seed again
    assert inserted == 0

    conn = get_connection(db_path)
    after = conn.execute("SELECT COUNT(*) AS c FROM topics").fetchone()["c"]
    conn.close()
    assert before == after


# ---------------------------------------------------------------------------
# EMA tests
# ---------------------------------------------------------------------------

def test_ema_first_update_uses_default_old_score(db_path):
    update_mastery("Arrays", "fundamentals", 0.8, db_path)
    conn = get_connection(db_path)
    row = conn.execute(
        """
        SELECT tm.score FROM topic_mastery tm
        JOIN topics t ON t.id = tm.topic_id
        WHERE t.name = 'Arrays' AND tm.mode = 'fundamentals'
        """
    ).fetchone()
    conn.close()
    # 0.7 * 0.5 + 0.3 * 0.8 = 0.59
    assert row["score"] == pytest.approx(0.59)


def test_ema_second_update_uses_prior_score(db_path):
    update_mastery("Arrays", "fundamentals", 0.8, db_path)  # -> 0.59
    update_mastery("Arrays", "fundamentals", 0.2, db_path)  # -> 0.7*0.8 + 0.3*0.2? no, uses 0.59
    conn = get_connection(db_path)
    row = conn.execute(
        """
        SELECT tm.score FROM topic_mastery tm
        JOIN topics t ON t.id = tm.topic_id
        WHERE t.name = 'Arrays' AND tm.mode = 'fundamentals'
        """
    ).fetchone()
    conn.close()
    # 0.7 * 0.59 + 0.3 * 0.2 = 0.473
    assert row["score"] == pytest.approx(0.473)


def test_ema_spec_example_08_then_02(db_path):
    # Spec section 26 example: 0.8 + answer 0.2 -> 0.62
    update_mastery("Trees", "fundamentals", 0.8, db_path)  # from default 0.5 -> 0.59, not 0.8
    # To hit the literal spec example (old=0.8, answer=0.2 -> 0.62), seed old=0.8 directly.
    conn = get_connection(db_path)
    topic_id = conn.execute("SELECT id FROM topics WHERE name='Trees'").fetchone()["id"]
    conn.execute(
        "UPDATE topic_mastery SET score = 0.8 WHERE topic_id = ? AND mode = 'fundamentals'",
        (topic_id,),
    )
    conn.commit()
    conn.close()

    update_mastery("Trees", "fundamentals", 0.2, db_path)
    conn = get_connection(db_path)
    row = conn.execute(
        "SELECT score FROM topic_mastery WHERE topic_id = ? AND mode = 'fundamentals'",
        (topic_id,),
    ).fetchone()
    conn.close()
    assert row["score"] == pytest.approx(0.62)


def test_update_mastery_rejects_invalid_mode(db_path):
    with pytest.raises(ValueError):
        update_mastery("Arrays", "not-a-mode", 0.5, db_path)


def test_update_mastery_rejects_invalid_score(db_path):
    with pytest.raises(ValueError):
        update_mastery("Arrays", "fundamentals", 1.5, db_path)
    with pytest.raises(ValueError):
        update_mastery("Arrays", "fundamentals", -0.1, db_path)


# ---------------------------------------------------------------------------
# Boundary / difficulty tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw_score,expected",
    [
        (0.39, "foundational"),
        (0.40, "medium"),
        (0.70, "medium"),
        (0.71, "edge_cases"),
    ],
)
def test_difficulty_boundaries(db_path, raw_score, expected):
    conn = get_connection(db_path)
    topic_id = conn.execute("SELECT id FROM topics WHERE name='Graphs'").fetchone()["id"]
    conn.execute(
        "INSERT INTO topic_mastery (topic_id, mode, score) VALUES (?, 'fundamentals', ?)",
        (topic_id, raw_score),
    )
    conn.commit()
    conn.close()

    assert get_next_difficulty("Graphs", "fundamentals", db_path) == expected


def test_difficulty_unseen_topic_defaults_to_medium(db_path):
    # never scored -> default mastery 0.5 -> medium
    assert get_next_difficulty("Hashing", "fundamentals", db_path) == "medium"


# ---------------------------------------------------------------------------
# Mode isolation tests
# ---------------------------------------------------------------------------

def test_mode_isolation(db_path):
    update_mastery("Arrays", "fundamentals", 0.9, db_path)
    update_mastery("Arrays", "scenario", 0.1, db_path)

    conn = get_connection(db_path)
    topic_id = conn.execute("SELECT id FROM topics WHERE name='Arrays'").fetchone()["id"]
    fund = conn.execute(
        "SELECT score FROM topic_mastery WHERE topic_id=? AND mode='fundamentals'", (topic_id,)
    ).fetchone()["score"]
    scen = conn.execute(
        "SELECT score FROM topic_mastery WHERE topic_id=? AND mode='scenario'", (topic_id,)
    ).fetchone()["score"]
    conn.close()

    assert fund != scen
    assert fund == pytest.approx(0.7 * 0.5 + 0.3 * 0.9)
    assert scen == pytest.approx(0.7 * 0.5 + 0.3 * 0.1)


# ---------------------------------------------------------------------------
# Weakest-topic tests
# ---------------------------------------------------------------------------

def test_weakest_topics_ordering(db_path):
    # Arrays 0.82, Trees 0.31, Graphs 0.47, DP 0.25 (spec section 23 example)
    for name, score in [
        ("Arrays", 0.82),
        ("Trees", 0.31),
        ("Graphs", 0.47),
        ("Dynamic Programming", 0.25),
    ]:
        conn = get_connection(db_path)
        topic_id = conn.execute("SELECT id FROM topics WHERE name=?", (name,)).fetchone()["id"]
        conn.execute(
            "INSERT INTO topic_mastery (topic_id, mode, score) VALUES (?, 'fundamentals', ?)",
            (topic_id, score),
        )
        conn.commit()
        conn.close()

    weakest = get_weakest_topics("fundamentals", 3, db_path)
    assert weakest == ["Dynamic Programming", "Trees", "Graphs"]


def test_weakest_topics_treats_unseen_as_default(db_path):
    # Only score one topic very high; unseen topics (0.5) should rank
    # above/below it depending on relation to 0.5.
    update_mastery("Arrays", "fundamentals", 1.0, db_path)  # -> 0.65, still below 0.5? no 0.65>0.5
    weakest = get_weakest_topics("fundamentals", 1, db_path)
    # Arrays should NOT be the weakest since its score (0.65) > unseen default (0.5)
    assert weakest[0] != "Arrays"


def test_weakest_topics_rejects_invalid_mode(db_path):
    with pytest.raises(ValueError):
        get_weakest_topics("bogus-mode", 3, db_path)


# ---------------------------------------------------------------------------
# Session tests
# ---------------------------------------------------------------------------

def test_save_session_creates_session_and_qa(db_path):
    session_data = {
        "summary": "Weak in trees and graphs",
        "qa": [
            {
                "question": "Explain BFS.",
                "transcript": "BFS is a graph traversal...",
                "score": 0.8,
                "topic": "Graphs",
                "mode": "fundamentals",
                "difficulty": "medium",
            },
            {
                "question": "What is a balanced tree?",
                "transcript": "A tree where heights differ by at most one.",
                "score": 0.6,
                "topic": "Trees",
                "mode": "fundamentals",
                "difficulty": "medium",
            },
        ],
    }
    session_id = save_session(session_data, db_path)
    assert isinstance(session_id, int)

    session = get_session(session_id, db_path)
    assert session is not None
    assert session["summary"] == "Weak in trees and graphs"
    assert session["ended_at"] is not None

    questions = get_session_questions(session_id, db_path)
    assert len(questions) == 2
    assert {q["topic"] for q in questions} == {"Graphs", "Trees"}


def test_save_session_rolls_back_on_bad_topic(db_path):
    session_data = {
        "summary": "broken session",
        "qa": [
            {
                "question": "Valid question",
                "score": 0.5,
                "topic": "Arrays",
                "mode": "fundamentals",
                "difficulty": "medium",
            },
            {
                "question": "Bad topic question",
                "score": 0.5,
                "topic": "NotARealTopic",
                "mode": "fundamentals",
                "difficulty": "medium",
            },
        ],
    }
    before_count = _count_sessions(db_path)
    with pytest.raises(ValueError):
        save_session(session_data, db_path)
    after_count = _count_sessions(db_path)
    # No partial session should remain.
    assert before_count == after_count


def test_save_session_rejects_invalid_mode(db_path):
    session_data = {
        "summary": "bad mode",
        "qa": [
            {
                "question": "Q",
                "score": 0.5,
                "topic": "Arrays",
                "mode": "not-a-real-mode",
                "difficulty": "medium",
            }
        ],
    }
    with pytest.raises(ValueError):
        save_session(session_data, db_path)


def _count_sessions(db_path) -> int:
    conn = get_connection(db_path)
    count = conn.execute("SELECT COUNT(*) AS c FROM sessions").fetchone()["c"]
    conn.close()
    return count


# ---------------------------------------------------------------------------
# End-to-end / persistence-across-restart style test
# ---------------------------------------------------------------------------

def test_start_session_creates_open_session(db_path):
    session_id = start_session(db_path)
    session = get_session(session_id, db_path)
    assert session is not None
    assert session["ended_at"] is None


def test_add_qa_appends_to_open_session(db_path):
    session_id = start_session(db_path)
    qa_id_1 = add_qa(
        session_id,
        question="Explain BFS.",
        topic="Graphs",
        mode="fundamentals",
        transcript="BFS visits neighbors level by level.",
        score=0.7,
        difficulty="medium",
        db_path=db_path,
    )
    qa_id_2 = add_qa(
        session_id,
        question="What is a balanced tree?",
        topic="Trees",
        mode="fundamentals",
        transcript="Heights differ by at most one.",
        score=0.6,
        difficulty="medium",
        db_path=db_path,
    )
    assert qa_id_1 != qa_id_2

    questions = get_session_questions(session_id, db_path)
    assert len(questions) == 2
    assert {q["topic"] for q in questions} == {"Graphs", "Trees"}

    # Session should still be open (add_qa must not close it).
    session = get_session(session_id, db_path)
    assert session["ended_at"] is None


def test_add_qa_rejects_unknown_session(db_path):
    with pytest.raises(ValueError):
        add_qa(
            999999,
            question="Q",
            topic="Arrays",
            mode="fundamentals",
            db_path=db_path,
        )


def test_add_qa_rejects_unknown_topic(db_path):
    session_id = start_session(db_path)
    with pytest.raises(ValueError):
        add_qa(
            session_id,
            question="Q",
            topic="NotARealTopic",
            mode="fundamentals",
            db_path=db_path,
        )


def test_end_session_sets_ended_at_and_summary(db_path):
    session_id = start_session(db_path)
    add_qa(
        session_id,
        question="Explain recursion.",
        topic="Recursion",
        mode="fundamentals",
        score=0.5,
        db_path=db_path,
    )
    end_session(session_id, summary="Practiced recursion basics", db_path=db_path)

    session = get_session(session_id, db_path)
    assert session["ended_at"] is not None
    assert session["summary"] == "Practiced recursion basics"


def test_end_session_rejects_unknown_session(db_path):
    with pytest.raises(ValueError):
        end_session(999999, db_path=db_path)


def test_persistence_across_reconnect(tmp_path):
    """
    Simulates an application restart: open connection, write data, close;
    reopen a fresh connection to the same file, confirm data remains.
    """
    path = tmp_path / "persist_test.db"
    init_db(path)
    seed_topics(path)

    update_mastery("Trees", "fundamentals", 0.2, path)
    session_id = save_session(
        {
            "summary": "First session",
            "qa": [
                {
                    "question": "What is a BST?",
                    "score": 0.2,
                    "topic": "Trees",
                    "mode": "fundamentals",
                    "difficulty": "foundational",
                }
            ],
        },
        path,
    )

    # "Restart": new connection object, same file.
    weakest = get_weakest_topics("fundamentals", 1, path)
    assert weakest == ["Trees"]

    session = get_session(session_id, path)
    assert session["summary"] == "First session"
