"""
Maps question_id -> the GeneratedQuestion it belongs to (including its
checklist and difficulty), so /submit-answer can grade against exactly
what was asked, instead of re-deriving a checklist at eval time (which
would risk inconsistency between what was asked and what's graded).

LIMITATION: this is process-local memory. It will NOT survive a server
restart and will NOT work correctly across multiple uvicorn workers (each
worker gets its own copy — fine for `uvicorn main:app`, broken for
`uvicorn main:app --workers 4`). That's an acceptable tradeoff for a
single-process hackathon demo.

If this becomes a real problem, the fix is asking your Part B teammate to
add a column to session_qa (or a small side table) that stores the
checklist alongside each asked question, and reading it back from SQLite
here instead of from this dict. Nothing in the exposed Part B signatures
currently supports that.
"""
from __future__ import annotations

from schemas import GeneratedQuestion

_store: dict[str, GeneratedQuestion] = {}


def save_question_context(question_id: str, question: GeneratedQuestion) -> None:
    _store[question_id] = question


def get_question_context(question_id: str) -> GeneratedQuestion | None:
    return _store.get(question_id)


def discard_question_context(question_id: str) -> None:
    _store.pop(question_id, None)
