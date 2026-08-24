"""
Centralized constants for Part B — Data & Scoring.

Per spec section 13: the allowed modes list must live in exactly one place.
Other modules import from here rather than redefining the list.
"""

# The three supported interview modes.
ALLOWED_MODES = frozenset({"fundamentals", "scenario", "your-projects"})

# Difficulty buckets, matching session_qa.difficulty CHECK constraint.
DIFFICULTY_FOUNDATIONAL = "foundational"
DIFFICULTY_MEDIUM = "medium"
DIFFICULTY_EDGE_CASES = "edge_cases"

# EMA weights (spec section 20): new = 0.7 * old + 0.3 * current
EMA_OLD_WEIGHT = 0.7
EMA_NEW_WEIGHT = 0.3

# Default mastery for a topic/mode that has never been scored (spec section 22).
DEFAULT_MASTERY = 0.5

# Difficulty thresholds (spec section 21).
DIFFICULTY_LOW_THRESHOLD = 0.4   # score < 0.4  -> foundational
DIFFICULTY_HIGH_THRESHOLD = 0.7  # score > 0.7  -> edge_cases
                                  # 0.4 <= score <= 0.7 -> medium


def validate_mode(mode: str) -> None:
    """Raise ValueError if `mode` is not one of the allowed modes."""
    if mode not in ALLOWED_MODES:
        raise ValueError(
            f"Invalid mode: {mode!r}. Allowed modes: {sorted(ALLOWED_MODES)}"
        )


def validate_score(score: float) -> None:
    """Raise ValueError if `score` is not in the valid [0.0, 1.0] range."""
    if not isinstance(score, (int, float)) or isinstance(score, bool):
        raise ValueError(f"Score must be numeric, got {type(score).__name__}")
    if not (0.0 <= score <= 1.0):
        raise ValueError(f"Score must be between 0.0 and 1.0, got {score}")
