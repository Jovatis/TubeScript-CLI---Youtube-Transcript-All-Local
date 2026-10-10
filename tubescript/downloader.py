"""YouTube audio retrieval via yt-dlp.

Downloads the audio track only, converts it to the 16 kHz mono WAV that
Whisper expects, and hands back both the temporary file and the video metadata
(title, duration, ...).
"""

from __future__ import annotations

import re
import shutil
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from . import cleanup as _cleanup
from .errors import (
    DownloadError,
    FFmpegMissingError,
    InvalidURLError,
    VideoUnavailableError,
)
from .paths import TMP_DIR

#: Hosts that can legitimately carry a YouTube video id.
_YOUTUBE_HOSTS = {
    "youtube.com", "www.youtube.com", "m.youtube.com",
    "music.youtube.com", "gaming.youtube.com", "youtube-nocookie.com",
    "www.youtube-nocookie.com", "youtu.be", "www.youtu.be",
}

_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")

ProgressHook = Callable[[float, str], None]

#: yt-dlp message fragments that mean "this video is not watchable".
_UNAVAILABLE_MARKERS = (
    "private video", "video unavailable", "removed by the uploader",
    "account associated with this video has been terminated",
    "this video has been removed", "members-only", "join this channel",
    "video is not available", "copyright", "who has blocked it on copyright",
    "sign in to confirm your age", "confirm you are not a bot",
    "requested format is not available",
)


@dataclass
class MediaInfo:
    """What yt-dlp managed to extract for a video."""

    audio_file: Path
    title: str
    duration: float | None
    video_id: str

    @property
    def display_title(self) -> str:
        return self.title or f"YouTube video {self.video_id}"


# --------------------------------------------------------------------------
# URL handling
# --------------------------------------------------------------------------
def extract_video_id(url: str) -> str:
    """Return the 11-character video id contained in *url*.

    Raises :class:`InvalidURLError` for anything that is not a YouTube video
    link, so the user gets a precise message instead of a yt-dlp stack trace.
    """
    candidate = (url or "").strip()
    if not candidate:
        raise InvalidURLError(
            "No URL was provided.",
            "Paste a YouTube link, for example https://www.youtube.com/watch?v=...",
        )

    # A bare 11-character id is what people paste when they grab it from the
    # URL bar's tail, so accept it directly.
    if _VIDEO_ID_RE.fullmatch(candidate):
        return candidate

    if "://" not in candidate:
        candidate = "https://" + candidate

    try:
        parsed = urlparse(candidate)
    except ValueError as exc:
        raise InvalidURLError(f"This does not look like a valid URL: {url}") from exc

    host = (parsed.hostname or "").lower()
    if host not in _YOUTUBE_HOSTS:
        raise InvalidURLError(
            f"'{host or url}' is not a YouTube address.",
            "Supported: youtube.com/watch?v=..., youtu.be/..., youtube.com/shorts/...",
        )

    path = parsed.path or ""
    if host.endswith("youtu.be"):
        candidate_id = path.strip("/").split("/")[0]
    elif path.startswith(("/shorts/", "/embed/", "/live/", "/v/")):
        candidate_id = path.split("/")[2] if len(path.split("/")) > 2 else ""
    else:
        candidate_id = parse_qs(parsed.query).get("v", [""])[0]

    if not _VIDEO_ID_RE.match(candidate_id or ""):
        raise InvalidURLError(
            "No YouTube video id found in that link.",
            "Check the link looks like https://www.youtube.com/watch?v=XXXXXXXXXXX",
        )
    return candidate_id


def normalise_url(url: str) -> str:
    """Rebuild a canonical watch URL from a pasted link."""
    return f"https://www.youtube.com/watch?v={extract_video_id(url)}"


def safe_filename(title: str, fallback: str = "transcription") -> str:
    """Turn a video title into a Windows-safe filename stem."""
    cleaned = unicodedata.normalize("NFKC", title or "")
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    if not cleaned:
        return fallback
    # Leave room for the ".txt" suffix and for Windows' 260-char limit.
    return cleaned[:150].rstrip(" .")


# --------------------------------------------------------------------------
# Download
# --------------------------------------------------------------------------
def _require_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None:
        raise FFmpegMissingError(
            "ffmpeg was not found on this machine.",
            "Whisper needs 16 kHz mono audio.\n"
            "  winget install Gyan.FFmpeg\n"
            "then reopen TubeScript.",
        )


def download_audio(
    url: str,
    *,
    on_progress: ProgressHook | None = None,
) -> MediaInfo:
    """Download and convert the audio track of *url*.

    *on_progress* receives ``(fraction, detail)``; the fraction may be 0.0 when
    the total size is unknown.
    """
    try:
        import yt_dlp
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise DownloadError(
            "yt-dlp is not installed.",
            "Run:  pip install -r requirements.txt",
        ) from exc

    _require_ffmpeg()
    canonical = normalise_url(url)
    TMP_DIR.mkdir(parents=True, exist_ok=True)

    def hook(status: dict[str, Any]) -> None:
        if on_progress is None:
            return
        state = status.get("status")
        if state == "downloading":
            total = status.get("total_bytes") or status.get("total_bytes_estimate") or 0
            done = status.get("downloaded_bytes") or 0
            fraction = (done / total) if total else 0.0
            speed = status.get("speed") or 0
            detail = f"{_bytes(speed)}/s" if speed else ""
            on_progress(fraction, detail)
        elif state == "finished":
            on_progress(1.0, "")

    options: dict[str, Any] = {
        "format": "bestaudio/best",
        "outtmpl": str(TMP_DIR / "%(id)s.%(ext)s"),
        "progress_hooks": [hook],
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "consoletitle": False,
        "retries": 3,
        "fragment_retries": 3,
        "ignoreerrors": False,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "wav",
                "preferredquality": "0",
            }
        ],
        "postprocessor_args": ["-ac", "1", "-ar", "16000"],
    }

    try:
        with yt_dlp.YoutubeDL(options) as downloader:
            info = downloader.extract_info(canonical, download=True)
    except yt_dlp.utils.DownloadError as exc:
        raise _translate(exc) from exc
    except Exception as exc:  # network stack failures, TLS, DNS, ...
        raise DownloadError(f"Could not reach YouTube: {exc}") from exc

    if not info:
        raise DownloadError("yt-dlp returned no information for that video.")

    video_id = str(info.get("id") or extract_video_id(canonical))
    audio_file = _locate_audio(video_id)

    duration = info.get("duration")
    return MediaInfo(
        audio_file=audio_file,
        title=str(info.get("title") or "").strip(),
        duration=float(duration) if isinstance(duration, (int, float)) else None,
        video_id=video_id,
    )


def _locate_audio(video_id: str) -> Path:
    """Find the converted WAV among the files yt-dlp left behind."""
    candidates = sorted(TMP_DIR.glob(f"{video_id}.*"))
    wav = [p for p in candidates if p.suffix.lower() == ".wav"]
    if wav:
        return wav[0]
    if candidates:
        raise DownloadError(
            "The audio was downloaded but could not be converted to WAV.",
            "Check that ffmpeg works:  ffmpeg -version",
        )
    raise DownloadError(
        "The audio file disappeared right after the download.",
        "This is usually an antivirus or permissions issue in the tmp folder.",
    )


def _bytes(count: float) -> str:
    for unit in ("B", "KB", "MB"):
        if count < 1024 or unit == "MB":
            return f"{count:.0f} {unit}" if unit == "B" else f"{count:.1f} {unit}"
        count /= 1024
    return f"{count:.1f} MB"


def _translate(exc: Exception) -> DownloadError:
    """Turn a yt-dlp exception into a message a human can act on."""
    message = str(exc)
    lowered = message.lower()
    for marker in _UNAVAILABLE_MARKERS:
        if marker in lowered:
            return VideoUnavailableError(
                "This video is not available for download.",
                "It may be private, age-restricted, region-locked or removed.\n"
                "If it is age-restricted, sign in to YouTube in your browser first.",
            )
    if "requested format is not available" in lowered:
        return DownloadError(
            "YouTube offered no downloadable audio format for this video.",
            "Try again later, or pick a different video.",
        )
    return DownloadError("Download failed.", message)


# Re-exported so callers only need one module for temp-file handling.
cleanup = _cleanup.cleanup
sweep = _cleanup.sweep
