"""
Interviewer agent: decides what to ask next and generates the question.

Owns the boundary with:
  - Part B (get_weakest_topics, get_next_difficulty) for topic/difficulty
    SELECTION
  - Part A (retrieve_project_context) for personalized project-mode
    questions

Question GENERATION itself goes through Kimi.

ASSUMPTION: which of the 3 modes to run next (fundamentals vs scenario vs
project) is decided by the CALLER (frontend/session flow), not by this
module. This wasn't pinned down before you asked for code, so I kept mode
selection out of scope rather than invent a heuristic you didn't sign off
on — generate_next_question() takes mode as a required argument.
"""
from __future__ import annotations

import uuid

from llm_client import call_structured
from schemas import GeneratedQuestion, GeneratedQuestionRaw, Mode
from session_store import save_question_context

# --- Part A / Part B imports ---------------------------------------------
# Replace these with the real imports once your teammates' modules land,
# e.g.:
#   from part_a.voice import retrieve_project_context
#   from part_b.scoring import get_weakest_topics, get_next_difficulty
# Stubs below let this module run standalone for testing until then.
try:
    from part_a import retrieve_project_context  # type: ignore
except ImportError:
    def retrieve_project_context(query: str) -> list[str]:
        return [f"[STUB retrieve_project_context] no Part A module found for query={query!r}"]

try:
    from part_b import get_weakest_topics, get_next_difficulty  # type: ignore
except ImportError:
    def get_weakest_topics(mode: str, n: int) -> list[str]:
        return ["arrays", "graphs", "dynamic-programming"][:n]

    def get_next_difficulty(topic: str, mode: str) -> str:
        return "medium"
# ---------------------------------------------------------------------------


FUNDAMENTALS_SYSTEM_PROMPT = (
    "You are an interviewer generating a single closed-form computer "
    "science question for a technical interview practice session. The "
    "question must have a clear, checkable correct answer. Do not include "
    "the answer in your output."
)

SCENARIO_SYSTEM_PROMPT = (
    "You are an interviewer generating an open-ended system-design "
    "question for interview practice. Along with the question, author a "
    "checklist of 3-6 atomic, independently-checkable things a strong "
    "answer should cover (e.g. specific components, tradeoffs, or failure "
    "modes). Each checklist item must be assessable as met/not-met without "
    "ambiguity."
)

PROJECT_SYSTEM_PROMPT = (
    "You are an interviewer generating a personalized interview question "
    "based on a candidate's own project/resume material provided below. "
    "Ask something that requires them to explain a real decision they "
    "made. Author a checklist of 3-5 atomic things a strong, specific "
    "answer should include, grounded in the provided project context."
)


def _generate(
    mode: Mode, topic: str, difficulty: str | None, context: list[str] | None
) -> GeneratedQuestionRaw:
    if mode == "fundamentals":
        system_prompt = FUNDAMENTALS_SYSTEM_PROMPT
        user_prompt = f"Topic: {topic}\nDifficulty: {difficulty}"
    elif mode == "scenario":
        system_prompt = SCENARIO_SYSTEM_PROMPT
        user_prompt = f"Topic area: {topic}"
    else:  # project
        system_prompt = PROJECT_SYSTEM_PROMPT
        joined_context = "\n---\n".join(context or []) or "(no project context retrieved)"
        user_prompt = f"Project context:\n{joined_context}"

    return call_structured(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        response_model=GeneratedQuestionRaw,
        schema_name=f"generated_question_{mode}",
        thinking_enabled=False,
        # Static system prompt per mode -> cacheable prefix across calls.
        prompt_cache_key=f"interviewer-{mode}",
    )


def generate_next_question(mode: Mode, topic: str | None = None) -> GeneratedQuestion:
    """
    Picks a topic (via Part B, if not given), picks difficulty (fundamentals
    only), pulls RAG context (via Part A, project mode only), generates the
    question via Kimi, and stashes the checklist server-side so the
    Evaluator can grade against the SAME checklist later.
    """
    if topic is None:
        weakest = get_weakest_topics(mode, 1)
        topic = weakest[0] if weakest else "general"

    difficulty = get_next_difficulty(topic, mode) if mode == "fundamentals" else None

    context = None
    if mode == "project":
        context = retrieve_project_context(topic)

    raw = _generate(mode, topic, difficulty, context)

    question_id = str(uuid.uuid4())
    question = GeneratedQuestion(
        question_id=question_id,
        mode=mode,
        topic=topic,
        difficulty=difficulty,
        question_text=raw.question_text,
        checklist=raw.checklist,
    )

    save_question_context(question_id, question)
    return question
