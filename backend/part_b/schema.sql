-- Viva — Part B: Data & Scoring
-- Finalized schema (see project spec, section 12). Do not redesign without strong reason.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS topics (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS topic_mastery (
    topic_id INTEGER NOT NULL,
    mode TEXT NOT NULL,
    score REAL NOT NULL CHECK(score >= 0 AND score <= 1),
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (topic_id, mode),
    FOREIGN KEY (topic_id) REFERENCES topics(id)
);

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ended_at TIMESTAMP,
    summary TEXT
);

CREATE TABLE IF NOT EXISTS session_qa (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL,
    question TEXT NOT NULL,
    transcript TEXT,
    score REAL CHECK(score >= 0 AND score <= 1),
    topic_id INTEGER NOT NULL,
    mode TEXT NOT NULL,
    difficulty TEXT CHECK(
        difficulty IN ('foundational', 'medium', 'edge_cases')
    ),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (session_id) REFERENCES sessions(id),
    FOREIGN KEY (topic_id) REFERENCES topics(id)
);

CREATE INDEX IF NOT EXISTS idx_session_qa_session_id ON session_qa(session_id);
CREATE INDEX IF NOT EXISTS idx_session_qa_topic_id ON session_qa(topic_id);
CREATE INDEX IF NOT EXISTS idx_topic_mastery_mode ON topic_mastery(mode);
