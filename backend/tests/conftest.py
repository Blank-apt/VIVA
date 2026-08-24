"""
part_c/main.py (and its sibling modules) use bare imports like
`from evaluator import evaluate`, which only resolve when part_c/ itself
is on sys.path — true when you `cd part_c && uvicorn main:app`, not true
by default when pytest collects tests from backend/tests/.

This conftest adds part_c/ to sys.path so the integration tests can
`import main` the same way uvicorn would load it.
"""
import sys
from pathlib import Path

_PART_C = Path(__file__).resolve().parent.parent / "part_c"
if str(_PART_C) not in sys.path:
    sys.path.insert(0, str(_PART_C))
