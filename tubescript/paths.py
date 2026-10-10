"""Filesystem locations used by TubeScript CLI.

Every path is derived from the project root (the directory that contains
``main.py``) so the tool stays fully self-contained: moving or copying the
folder somewhere else keeps it working.
"""

from __future__ import annotations

from pathlib import Path

APP_DIR: Path = Path(__file__).resolve().parent.parent
MODELS_DIR: Path = APP_DIR / "models"
OUTPUT_DIR: Path = APP_DIR / "output"
TMP_DIR: Path = APP_DIR / "tmp"
CONFIG_PATH: Path = APP_DIR / "config.json"

#: Whisper model used for every transcription. Driven by the first-run picker
#: (see :mod:`tubescript.model_catalog`) and persisted in ``config.json``; the
#: constants below are re-derived by :func:`set_model`.
from .model_catalog import DEFAULT as _DEFAULT_MODEL

MODEL_NAME: str = _DEFAULT_MODEL
MODEL_FILENAME: str = f"{MODEL_NAME}.bin"

#: Official whisper.cpp mirror used for the automatic first-run download.
MODEL_URL: str = f"https://huggingface.co/ggerganov/whisper.cpp/resolve/main/{MODEL_NAME}.bin"


def set_model(name: str) -> None:
    """Switch the active Whisper model (a catalogue stem such as ``ggml-tiny``)."""
    global MODEL_NAME, MODEL_FILENAME, MODEL_URL
    MODEL_NAME = name
    MODEL_FILENAME = f"{name}.bin"
    MODEL_URL = f"https://huggingface.co/ggerganov/whisper.cpp/resolve/main/{name}.bin"


def model_path() -> Path:
    """Return the expected local path of the GGML model file."""
    return MODELS_DIR / MODEL_FILENAME


def ensure_dirs() -> None:
    """Create the writable project directories if they do not exist yet."""
    for directory in (MODELS_DIR, OUTPUT_DIR, TMP_DIR):
        directory.mkdir(parents=True, exist_ok=True)
