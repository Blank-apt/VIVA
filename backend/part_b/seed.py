"""
Idempotent topic seeding for Viva Part B (spec section 17).

Running `seed_topics()` twice must not create duplicates — relies on the
UNIQUE constraint on topics.name plus INSERT OR IGNORE.
"""

from __future__ import annotations

from pathlib import Path

from .db import DEFAULT_DB_PATH, get_connection

# (name, category) — starter topic set, covering common CS interview areas.
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
    ("Heaps", "DSA"),
    ("Tries", "DSA"),
    ("Sliding Window", "DSA"),
    ("Two Pointers", "DSA"),
    ("Backtracking", "DSA"),
    ("Bit Manipulation", "DSA"),
    ("Sorting Algorithms", "DSA"),
    ("Union-Find", "DSA"),
    # OS
    ("Processes", "OS"),
    ("Threads", "OS"),
    ("CPU Scheduling", "OS"),
    ("Deadlocks", "OS"),
    ("Memory Management", "OS"),
    ("Virtual Memory", "OS"),
    ("Paging and Segmentation", "OS"),
    ("Semaphores and Mutexes", "OS"),
    ("File Systems", "OS"),
    ("Inter-Process Communication", "OS"),
    # DBMS
    ("SQL", "DBMS"),
    ("Joins", "DBMS"),
    ("Normalization", "DBMS"),
    ("Transactions", "DBMS"),
    ("Indexing", "DBMS"),
    ("ACID", "DBMS"),
    ("Concurrency Control", "DBMS"),
    ("Query Optimization", "DBMS"),
    ("Views and Stored Procedures", "DBMS"),
    ("NoSQL Databases", "DBMS"),
    ("Database Sharding", "DBMS"),
    # Networking
    ("TCP/IP Basics", "Networking"),
    ("HTTP and HTTPS", "Networking"),
    ("DNS", "Networking"),
    ("REST APIs", "Networking"),
    ("Load Balancing", "Networking"),
    # OOP
    ("OOP Principles", "OOP"),
    ("Design Patterns", "OOP"),
    ("SOLID Principles", "OOP"),
    ("UML Basics", "OOP"),
    # System Design Basics
    ("Caching", "System Design"),
    ("Scalability Basics", "System Design"),
    ("CAP Theorem", "System Design"),
    ("Rate Limiting", "System Design"),
    ("Message Queues", "System Design"),
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
