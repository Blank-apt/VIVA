"""
Pydantic models for Part C: Agent Orchestration.

Two layers here:
  1. The RAW structured-output schemas Kimi is asked to fill in. These are
     deliberately COARSE (booleans / checklist met-or-not / 3-way labels),
     never a raw numeric score — LLM judges are unreliable at fine-grained
     numeric scoring, so the model only produces categorical judgments.
  2. The API-facing models used by main.py's routes, including
     EvaluationResult.score, which IS the numeric float that gets computed
     deterministically (in evaluator.py) from the raw judgment above, and
     is what should be passed to Part B's update_mastery(topic, mode, score).

ASSUMPTION (flagged, not confirmed with Part B): score is a float in
[0.0, 1.0]. If your teammate's update_mastery() expects something else
(e.g. int 0-100), change _score_from_points() in evaluator.py — nothing
else needs to change, that's the only place score type is decided.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

Mode = Literal["fundamentals", "scenario", "project"]


# ---------------------------------------------------------------------------
# Kimi structured-output schemas (raw judgments from the LLM)
# ---------------------------------------------------------------------------

class GeneratedQuestionRaw(BaseModel):
    """What Kimi returns when asked to author a question."""

    question_text: str
    checklist: list[str] = Field(
        default_factory=list,
        description=(
            "Empty for fundamentals mode. 3-6 atomic, independently "
            "checkable criteria a strong answer should hit, for "
            "scenario/project mode."
        ),
    )


class FundamentalsEvaluationRaw(BaseModel):
    """Kimi's raw judgment for a fundamentals-mode answer."""

    concept_correct: bool
    reasoning_sound: bool
    no_major_misconception: bool
    missed_concepts: list[str] = Field(default_factory=list)
    rationale: str


class ChecklistJudgment(BaseModel):
    item: str
    met: bool


class OpenEndedEvaluationRaw(BaseModel):
    """Kimi's raw judgment for scenario/project-mode answers."""

    criteria: list[ChecklistJudgment]
    overall: Literal["strong", "adequate", "weak"]
    rationale: str


# ---------------------------------------------------------------------------
# API-facing / internal models
# ---------------------------------------------------------------------------

class GeneratedQuestion(BaseModel):
    question_id: str
    mode: Mode
    topic: str
    difficulty: Optional[str] = None
    question_text: str
    checklist: list[str] = Field(default_factory=list)


class EvaluationResult(BaseModel):
    score: float  # normalized [0.0, 1.0] -> feed to Part B's update_mastery()
    points_earned: int
    points_possible: int
    rationale: str
    detail: dict  # raw per-mode judgment, kept for logging/debugging


class NextQuestionRequest(BaseModel):
    session_id: str
    mode: Mode
    # If omitted, Part C asks Part B for the weakest topic in this mode.
    topic: Optional[str] = None


class SubmitAnswerRequest(BaseModel):
    session_id: str
    question_id: str
    audio_base64: str  # base64-encoded audio; decoded to bytes before transcribe()


class SubmitAnswerResponse(BaseModel):
    transcript: str
    evaluation: EvaluationResult
    next_difficulty: Optional[str] = None
