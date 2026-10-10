"""The whisper.cpp transcription engine.

Wraps ``pywhispercpp`` and maps the user's :class:`~tubescript.config.Settings`
(thread count) onto the low-level knobs whisper.cpp understands. Audio is
decoded on the CPU, so no GPU or CUDA toolchain is required.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, Sequence

from . import languages
from .config import Settings
from .errors import (
    ModelLoadError,
    ModelNotFoundError,
    TranscriptionError,
    UnsupportedLanguageError,
)
from .paths import MODEL_URL, MODELS_DIR, model_path

#: A gap longer than this (in seconds) becomes a paragraph break.
PARAGRAPH_GAP = 1.1

#: ``pywhispercpp`` forwards whisper.cpp's ``whisper_full_get_segment_t0/t1``
#: verbatim, and whisper.cpp counts those in centiseconds (hundredths of a
#: second), not milliseconds. Dividing by 1000 makes every duration 10x too
#: small, which pins the progress bar at ~10% and widens the paragraph gap to
#: 11 seconds.
TIMESTAMP_SCALE = 0.01

#: Sentinel meaning "let the model work out the language itself". This is *not*
#: a value whisper.cpp understands: ``language="auto"`` makes
#: ``whisper_lang_id`` fail and the decode returns zero segments, so the
#: language has to be detected first and the real code passed in.
AUTO = languages.AUTO.code

ProgressHook = Callable[[float, str], None]


# --------------------------------------------------------------------------
# Transcript formatting
# --------------------------------------------------------------------------
def format_transcript(segments: Sequence[object]) -> str:
    """Turn raw whisper segments into readable plain text.

    Consecutive segments are glued together, and a silence longer than
    :data:`PARAGRAPH_GAP` starts a new paragraph.
    """
    paragraphs: list[str] = []
    current: list[str] = []
    previous_end = 0.0

    for segment in segments:
        text = (getattr(segment, "text", "") or "").strip()
        if not text:
            continue
        start = getattr(segment, "t0", 0) * TIMESTAMP_SCALE
        if current and start - previous_end > PARAGRAPH_GAP:
            paragraphs.append(" ".join(current))
            current = []
        current.append(text)
        previous_end = getattr(segment, "t1", 0) * TIMESTAMP_SCALE

    if current:
        paragraphs.append(" ".join(current))

    return "\n\n".join(paragraphs).strip()


# --------------------------------------------------------------------------
# Transcriber
# --------------------------------------------------------------------------
class Transcriber:
    """Loads the GGML model once and decodes audio files with it."""

    def __init__(self, settings: Settings, model_file: Path | None = None) -> None:
        self.settings = settings
        self.model_file = model_file or model_path()
        self._model = None
        self.load_seconds = 0.0
        #: Language the last :meth:`transcribe` call actually used, so callers
        #: can report what auto-detection picked.
        self.detected_language: str | None = None

    # -- loading -----------------------------------------------------------
    def _require_backend(self) -> None:
        try:
            import pywhispercpp  # noqa: F401
        except ImportError:
            raise ModelNotFoundError(
                "The transcription engine (pywhispercpp) is not installed.",
                "Run:  pip install -r requirements.txt",
            )

    def _require_model(self) -> None:
        if not self.model_file.is_file():
            raise ModelNotFoundError(
                f"Model file not found: {self.model_file.name}",
                f"Expected location:\n  {self.model_file}\n\n"
                f"Download it from:\n  {MODEL_URL}\n"
                f"and place it in:\n  {MODELS_DIR}",
            )

    def _build_model(self) -> object:
        from pywhispercpp.model import Model

        return Model(
            model=str(self.model_file),
            models_dir=str(MODELS_DIR),
            n_threads=self.settings.effective_threads,
            # Our own bar drives the progress display.
            print_progress=False,
            print_realtime=False,
            redirect_whispercpp_logs_to=None,
            context_params={"use_gpu": False},
        )

    def load(self) -> None:
        """Prepare the model for transcription."""
        self._require_backend()
        self._require_model()
        started = time.perf_counter()
        try:
            self._model = self._build_model()
        except Exception as exc:
            raise ModelLoadError(
                f"whisper.cpp could not load the model: {exc}",
                f"Check that {self.model_file.name} is a complete download.",
            ) from exc
        self.load_seconds = time.perf_counter() - started

    # -- language ----------------------------------------------------------
    def _detect(self, audio_file: Path) -> str:
        """Ask whisper.cpp which language the audio is in.

        ``auto_detect_language`` returns ``((code, probability), all_scores)``,
        so the winning code is nested one level deep.
        """
        result = self._model.auto_detect_language(str(audio_file))  # type: ignore[union-attr]
        if not isinstance(result, (tuple, list)) or not result:
            raise TranscriptionError(
                "Auto-detection returned an unexpected result.",
                "Pick a specific language instead of using auto-detect.",
            )
        best = result[0]
        if isinstance(best, (tuple, list)) and best:
            return str(best[0])
        return str(best)

    def _resolve_language(self, audio_file: Path, language: str) -> dict[str, object]:
        """Validate *language* and build the whisper.cpp decode params.

        For :data:`AUTO` the language is detected with whisper.cpp's dedicated
        ``auto_detect_language`` pass and the concrete code is then used for the
        real decode. Passing ``language="auto"`` straight through is not an
        option: whisper.cpp has no such language id, and the decode then returns
        zero segments without raising.
        """
        if language != AUTO:
            if not languages.is_supported(language):
                raise UnsupportedLanguageError(
                    f"Language '{language}' is not supported by the model.",
                    "Pick another language from the list.",
                )
            self.detected_language = language
            return {"language": language}

        if not hasattr(self._model, "auto_detect_language"):
            # Very old bindings: leaving the language unset lets whisper.cpp
            # detect it during the decode itself.
            self.detected_language = None
            return {}

        try:
            code = self._detect(audio_file)
        except TranscriptionError:
            raise
        except Exception as exc:
            raise TranscriptionError(
                f"Language detection failed: {exc}",
                "Pick a specific language instead of using auto-detect.",
            ) from exc

        if not code or not languages.is_supported(code):
            raise TranscriptionError(
                "Auto-detection did not return a usable language.",
                "Pick a specific language instead of using auto-detect.",
            )

        self.detected_language = code
        return {"language": code}

    # -- transcription -----------------------------------------------------
    def transcribe(
        self,
        audio_file: Path,
        language: str = AUTO,
        duration_seconds: float | None = None,
        on_progress: ProgressHook | None = None,
    ) -> str:
        """Transcribe *audio_file* and return the formatted text.

        The app always passes :data:`AUTO`; an explicit code is accepted and
        pinned as the source language, which is how the tests exercise the
        validation and error paths.
        """
        if self._model is None:
            raise TranscriptionError("The model has not been loaded yet.")

        params = self._resolve_language(audio_file, language)

        def on_segment(segment: object) -> None:
            if on_progress is None or not duration_seconds:
                return
            end = getattr(segment, "t1", 0) * TIMESTAMP_SCALE
            fraction = min(0.999, max(0.0, end / duration_seconds))
            on_progress(fraction, "")

        try:
            segments = self._model.transcribe(  # type: ignore[union-attr]
                str(audio_file),
                new_segment_callback=on_segment,
                **params,
            )
        except Exception as exc:
            raise TranscriptionError(
                f"Transcription failed: {exc}",
                "The audio file may be corrupt, or the model may be incompatible.",
            ) from exc

        text = format_transcript(segments)
        if not text.strip():
            detected = self.detected_language or "unknown"
            raise TranscriptionError(
                "The model returned an empty transcription.",
                f"Detected language: {detected}. Try another language, or check "
                "that the video actually contains speech.",
            )
        return text

    def describe_compute(self) -> str:
        """A short, human summary of the compute configuration in use."""
        return f"{self.settings.effective_threads} threads, CPU only"