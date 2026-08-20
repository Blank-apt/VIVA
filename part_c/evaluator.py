"""
Evaluator agent: scores a transcribed answer against the question it was
asked, per the mode-specific rubric.

Design: Kimi is only ever asked for a COARSE, categorical judgment
(booleans / checklist met-or-not / 3-way label) plus a rationale. The
numeric score handed to Part B's update_mastery() is computed
deterministically here in Python — LLM judges are unreliable at
fine-grained numeric scoring (this is a documented finding, not a
guess — see prior discussion), so the model only does the part it's
actually good at: point-counting, not arithmetic.
"""
from __future__ import annotations

from llm_client import call_structured
from schemas import (
    EvaluationResult,
    FundamentalsEvaluationRaw,
    GeneratedQuestion,
    OpenEndedEvaluationRaw,
)

FUNDAMENTALS_EVAL_PROMPT = (
    "You are grading a spoken answer to a closed-form technical question. "
    "Judge three things independently: whether the core concept is "
    "correct, whether the reasoning given is sound, and whether the "
    "answer contains any major misconception. List any key concepts the "
    "answer missed. Be strict but fair — partial credit lives in these "
    "three flags, not in a numeric score you'd have to invent."
)

OPEN_ENDED_EVAL_PROMPT = (
    "You are grading a spoken answer against a fixed checklist of "
    "criteria. For each checklist item, decide independently whether the "
    "answer meets it (a criterion can be considered met even if phrased "
    "differently than the checklist wording, as long as the substance is "
    "there). Do not invent extra criteria beyond the checklist. Then give "
    "an overall holistic label."
)


def _score_from_points(earned: int, possible: int) -> float:
    """
    The single place score type/range is decided. Currently: float in
    [0.0, 1.0]. If Part B's update_mastery() turns out to expect a
    different type (e.g. int 0-100), this is the only function that
    needs to change.
    """
    if possible <= 0:
        return 0.0
    return max(0.0, min(1.0, earned / possible))


def evaluate_fundamentals(question: GeneratedQuestion, answer_text: str) -> EvaluationResult:
    raw = call_structured(
        system_prompt=FUNDAMENTALS_EVAL_PROMPT,
        user_prompt=(
            f"Question: {question.question_text}\n"
            f"Candidate's answer (transcribed from speech): {answer_text}"
        ),
        response_model=FundamentalsEvaluationRaw,
        schema_name="fundamentals_evaluation",
        thinking_enabled=False,
        prompt_cache_key="evaluator-fundamentals",
    )

    points_possible = 3
    points_earned = sum(
        [raw.concept_correct, raw.reasoning_sound, raw.no_major_misconception]
    )

    return EvaluationResult(
        score=_score_from_points(points_earned, points_possible),
        points_earned=points_earned,
        points_possible=points_possible,
        rationale=raw.rationale,
        detail=raw.model_dump(),
    )


def evaluate_open_ended(question: GeneratedQuestion, answer_text: str) -> EvaluationResult:
    if not question.checklist:
        raise ValueError(
            f"Question {question.question_id} has no stored checklist — "
            "cannot grade scenario/project mode without one. Check that "
            "generate_next_question() actually persisted it."
        )

    checklist_str = "\n".join(f"- {item}" for item in question.checklist)
    raw = call_structured(
        system_prompt=OPEN_ENDED_EVAL_PROMPT,
        user_prompt=(
            f"Question: {question.question_text}\n\n"
            f"Checklist:\n{checklist_str}\n\n"
            f"Candidate's answer (transcribed from speech): {answer_text}"
        ),
        response_model=OpenEndedEvaluationRaw,
        schema_name="open_ended_evaluation",
        thinking_enabled=False,
        prompt_cache_key=f"evaluator-{question.mode}",
    )

    points_possible = len(question.checklist)
    points_earned = sum(1 for c in raw.criteria if c.met)

    return EvaluationResult(
        score=_score_from_points(points_earned, points_possible),
        points_earned=points_earned,
        points_possible=points_possible,
        rationale=raw.rationale,
        detail=raw.model_dump(),
    )


def evaluate(question: GeneratedQuestion, answer_text: str) -> EvaluationResult:
    """Single entry point main.py calls — dispatches on question.mode."""
    if question.mode == "fundamentals":
        return evaluate_fundamentals(question, answer_text)
    return evaluate_open_ended(question, answer_text)
