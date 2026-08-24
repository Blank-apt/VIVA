"""
Integration glue: makes the sibling `part_a` and `part_b` packages
importable from inside part_c, regardless of which directory uvicorn/
pytest is launched from.

part_a, part_b, and part_c are siblings under backend/. When you run
`uvicorn main:app` from inside part_c/, only part_c's own directory is
on sys.path by default — part_a and part_b (one level up) are not. This
module inserts the backend/ root onto sys.path so `from part_a import
...` / `from part_b import ...` resolve correctly.

Import this BEFORE importing anything from part_a/part_b — main.py and
interviewer.py both do `import _pathfix` as their first import for
exactly this reason.
"""
import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parent.parent  # backend/
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))
