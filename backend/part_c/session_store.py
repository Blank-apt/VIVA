"""
Two process-local mappings used to bridge Part C's request-scoped values
to Part B's persistent state:

1. question_id -> the GeneratedQuestion it belongs to (including its
   checklist and difficulty), so /submit-answer can grade against exactly
   what was asked, instead of re-deriving a checklist at eval time (which
   would risk inconsistency between what was asked and what's graded).

2. frontend session_id (str, chosen by the caller) -> Part B's integer
   sessions.id (the actual primary key in SQLite). The frontend/caller
   never needs to know about Part B's integer PK; this module is the only
   place that translation happens.

LIMITATION (documented, accepted tradeoff for a hackathon-scale single
process demo): both mappings are process-local memory. They will NOT
survive a server restart and will NOT work correctly across multiple
uvicorn workers (each worker gets its own copy — fine for
`uvicorn main:app`, broken for `uvicorn main:app --workers 4`).

Concretely: if the server restarts mid-session, the *already-answered*
Q&A for that session is still safe (each turn is persisted to SQLite via
add_qa() as it happens — see main.py), but the frontend's session_id will
no longer map to that Part B session row, so the app will treat the next
turn as belonging to a brand-new session. This only loses the *mapping*,
never previously-saved answers or mastery.

If this becomes a real problem, the fix is a small `sessions` side-column
or lookup table on Part B's side keyed by an external session token. Not
needed for the current spec/scale.
"""
from __future__ import annotations

import _pathfix  # noqa: F401  (must run before the deferred part_b import below)
from schemas import GeneratedQuestion

_question_store: dict[str, GeneratedQuestion] = {}
_session_id_map: dict[str, int] = {}


def save_question_context(question_id: str, question: GeneratedQuestion) -> None:
    _question_store[question_id] = question


def get_question_context(question_id: str) -> GeneratedQuestion | None:
    return _question_store.get(question_id)


def discard_question_context(question_id: str) -> None:
    _question_store.pop(question_id, None)


def get_or_create_backend_session(frontend_session_id: str) -> int:
    """
    Look up the Part B integer session id for a given frontend session_id,
    creating a new Part B session row (via start_session()) the first time
    a given frontend_session_id is seen.
    """
    if frontend_session_id not in _session_id_map:
        from part_b import start_session  # local import: avoid import-order issues with _pathfix

        _session_id_map[frontend_session_id] = start_session()
    return _session_id_map[frontend_session_id]


def forget_backend_session(frontend_session_id: str) -> None:
    """Drop the mapping so a later reuse of this frontend_session_id starts fresh."""
    _session_id_map.pop(frontend_session_id, None)
