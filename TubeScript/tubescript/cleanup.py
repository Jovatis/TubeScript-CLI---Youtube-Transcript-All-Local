"""Cleanup helpers for the ``tmp`` folder.

Leftover audio can survive a crash or a forced close. The helpers here remove
those stale files without ever touching the transcripts in ``output/`` or the
model in ``models/``.
"""

from __future__ import annotations

import time
from pathlib import Path

from .paths import TMP_DIR

#: Extensions yt-dlp and ffmpeg can leave behind in the temp folder.
TEMP_SUFFIXES = frozenset(
    {".wav", ".webm", ".m4a", ".mp3", ".opus", ".ogg", ".aac", ".flac", ".part", ".ytdl", ".temp"}
)


def _is_temp_media(path: Path) -> bool:
    """Only ever remove files the audio pipeline could have produced."""
    return path.suffix.lower() in TEMP_SUFFIXES


def cleanup(file: Path) -> list[str]:
    """Delete a temporary file plus any sibling leftovers.

    Returns a list of human-readable problems instead of raising, so the
    transcript can still be reported as a success.
    """
    problems: list[str] = []
    for path in [file, *file.parent.glob(f"{file.stem}.*")]:
        if not path.exists():
            continue
        try:
            path.unlink()
        except OSError as exc:
            problems.append(f"{path.name}: {exc.strerror or exc}")
    return problems


def sweep(older_than_seconds: float | None = None) -> list[Path]:
    """Remove media files left in ``tmp/`` by a previous run.

    *older_than_seconds* skips anything younger than that, which keeps a
    concurrently running instance safe. Returns the list of removed paths;
    files that cannot be deleted are skipped rather than raising.
    """
    if not TMP_DIR.is_dir():
        return []

    removed: list[Path] = []
    for path in sorted(TMP_DIR.iterdir()):
        if not path.is_file() or not _is_temp_media(path):
            continue
        if older_than_seconds is not None:
            try:
                if time.time() - path.stat().st_mtime < older_than_seconds:
                    continue
            except OSError:
                continue
        try:
            path.unlink()
        except OSError:
            continue
        removed.append(path)
    return removed
