"""
Part A — Voice & Ingestion, public package interface.

Re-exports the three functions other parts (Part C) import:
    transcribe(audio: bytes) -> str
    ingest_documents(files: list) -> None
    retrieve_project_context(query: str) -> list[str]

Importing this package eagerly imports voice.py and ingest.py, which in
turn import faster-whisper / sentence-transformers / pdfplumber /
python-docx. If those heavy dependencies aren't installed, this import
raises ModuleNotFoundError (a subclass of ImportError) — Part C's main.py
and interviewer.py already catch ImportError and fall back to stub
implementations, so a missing/partial Part A install degrades gracefully
instead of crashing the whole app.
"""

from .voice import transcribe
from .ingest import ingest_documents, retrieve_project_context

__all__ = ["transcribe", "ingest_documents", "retrieve_project_context"]
