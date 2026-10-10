"""User-facing error types.

Every failure the user can plausibly hit is expressed as a
:class:`TubeScriptError` with a short message and an optional ``hint``.
:mod:`tubescript.app` catches this base class, renders the error nicely and
returns to the prompt instead of letting a traceback reach the terminal.
"""

from __future__ import annotations


class TubeScriptError(Exception):
    """Base class for expected, user-facing failures."""

    def __init__(self, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


class InvalidURLError(TubeScriptError):
    """The pasted string is not a usable YouTube video URL."""


class DownloadError(TubeScriptError):
    """The audio could not be downloaded (network, format, disk, ...)."""


class VideoUnavailableError(DownloadError):
    """The video exists but cannot be played or is private / removed."""


class FFmpegMissingError(TubeScriptError):
    """ffmpeg is required but was not found on the machine."""


class ModelNotFoundError(TubeScriptError):
    """The GGML model file is not present in ``models/``."""


class ModelLoadError(TubeScriptError):
    """The model file exists but whisper.cpp refused to load it."""


class TranscriptionError(TubeScriptError):
    """whisper.cpp failed while decoding the audio."""


class UnsupportedLanguageError(TubeScriptError):
    """The selected language is not known to the Whisper model."""


class SettingsError(TubeScriptError):
    """The settings file is unreadable or contains invalid values."""
