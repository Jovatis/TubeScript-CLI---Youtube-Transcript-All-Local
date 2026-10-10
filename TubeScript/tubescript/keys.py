"""Cross-platform single-key reader for interactive menus.

Windows uses :mod:`msvcrt` (``getwch``); POSIX terminals are switched to raw
mode. Both paths return a :class:`Key` so the widgets never deal with
platform-specific escape sequences.

Arrow keys, Enter, Escape, Home/End/PageUp/PageDown and Backspace are all
decoded; anything else comes back as :attr:`Key.CHAR` with its character.
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from enum import Enum
from typing import Iterator

IS_WINDOWS = sys.platform.startswith("win")

try:  # pragma: no cover - import shape depends on the platform
    import msvcrt
except ImportError:  # pragma: no cover
    msvcrt = None  # type: ignore[assignment]

try:  # pragma: no cover
    import termios
    import tty
except ImportError:  # pragma: no cover
    termios = None  # type: ignore[assignment]
    tty = None  # type: ignore[assignment]


class Key(str, Enum):
    """A decoded key press. Subclasses :class:`str` so it compares to text."""

    UP = "UP"
    DOWN = "DOWN"
    LEFT = "LEFT"
    RIGHT = "RIGHT"
    HOME = "HOME"
    END = "END"
    PAGE_UP = "PAGE_UP"
    PAGE_DOWN = "PAGE_DOWN"
    ENTER = "ENTER"
    ESC = "ESC"
    BACKSPACE = "BACKSPACE"
    CHAR = "CHAR"


#: ``msvcrt`` scan codes for the extended keys we care about.
_WINDOWS_KEYS = {
    "H": Key.UP,
    "P": Key.DOWN,
    "K": Key.LEFT,
    "M": Key.RIGHT,
    "G": Key.HOME,
    "O": Key.END,
    "I": Key.PAGE_UP,
    "Q": Key.PAGE_DOWN,
    "S": Key.BACKSPACE,
}

#: Single characters that map to a navigation key.
_CHAR_KEYS = {
    "\r": Key.ENTER,
    "\n": Key.ENTER,
    "\x1b": Key.ESC,
    "\x7f": Key.BACKSPACE,
    "\b": Key.BACKSPACE,
}

#: Escape sequences keyed *without* the leading ESC, so both the CSI form
#: (``ESC [ A``) and the SS3 form (``ESC O A``) resolve correctly.
_ANSI_SEQUENCES = {
    "[A": Key.UP,
    "[B": Key.DOWN,
    "[C": Key.RIGHT,
    "[D": Key.LEFT,
    "[H": Key.HOME,
    "[F": Key.END,
    "OA": Key.UP,
    "OB": Key.DOWN,
    "OC": Key.RIGHT,
    "OD": Key.LEFT,
    "OH": Key.HOME,
    "OF": Key.END,
    "[1~": Key.HOME,
    "[3~": Key.BACKSPACE,
    "[4~": Key.END,
    "[5~": Key.PAGE_UP,
    "[6~": Key.PAGE_DOWN,
    "[7~": Key.HOME,
    "[8~": Key.END,
}

#: Characters that terminate an escape sequence, used to detect sequences we
#: do not recognise (those fall back to a bare Escape).
_SEQUENCE_END = frozenset("ABCDFHPQRS~")

#: How long to wait for the rest of an escape sequence before deciding the
#: user simply pressed Escape. Without this a lone Escape would block.
ESC_TIMEOUT = 0.05

#: Longest sequence we handle is ``ESC [ 6 ~`` -> 3 characters after the ESC.
_MAX_SEQUENCE = 3


class KeyboardUnavailable(RuntimeError):
    """Raised when the process has no interactive console to read from."""


@contextmanager
def _raw_mode() -> Iterator[None]:
    """Disable line buffering and echo on POSIX terminals."""
    if IS_WINDOWS or termios is None or tty is None:
        yield
        return
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)  # keeps Ctrl+C working
        yield
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)


def _read_windows() -> tuple[Key, str]:
    assert msvcrt is not None
    ch = msvcrt.getwch()
    if ch in ("\x00", "\xe0"):  # extended key: the next read is the scan code
        return _WINDOWS_KEYS.get(msvcrt.getwch().upper(), Key.CHAR), ""
    key = _CHAR_KEYS.get(ch, Key.CHAR)
    # Only printable characters carry a meaningful payload.
    return key, ch if key is Key.CHAR else ""


def _read_posix() -> tuple[Key, str]:
    ch = sys.stdin.read(1)
    if ch != "\x1b":
        key = _CHAR_KEYS.get(ch, Key.CHAR)
        return key, ch if key is Key.CHAR else ""

    # An ESC may be the Escape key on its own or the start of a sequence.
    # Peek with a timeout so a lone Escape never blocks.
    seq = ""
    for _ in range(_MAX_SEQUENCE):
        if not _has_input():
            break
        seq += sys.stdin.read(1)
        if seq in _ANSI_SEQUENCES:
            return _ANSI_SEQUENCES[seq], ""
        if seq[-1] in _SEQUENCE_END:
            break  # complete but unrecognised: fall through to a bare Escape
    return Key.ESC, ""


def _has_input() -> bool:
    """Whether stdin has data ready, without blocking for long."""
    try:
        from select import select

        ready, _, _ = select([sys.stdin], [], [], ESC_TIMEOUT)
        return bool(ready)
    except Exception:  # pragma: no cover - non-POSIX or no fileno
        return False


def read_key() -> tuple[Key, str]:
    """Block until a key is pressed.

    Returns ``(Key, character)``; *character* is only meaningful for
    :attr:`Key.CHAR`.
    """
    if not _is_real_console():
        raise KeyboardUnavailable("stdin is not a terminal")
    if IS_WINDOWS:
        if msvcrt is None:  # pragma: no cover
            raise KeyboardUnavailable("msvcrt is unavailable")
        return _read_windows()
    with _raw_mode():
        return _read_posix()


def _is_real_console() -> bool:
    """Whether keystrokes can actually be read.

    Only *stdin* matters here. Requiring stdout to be a TTY as well would
    wrongly disable the arrow-key menu whenever the output is piped or
    redirected (``python main.py > log.txt``), which is a perfectly normal way
    to run the app from a terminal.

    Checking that ``msvcrt`` imports is not enough either: a *piped* stdin
    still imports it on Windows, and the menu would then block forever waiting
    for a key that can never arrive.
    """
    try:
        if not sys.stdin.isatty():
            return False
    except (AttributeError, ValueError):  # detached or closed streams
        return False
    return not IS_WINDOWS or msvcrt is not None


def is_interactive() -> bool:
    """Whether a keyboard-driven menu can be displayed."""
    return _is_real_console()
