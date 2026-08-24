"""
End-to-end smoke test for Part A functions.

Run this after you've got voice.py and ingest.py working individually,
to confirm everything still behaves before handing the module off to
whoever's building Part C - they'll be calling these functions blind,
trusting the signatures and return types.

Usage:
    python test_harness.py

Each test SKIPS (doesn't fail) if its test fixture file is missing, so
you can run this early and fill in fixtures as you get them.
"""

from pathlib import Path
from voice import transcribe
from ingest import ingest_documents, retrieve_project_context

HERE = Path(__file__).parent


def test_transcribe():
    print("\n=== Testing transcribe() ===")
    audio_path = HERE / "test_audio.webm"
    if not audio_path.exists():
        audio_path = HERE / "test_audio.wav"
    if not audio_path.exists():
        print("SKIPPED - no test_audio.webm/.wav found")
        return

    with open(audio_path, "rb") as f:
        audio_bytes = f.read()

    text = transcribe(audio_bytes)
    print("Transcript:", text)

    assert isinstance(text, str), "transcribe() must return a str"
    assert len(text) > 0, "transcribe() returned an empty string - check audio/ffmpeg conversion"
    print("PASSED")


def test_ingest_and_retrieve():
    print("\n=== Testing ingest_documents() + retrieve_project_context() ===")
    resume_path = HERE / "test_resume.pdf"
    if not resume_path.exists():
        print("SKIPPED - no test_resume.pdf found")
        return

    ingest_documents([str(resume_path)])
    results = retrieve_project_context("sparse autoencoder Qwen")

    print(f"Retrieved {len(results)} chunks:")
    for r in results:
        print("-", r[:150].replace("\n", " "), "...")

    assert isinstance(results, list), "retrieve_project_context() must return a list"
    assert all(isinstance(r, str) for r in results), "every item must be a str"
    print("PASSED")


if __name__ == "__main__":
    test_transcribe()
    test_ingest_and_retrieve()
    print("\nDone. Fill in missing fixture files (test_audio.webm, test_resume.pdf) to unskip tests.")
