"""
Part A - Voice & Ingestion: Speech-to-text
============================================
transcribe(audio: bytes) -> str

Converts raw audio bytes (any format the browser gives us - typically
WebM/Opus from MediaRecorder) into a transcript string using faster-whisper.

Pipeline:
    raw audio bytes -> temp file -> ffmpeg convert to 16kHz mono WAV -> Whisper -> text

Requires ffmpeg installed on the system (not a pip package):
    macOS:   brew install ffmpeg
    Ubuntu:  sudo apt install ffmpeg
    Windows: download from ffmpeg.org and add to PATH
"""

import subprocess
import tempfile
import os
from pathlib import Path

from faster_whisper import WhisperModel

# Load the model once at import time is wasteful if this module is imported
# but never used, so we lazy-load on first call instead. "small.en" is the
# starting point: balances latency against jargon accuracy for a live demo.
# Bump to "medium.en" ONLY if small mangles your technical vocabulary
# (test with words like "sparse autoencoder", "topk", "reconstruction MSE").
_MODEL_SIZE = "small.en"

# Auto-detect GPU rather than hardcoding CPU. faster-whisper itself doesn't
# need torch, but if it happens to be installed (transitively via
# sentence-transformers in ingest.py, or on any Colab/Kaggle GPU notebook)
# we use it to check for CUDA, and fall back to CPU cleanly if not.
try:
    import torch
    _HAS_CUDA = torch.cuda.is_available()
except ImportError:
    _HAS_CUDA = False

_DEVICE = "cuda" if _HAS_CUDA else "cpu"
_COMPUTE_TYPE = "float16" if _HAS_CUDA else "int8"  # float16 needs a GPU; int8 is the CPU-friendly choice

_model = None


def _get_model() -> WhisperModel:
    """Lazy-load the model so importing this file doesn't eat RAM/time upfront."""
    global _model
    if _model is None:
        print(f"[voice] loading faster-whisper model '{_MODEL_SIZE}' ({_DEVICE}/{_COMPUTE_TYPE})...")
        _model = WhisperModel(_MODEL_SIZE, device=_DEVICE, compute_type=_COMPUTE_TYPE)
    return _model


def _convert_to_wav(input_path: str, output_path: str) -> None:
    """
    Browsers send WebM/Opus via the MediaRecorder API, not WAV. Whisper wants
    16kHz mono WAV. ffmpeg does the conversion.

    This is isolated as its own function deliberately - format mismatches
    between browser audio and Whisper's expected input are the #1 silent
    failure point in these pipelines. Test THIS function on its own with a
    real browser-recorded clip before trusting the full pipeline.
    """
    cmd = [
        "ffmpeg", "-y",              # -y = overwrite output without prompting
        "-i", input_path,
        "-ar", "16000",              # 16kHz sample rate, what Whisper expects
        "-ac", "1",                  # mono
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg conversion failed:\n{result.stderr}")


def transcribe(audio: bytes) -> str:
    """
    Convert raw audio bytes into a transcript string.

    Args:
        audio: raw audio bytes, any ffmpeg-readable format (webm, wav, mp3, etc.)
               ffmpeg reads the container format from the file header, so the
               caller doesn't need to tell us what format it is.

    Returns:
        Transcribed text as a single string.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        input_path = os.path.join(tmpdir, "input.bin")
        wav_path = os.path.join(tmpdir, "converted.wav")

        with open(input_path, "wb") as f:
            f.write(audio)

        _convert_to_wav(input_path, wav_path)

        model = _get_model()
        segments, info = model.transcribe(wav_path, beam_size=5)

        text = " ".join(segment.text.strip() for segment in segments)
        return text.strip()


if __name__ == "__main__":
    import time

    # Manual smoke test: drop an audio file named test_audio.webm (or .wav)
    # next to this script and run `python voice.py`.
    test_file = Path(__file__).parent / "test_audio.webm"
    if not test_file.exists():
        test_file = Path(__file__).parent / "test_audio.wav"

    if test_file.exists():
        with open(test_file, "rb") as f:
            audio_bytes = f.read()

        start = time.time()
        text = transcribe(audio_bytes)
        elapsed = time.time() - start

        print("Transcript:", text)
        print(f"Took {elapsed:.2f}s on {_DEVICE}")
    else:
        print(
            f"No test file found. Drop an audio file named "
            f"'test_audio.webm' or 'test_audio.wav' in {Path(__file__).parent} and rerun."
        )
