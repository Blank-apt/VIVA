# Part A — Voice & Ingestion

## Setup

```bash
# system dependency (not pip) - needed for audio format conversion
# macOS:   brew install ffmpeg
# Ubuntu:  sudo apt install ffmpeg
# Windows: download from ffmpeg.org, add to PATH

python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

pip install -r requirements.txt
```

The first time you call `transcribe()` or `ingest_documents()`, the underlying
libraries will **download model weights from Hugging Face** (Whisper's
`small.en`, and `all-MiniLM-L6-v2` for embeddings) — this needs internet
access and happens once; after that they're cached locally
(`~/.cache/huggingface`). Don't leave this until the last hour of the
hackathon in case wifi at the venue is bad — run it once tonight so the
weights are already on disk.

## Try it yourself, in order

```bash
# 1. transcribe() - drop an audio file next to voice.py first
#    (record anything on your phone, or record via a browser MediaRecorder
#    demo page to get a realistic WebM file)
python voice.py

# 2. ingest + retrieve - drop your resume as test_resume.pdf next to ingest.py
python ingest.py

# 3. run both together
python test_harness.py
```

Each script tells you exactly what test file it's looking for and where, and
skips gracefully if it's missing rather than crashing.

## Files

| File | Exposes | Notes |
|---|---|---|
| `voice.py` | `transcribe(audio: bytes) -> str` | ffmpeg conversion is a separate internal function (`_convert_to_wav`) — test it in isolation first if transcription is failing, since format mismatches are the most common silent failure here |
| `ingest.py` | `ingest_documents(files: list) -> None`<br>`retrieve_project_context(query: str) -> list[str]` | Chunking splits **only on blank lines**, not every bullet — this keeps a project's bullets grouped with its heading, which matters for "why did you choose X" style retrieval |
| `test_harness.py` | — | End-to-end smoke test, run this before handing the module to whoever's building Part C |

## What's been verified vs. what you still need to check

I ran the real chunking/parsing/storage/retrieval logic in `ingest.py`
end-to-end against a `.docx` test file (with a stubbed embedder, since this
sandbox can't reach Hugging Face to download real model weights) — the
plumbing works and returns the right types. **What I have not been able to
verify from here**, because it needs real model weights and your own
hardware/mic:

- Whisper's actual transcription accuracy on your voice + your technical
  vocabulary (SAE, topk, reconstruction MSE) — test this yourself on day 1,
  it's the highest-risk unknown in this whole part.
- The ffmpeg conversion step against a **real browser-recorded** WebM clip,
  not a clean file you made yourself — this is where format bugs actually
  show up.
- Real semantic retrieval quality from `all-MiniLM-L6-v2` (the stub used
  fake hash-based vectors just to prove the pipeline runs, not real
  similarity) — this you can eyeball for yourself once you run it for real:
  ask a query like "why did you pick Qwen2.5-7B" and see if the right chunk
  comes back first.

## Known limitations (acceptable at hackathon scale, worth knowing about)

- `ingest_documents()` **overwrites** the existing chunk store rather than
  appending — call it once with your full file list, not once per file.
- The first chunk in a document sometimes absorbs the header/name block
  along with the first real section, since there's often no blank line
  between them in a compact resume layout. Harmless for retrieval at this
  scale, just don't be surprised by it.
- No retry/error handling around the Hugging Face model download — if it
  fails partway (bad wifi), delete `~/.cache/huggingface` and retry rather
  than debugging a partial cache.
