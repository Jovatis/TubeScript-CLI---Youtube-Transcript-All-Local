"""Minimal HTTP downloads with resume support and integrity checks.

Only the standard library is used, so the app keeps a single installed
dependency for transcription. A download streams into a ``.part`` file next to
its destination and is only renamed into place once the byte count matches the
server's ``Content-Length`` - a dropped connection therefore leaves a partial
file that the next call resumes from instead of starting over.

Security posture: model downloads are **only** allowed onto ``.bin`` files, and
when a pinned size or SHA-256 is supplied the finished file is verified against
it before it is moved into place. A payload that is not a model (an HTML error
page, a tampered or truncated binary, ...) is discarded on the spot, so a
corrupt model can never end up in ``models/``.
"""

from __future__ import annotations

import hashlib
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

#: Progress reporting callback: ``(fraction 0..1, short detail)``.
ProgressHook = Callable[[float, str], None]

_CHUNK = 1024 * 1024  # 1 MiB
_MB = 1024 * 1024

#: Headers that real GGML models never start with - clear signs of a text or
#: container payload that was served as the model (HTML error page, PDF, zip).
_TEXT_MARKS = (b"<", b"{", b"[", b'"', b"PK\x03\x04", b"%PDF", b"MZ")


class ChecksumError(OSError):
    """The download did not match the pinned size or SHA-256 (or was not a binary)."""


def hexdigest(path: Path) -> str:
    """SHA-256 of *path*, streamed in 1 MiB chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def validate_model(path: Path) -> str:
    """Return ``""`` when *path* looks like a GGML binary, else the reason it is not."""
    try:
        head = path.read_bytes()[:512]
    except OSError as exc:
        return str(exc)
    if not head:
        return "empty file"
    for mark in _TEXT_MARKS:
        if head.startswith(mark):
            return "not a GGML binary (text/HTML payload)"
    return ""


def _total(response: object) -> int:
    """Total size of the resource, read from Content-Range then Content-Length."""
    headers = response.headers  # type: ignore[attr-defined]
    content_range = headers.get("Content-Range") or ""
    if "/" in content_range:  # e.g. "bytes 1234-5678/102400"
        try:
            return int(content_range.rsplit("/", 1)[1])
        except ValueError:
            pass
    try:
        return int(headers.get("Content-Length") or 0)
    except (TypeError, ValueError):
        return 0


def _finish(
    part: Path,
    destination: Path,
    expected_size: int | None,
    expected_sha256: str | None,
) -> int:
    """Verify a completed ``.part``, then move it into place. Returns the size."""
    size = part.stat().st_size
    if expected_size is not None and size != expected_size:
        part.unlink(missing_ok=True)
        raise ChecksumError(f"size mismatch: expected {expected_size} bytes, got {size}")
    if expected_sha256 is not None:
        digest = hexdigest(part)
        if digest != expected_sha256:
            part.unlink(missing_ok=True)  # corrupt or tampered: never keep it
            raise ChecksumError("SHA-256 mismatch - the download is corrupted or tampered")
    reason = validate_model(part)
    if reason:
        part.unlink(missing_ok=True)
        raise ChecksumError(f"invalid model payload: {reason}")
    os.replace(part, destination)
    return size


def download(
    url: str,
    destination: Path,
    *,
    on_progress: ProgressHook | None = None,
    expected_size: int | None = None,
    expected_sha256: str | None = None,
) -> int:
    """Download *url* to a ``.bin`` *destination*, resuming interrupted downloads.

    The bytes stream directly to disk in one-megabyte chunks. A fresh request
    starts over if the server ignores the ``Range`` header (no re-hosted / 200
    answer), otherwise a pre-existing ``.part`` file is appended to. Once the
    download matches the expected size the partial file is verified (size, then
    SHA-256 when pinned, then a binary payload check) and moved into place, so
    ``pathlib.Path.is_file()`` only ever sees a complete, intact model.
    Returns the final size in bytes.
    """
    if destination.suffix.lower() != ".bin":
        raise ValueError(
            f"model downloads are only allowed as .bin files, got {destination.name}"
        )
    part = destination.with_name(destination.name + ".part")
    part.parent.mkdir(parents=True, exist_ok=True)

    request = urllib.request.Request(url, headers={"User-Agent": "TubeScript/1.0"})
    if part.exists():
        request.add_header("Range", f"bytes={part.stat().st_size}-")

    try:
        response = urllib.request.urlopen(request, timeout=300)
    except urllib.error.HTTPError as exc:
        if exc.code == 416:  # range not satisfiable: the .part is already the whole file
            return _finish(part, destination, expected_size, expected_sha256)
        raise

    total = _total(response)
    with response:
        if response.status == 206:  # partial content: append to the existing .part
            resume_from = part.stat().st_size
            if total and resume_from >= total:  # already complete, nothing to fetch
                return _finish(part, destination, expected_size, expected_sha256)
        else:  # a fresh 200: start over, ignoring any stale .part
            resume_from = 0

        seen = resume_from
        with part.open("ab" if resume_from else "wb") as out:
            while True:
                chunk = response.read(_CHUNK)
                if not chunk:
                    break
                out.write(chunk)
                seen += len(chunk)
                if on_progress is not None:
                    fraction = (seen / total) if total else 0.0
                    on_progress(min(1.0, fraction), f"{seen / _MB:.0f} MB")
            out.flush()
            os.fsync(out.fileno())

    if total and seen < total:  # dropped mid-download: keep the .part for resume
        raise OSError(f"incomplete download: {seen} of {total} bytes")
    return _finish(part, destination, expected_size, expected_sha256)