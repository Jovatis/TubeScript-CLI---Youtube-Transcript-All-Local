"""Terminal visual language: colours, glyphs, and the low-level drawing
primitives shared by the rest of the UI.

Everything degrades gracefully:

* ``NO_COLOR`` (https://no-color.org) or a non-tty stream disables colours;
* ``TUBESCRIPT_ASCII=1`` forces the ASCII glyph set, which is also selected
  automatically when the terminal cannot encode box-drawing characters.
"""

from __future__ import annotations

import os
import re
import sys
from typing import Sequence

# --------------------------------------------------------------------------
# Terminal capabilities
# --------------------------------------------------------------------------
# Windows terminals are notoriously inconsistent about encodings, so the
# streams are switched to UTF-8 up front. If that is impossible we fall back to
# pure ASCII instead of printing mojibake.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError, OSError):  # pragma: no cover - old/odd streams
        pass


def _console_supports_unicode() -> bool:
    if os.environ.get("TUBESCRIPT_ASCII") == "1":
        return False
    encoding = (getattr(sys.stdout, "encoding", "") or "").lower()
    return "utf" in encoding


UNICODE: bool = _console_supports_unicode()
COLOR: bool = (
    os.environ.get("NO_COLOR") is None
    and os.environ.get("TERM") != "dumb"
    and hasattr(sys.stdout, "isatty")
    and sys.stdout.isatty()
)

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def visible_len(text: str) -> int:
    """Length of *text* once ANSI escape sequences are ignored."""
    return len(_ANSI_RE.sub("", text))


# --------------------------------------------------------------------------
# Palette - a warm clay accent on greys.
# Every value must be a full SGR foreground selector (``38;5;n`` for the
# 256-colour cube, ``38;2;r;g;b`` for 24-bit); a bare number is silently
# ignored by the terminal and the text falls back to the default colour.
# --------------------------------------------------------------------------
class C:
    ACCENT = "38;2;237;129;84"  # rgb(173, 115, 90)rgb(237, 129, 84)
    ACCENT_DIM = "38;2;130;86;68"  # same hue, muted
    TEXT = "38;5;252"
    MUTED = "38;5;245"
    DIM = "38;5;240"
    FAINT = "38;5;238"
    OK = "38;5;114"
    WARN = "38;5;179"
    ERR = "38;5;203"  # #ff5f5f - errors stay red, they are not the accent
    INFO = "38;5;110"
    BRIGHT = "38;5;231"  # #ffffff


def style(text: str, *codes: str) -> str:
    """Wrap *text* in the given ANSI *codes* (no-op without colour support)."""
    if not COLOR or not codes:
        return text
    return "\x1b[" + ";".join(codes) + "m" + text + "\x1b[0m"


# --------------------------------------------------------------------------
# Glyphs
# --------------------------------------------------------------------------
class G:
    """The glyph set, swapped for ASCII when the terminal cannot cope."""

    UL = "\u256d" if UNICODE else "+"
    UR = "\u256e" if UNICODE else "+"
    LL = "\u2570" if UNICODE else "+"
    LR = "\u256f" if UNICODE else "+"
    H = "\u2500" if UNICODE else "-"
    V = "\u2502" if UNICODE else "|"

    BLOCK = "\u2588" if UNICODE else "#"
    BLOCK_LIGHT = "\u2591" if UNICODE else "."
    BULLET = "\u2022" if UNICODE else "*"

    CURSOR = "\u276f" if UNICODE else ">"
    UP = "\u2191" if UNICODE else "^"
    DOWN = "\u2193" if UNICODE else "v"
    ARROW = "\u2192" if UNICODE else "->"

    CHECK = "\u2714" if UNICODE else "v"
    CROSS = "\u2718" if UNICODE else "x"
    WARN = "\u26a0" if UNICODE else "!"
    BRAIN = "\U0001f9e0" if UNICODE else "*"
    DOWNLOAD = "\u2b07" if UNICODE else "v"
    SPARK = "\u2726" if UNICODE else "*"

    ELLIPSIS = "\u2026" if UNICODE else "..."


def frame(title: str, width: int = 44, subtitle: str = "") -> str:
    """A framed title card, with the title inset in the top border.

    *width* is the full outer width, so the box never exceeds the terminal.
    """
    outer = max(28, width)
    inner = outer - 2  # room between the two vertical bars
    label = f" {title} "

    rows = [
        G.UL
        + style(G.H, C.FAINT)
        + style(label, C.ACCENT, "1")
        + style(G.H * max(0, outer - 3 - len(label)), C.FAINT)
        + style(G.UR, C.FAINT),
        style(G.V, C.FAINT) + " " * inner + style(G.V, C.FAINT),
    ]
    if subtitle:
        pad = max(0, inner - visible_len(subtitle))
        rows.append(
            style(G.V, C.FAINT)
            + " " * (pad // 2 + 1)
            + style(subtitle, C.MUTED)
            + " " * (pad - pad // 2 - 1)
            + style(G.V, C.FAINT)
        )
        rows.append(style(G.V, C.FAINT) + " " * inner + style(G.V, C.FAINT))
    rows.append(style(G.LL + G.H * inner + G.LR, C.FAINT))
    return "\n".join(rows)


# --------------------------------------------------------------------------
# Primitives
# --------------------------------------------------------------------------
def blank() -> None:
    print()


def clear() -> None:
    """Erase the screen and the scrollback, then home the cursor.
    The app is a sequence of pages, so a page change wipes the previous one and
    the console only shows the current step. When stdout is not a terminal (a
    pipe, a log file) those escapes would be noise, so a blank line is printed
    instead and the captured log stays complete.
    """
    if not (hasattr(sys.stdout, "isatty") and sys.stdout.isatty()):
        blank()
        return
    esc = chr(27)
    sys.stdout.write(esc + "[2J" + esc + "[3J" + esc + "[H")
    sys.stdout.flush()


def line(text: str = "", color: str | None = None) -> None:
    print(style(text, color) if color else text)


def rule(width: int = 46, char: str | None = None) -> None:
    print(style((char or G.H) * width, C.FAINT))


def field(name: str, value: str, name_width: int = 14) -> str:
    """A ``name  value`` line, the workhorse of the settings and result views."""
    return (
        style("  " + name.ljust(name_width), C.DIM)
        + style(value, C.TEXT)
    )


def warn(text: str) -> None:
    print(f"  {style(G.WARN, C.WARN)} {style(text, C.WARN)}")


def hint(text: str) -> None:
    print(f"    {style(text, C.FAINT)}")


def kv_block(pairs: Sequence[tuple[str, str]], name_width: int = 14) -> str:
    return "\n".join(field(k, v, name_width) for k, v in pairs)
