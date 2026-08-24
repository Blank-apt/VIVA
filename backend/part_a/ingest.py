"""
Part A - Voice & Ingestion: Document ingestion + retrieval
=============================================================
ingest_documents(files: list) -> None
retrieve_project_context(query: str) -> list[str]

Small local RAG pipeline for "your projects" mode: parse resume/project
docs -> chunk -> embed locally -> store -> retrieve top-k relevant chunks
for a given interview question.

Deliberately no vector DB (FAISS/Chroma) and no API-based embeddings:
Part C owns the Kimi API budget for LLM calls, not embeddings. At
resume-sized corpora (20-50 chunks) brute-force numpy cosine similarity
is instant, so a real vector DB would just be setup overhead with no
performance benefit at this scale.
"""

import re
import pickle
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer

import pdfplumber
import docx  # this is the python-docx package, imported as `docx`

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_EMBED_MODEL_NAME = "all-MiniLM-L6-v2"   # small, fast, local, good enough at this scale
_STORE_PATH = Path(__file__).parent / "chunk_store.pkl"

_embedder = None


def _get_embedder() -> SentenceTransformer:
    global _embedder
    if _embedder is None:
        print(f"[ingest] loading embedding model '{_EMBED_MODEL_NAME}'...")
        _embedder = SentenceTransformer(_EMBED_MODEL_NAME)
    return _embedder


# ---------------------------------------------------------------------------
# Parsing - turn a file into raw text
# ---------------------------------------------------------------------------

def _extract_text_from_pdf(path: str) -> str:
    """
    Uses word-level bounding boxes rather than pdfplumber's default
    extract_text(), which was found to silently merge adjacent words with no
    space between them on some PDFs (LaTeX-generated ones in particular -
    e.g. "Engineered" + "a" + "Top-K" came out as "EngineeredaTop-K...").
    Grouping words by line position and joining with explicit spaces avoids
    that failure mode.
    """
    text_parts = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            words = page.extract_words(x_tolerance=1, keep_blank_chars=False)
            if not words:
                text_parts.append(page.extract_text() or "")
                continue

            # Group words into lines by vertical position ("top"), then sort
            # each line left-to-right by x-position before joining.
            lines_by_y = {}
            for w in words:
                line_key = round(w["top"])
                lines_by_y.setdefault(line_key, []).append(w)

            page_lines = []
            for key in sorted(lines_by_y.keys()):
                line_words = sorted(lines_by_y[key], key=lambda w: w["x0"])
                page_lines.append(" ".join(w["text"] for w in line_words))

            text_parts.append("\n".join(page_lines))
    return "\n".join(text_parts)


def _extract_text_from_docx(path: str) -> str:
    d = docx.Document(path)
    return "\n".join(p.text for p in d.paragraphs)


def _extract_text_from_txt(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


def _extract_text(path: str) -> str:
    ext = Path(path).suffix.lower()
    if ext == ".pdf":
        return _extract_text_from_pdf(path)
    elif ext == ".docx":
        return _extract_text_from_docx(path)
    elif ext in (".txt", ".md"):
        return _extract_text_from_txt(path)
    else:
        raise ValueError(f"Unsupported file type: {ext} (supported: .pdf, .docx, .txt, .md)")


# ---------------------------------------------------------------------------
# Chunking - resumes/project docs are structured, not prose. Primary
# strategy: split on blank lines, so bullets stay grouped with their parent
# project heading (splitting on every bullet fragments a project's reasoning
# away from its description, hurting retrieval for "why did you choose X"
# questions).
#
# FALLBACK: PDF extraction (pdfplumber) frequently produces text with NO
# literal blank lines between sections at all - PDFs are laid out visually,
# not with double-newlines - which was confirmed against a real resume PDF
# where blank-line splitting returned exactly 1 chunk for the whole
# document. When that happens, fall back to grouping consecutive lines up
# to a target size. Less semantically precise than a real section split,
# but far better than one undifferentiated chunk for the whole document.
# ---------------------------------------------------------------------------

def _chunk_text(text: str, target_chunk_chars: int = 500, min_chunk_len: int = 60) -> list:
    raw_parts = re.split(r"\n\s*\n+", text)
    chunks = [p.strip() for p in raw_parts if p.strip()]

    if len(chunks) <= 1 and len(text) > target_chunk_chars:
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        chunks = []
        buffer_lines = []
        buffer_len = 0
        for line in lines:
            buffer_lines.append(line)
            buffer_len += len(line) + 1
            if buffer_len >= target_chunk_chars:
                chunks.append("\n".join(buffer_lines))
                buffer_lines = []
                buffer_len = 0
        if buffer_lines:
            chunks.append("\n".join(buffer_lines))

    # Merge chunks shorter than min_chunk_len into their neighbor so we don't
    # end up with a chunk that's just a lone section header like "SKILLS".
    merged = []
    buffer = ""
    for c in chunks:
        buffer = f"{buffer}\n\n{c}".strip() if buffer else c
        if len(buffer) >= min_chunk_len:
            merged.append(buffer)
            buffer = ""
    if buffer:
        if merged:
            merged[-1] += "\n\n" + buffer
        else:
            merged.append(buffer)

    return merged


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def ingest_documents(files: list) -> None:
    """
    Parse, chunk, embed, and store a list of document file paths.

    Args:
        files: list of file paths (str) to resume/project docs
               (.pdf, .docx, .txt, .md)

    Returns:
        None. Chunks + embeddings are persisted to disk (chunk_store.pkl)
        for retrieve_project_context() to load. NOTE: this OVERWRITES the
        existing store, it doesn't append - call it once with the full
        file list, not once per file.
    """
    all_chunks = []
    for filepath in files:
        print(f"[ingest] parsing {filepath}...")
        text = _extract_text(filepath)
        chunks = _chunk_text(text)
        all_chunks.extend(chunks)

    if not all_chunks:
        print("[ingest] no chunks produced - check your input files.")
        return

    embedder = _get_embedder()
    print(f"[ingest] embedding {len(all_chunks)} chunks...")
    embeddings = embedder.encode(all_chunks, normalize_embeddings=True)

    with open(_STORE_PATH, "wb") as f:
        pickle.dump({"chunks": all_chunks, "embeddings": embeddings}, f)

    print(f"[ingest] stored {len(all_chunks)} chunks to {_STORE_PATH}")


def retrieve_project_context(query: str, k: int = 3) -> list:
    """
    Return the top-k most relevant chunks for a given interview question.

    Args:
        query: the question being asked (e.g. "why LightGBM over XGBoost?")
        k: how many chunks to return

    Returns:
        list[str] of chunk text, most relevant first.
    """
    if not _STORE_PATH.exists():
        raise RuntimeError("No documents ingested yet - call ingest_documents() first.")

    with open(_STORE_PATH, "rb") as f:
        store = pickle.load(f)

    chunks = store["chunks"]
    chunk_embeddings = store["embeddings"]  # already normalized at ingest time

    embedder = _get_embedder()
    query_vec = embedder.encode([query], normalize_embeddings=True)[0]

    # Both sides are normalized, so a plain dot product IS cosine similarity -
    # no need for a separate cosine-sim function.
    scores = chunk_embeddings @ query_vec
    top_k_idx = np.argsort(scores)[::-1][:k]

    return [chunks[i] for i in top_k_idx]


if __name__ == "__main__":
    # Manual smoke test: drop your resume as test_resume.pdf next to this
    # script and run `python ingest.py`.
    test_file = Path(__file__).parent / "test_resume.pdf"
    if test_file.exists():
        ingest_documents([str(test_file)])
        results = retrieve_project_context("why did you use a TopK sparse autoencoder?")
        print("\nTop matches:")
        for r in results:
            print("-", r[:200].replace("\n", " "), "...\n")
    else:
        print(f"No test file found at {test_file} - drop your resume there and rerun.")
