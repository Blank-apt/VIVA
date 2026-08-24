"""
Idempotent topic seeding for Viva Part B (spec section 17).

Running `seed_topics()` twice must not create duplicates — relies on the
UNIQUE constraint on topics.name plus INSERT OR IGNORE.
"""

from __future__ import annotations

from pathlib import Path

from .db import DEFAULT_DB_PATH, get_connection

# (name, category) — minimum topic set from spec section 17.
INITIAL_TOPICS: list[tuple[str, str]] = [
    # DSA
    ("Arrays", "DSA"),
    ("Strings", "DSA"),
    ("Linked Lists", "DSA"),
    ("Stack", "DSA"),
    ("Queue", "DSA"),
    ("Binary Search", "DSA"),
    ("Trees", "DSA"),
    ("Graphs", "DSA"),
    ("Dynamic Programming", "DSA"),
    ("Greedy", "DSA"),
    ("Recursion", "DSA"),
    ("Hashing", "DSA"),
    # OS
    ("Processes", "OS"),
    ("Threads", "OS"),
    ("CPU Scheduling", "OS"),
    ("Deadlocks", "OS"),
    ("Memory Management", "OS"),
    ("Virtual Memory", "OS"),
    # DBMS
    ("SQL", "DBMS"),
    ("Joins", "DBMS"),
    ("Normalization", "DBMS"),
    ("Transactions", "DBMS"),
    ("Indexing", "DBMS"),
    ("ACID", "DBMS"),
]


def seed_topics(db_path: str | Path = DEFAULT_DB_PATH) -> int:
    """
    Insert the initial topic set. Idempotent: safe to call multiple times.

    Returns the number of NEW rows inserted (0 if already seeded).
    """
    conn = get_connection(db_path)
    try:
        cur = conn.cursor()
        inserted = 0
        for name, category in INITIAL_TOPICS:
            cur.execute(
                "INSERT OR IGNORE INTO topics (name, category) VALUES (?, ?)",
                (name, category),
            )
            inserted += cur.rowcount
        conn.commit()
        return inserted
    finally:
        conn.close()


if __name__ == "__main__":
    from .db import init_db

    init_db()
    count = seed_topics()
    print(f"Seeded {count} new topic(s) (existing topics left untouched).")
