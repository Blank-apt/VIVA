"""
Part B — Data & Scoring, public package interface.

Other parts of Viva should import from here (`from part_b import ...`)
rather than reaching into individual modules — this is the one place
the "public interface" from the original spec is re-exported.
"""

from .db import init_db
from .seed import seed_topics
from .mastery import update_mastery, get_next_difficulty, get_weakest_topics, get_mastery_overview
from .sessions import (
    save_session,
    start_session,
    add_qa,
    end_session,
    get_session,
    get_session_questions,
)
from .constants import ALLOWED_MODES, validate_mode, validate_score

__all__ = [
    "init_db",
    "seed_topics",
    "update_mastery",
    "get_next_difficulty",
    "get_weakest_topics",
    "get_mastery_overview",
    "save_session",
    "start_session",
    "add_qa",
    "end_session",
    "get_session",
    "get_session_questions",
    "ALLOWED_MODES",
    "validate_mode",
    "validate_score",
]
