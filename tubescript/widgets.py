"""Interactive terminal widgets: the select menu, text prompts, confirmations
and the progress indicators.

The menu is a real keyboard-driven list: arrows move, Enter selects, PageUp /
PageDown jump a screen at a time. When the process has no interactive console
the menu transparently falls back to numbered input so piping output still
works.
"""

from __future__ import annotations

import shutil
import sys
import threading
import time
from dataclasses import dataclass
from typing import Sequence

from . import keys
from .keys import Key
from .theme import C, G, style, visible_len

_ERASE_LINE = "\x1b[2K"
_CURSOR_UP = "\x1b[{n}A"

CANCELLED = object()
"""Sentinel returned when the user aborts a menu with Escape / Ctrl+C."""


def term_width(default: int = 80) -> int:
    try:
        return max(40, shutil.get_terminal_size((default, 24)).columns)
    except OSError:  # pragma: no cover
        return default


# --------------------------------------------------------------------------
# Menu
# --------------------------------------------------------------------------
@dataclass
class MenuItem:
    label: str
    value: str
    note: str = ""
    enabled: bool = True


class SelectMenu:
    """A vertically scrolling, arrow-key navigable list."""

    def __init__(
        self,
        title: str,
        items: Sequence[MenuItem],
        *,
        visible: int = 12,
        initial: int = 0,
        cancellable: bool = False,
    ) -> None:
        self.title = title
        self.items = list(items)
        self.visible = max(3, visible)
        self.index = max(0, min(initial, len(self.items) - 1))
        # A greyed-out row is inert: never land on it, even as the start point.
        self.index = self._nearest_enabled(self.index)
        self.cancellable = cancellable
        self._printed = 0
        self._typed = 0

    # -- navigation --------------------------------------------------------
    def _nearest_enabled(self, index: int) -> int:
        """Closest selectable row to *index*, walking outward in both directions."""
        if not 0 <= index < len(self.items) or self.items[index].enabled:
            return index
        for offset in range(1, len(self.items)):
            for candidate in (index - offset, index + offset):
                if 0 <= candidate < len(self.items) and self.items[candidate].enabled:
                    return candidate
        return index

    # -- rendering ---------------------------------------------------------
    def _truncate(self, text: str, width: int) -> str:
        if len(text) <= width:
            return text
        return text[: max(0, width - 1)] + G.ELLIPSIS

    def _row(self, item: MenuItem, selected: bool) -> str:
        width = term_width() - 8
        note = f"  {item.note}" if item.note else ""
        label = self._truncate(item.label, max(4, width - visible_len(note)))
        if not item.enabled:
            marker = " "
            color = C.FAINT
        elif selected:
            marker = style(G.CURSOR, C.ACCENT)
            color = C.ACCENT
        else:
            marker = " "
            color = C.MUTED
        return f"  {marker} {style(label, color)}{style(note, C.FAINT)}"

    def _window(self) -> tuple[int, int]:
        """Return the ``(first, last)`` visible slice, scrolling around the cursor."""
        if len(self.items) <= self.visible:
            return 0, len(self.items)
        half = self.visible // 2
        first = self.index - half
        first = max(0, min(first, len(self.items) - self.visible))
        return first, first + self.visible

    def _draw(self) -> None:
        lines: list[str] = []
        if self.title:
            lines.append("")
            lines.append(f"  {style(self.title, C.TEXT)}")
            lines.append("")

        first, last = self._window()
        for position in range(first, last):
            lines.append(self._row(self.items[position], position == self.index))

        if len(self.items) > self.visible:
            counter = f"  {self.index + 1}/{len(self.items)}"
            lines.append(style(counter, C.FAINT))

        lines.append("")
        keys_line = f"  {style(G.UP, C.FAINT)} {style(G.DOWN, C.FAINT)} navigate"
        keys_line += f"   {style('Enter', C.FAINT)} select"
        keys_line += f"   {style('#', C.FAINT)} jump to number"
        if self.cancellable:
            keys_line += f"   {style('Esc', C.FAINT)} cancel"
        lines.append(style(keys_line, C.DIM))
        lines.append("")

        if self._printed:
            sys.stdout.write(_CURSOR_UP.format(n=self._printed))
        sys.stdout.write(_ERASE_LINE + "\r")
        for row in lines:
            sys.stdout.write(_ERASE_LINE + row + "\n")
        sys.stdout.flush()
        self._printed = len(lines)

    def _clear(self) -> None:
        if not self._printed:
            return
        sys.stdout.write(_CURSOR_UP.format(n=self._printed))
        for _ in range(self._printed):
            sys.stdout.write(_ERASE_LINE + "\n")
        sys.stdout.write(_CURSOR_UP.format(n=self._printed))
        sys.stdout.flush()
        self._printed = 0

    # -- interaction -------------------------------------------------------
    def _move(self, delta: int) -> None:
        count = len(self.items)
        if not count:
            return
        step = 1 if delta > 0 else -1
        for _ in range(abs(delta)):
            # Greyed-out rows are skipped, with wraparound once per step.
            for _ in range(count):
                self.index = (self.index + step) % count
                if self.items[self.index].enabled:
                    break

    def _run_interactive(self) -> str | object:
        self._typed = 0
        while True:
            self._draw()
            key, char = keys.read_key()
            if key is not Key.CHAR:
                self._typed = 0
            if key is Key.UP:
                self._move(-1)
            elif key is Key.DOWN:
                self._move(1)
            elif key is Key.PAGE_UP:
                self._move(-self.visible)
            elif key is Key.PAGE_DOWN:
                self._move(self.visible)
            elif key is Key.HOME:
                self.index = self._nearest_enabled(0)
            elif key is Key.END:
                self.index = self._nearest_enabled(len(self.items) - 1)
            elif key is Key.ENTER:
                item = self.items[self.index]
                if not item.enabled:
                    # Greyed-out rows are inert: ignore the keypress rather
                    # than cancelling the whole menu under the user.
                    continue
                self._clear()
                return item.value
            elif key is Key.ESC:
                # When the menu cannot be cancelled, Escape is simply ignored.
                if self.cancellable:
                    self._clear()
                    return CANCELLED
            elif key is Key.CHAR and char == "\x03":  # Ctrl+C
                self._clear()
                raise KeyboardInterrupt
            elif key is Key.CHAR and char in ("k", "j"):
                self._move(-1 if char == "k" else 1)
            elif key is Key.CHAR and char.isdigit():
                # Type-ahead: digits select by position, so the menu stays
                # usable even where arrow keys are not decoded. Digits keep
                # accumulating until no longer number could follow, at which
                # point the choice is committed ("1" then "2" picks item 12).
                total = len(self.items)
                candidate = self._typed * 10 + int(char)
                if not 1 <= candidate <= total:
                    self._typed = 0  # out of range: start over
                    continue
                if not self.items[candidate - 1].enabled:
                    self._typed = 0  # greyed-out row is inert even by number
                    continue
                self.index = candidate - 1
                if candidate * 10 > total:
                    self._clear()
                    return self.items[candidate - 1].value
            elif key is Key.CHAR:
                self._typed = 0

    def _run_fallback(self) -> str | object:
        """Numbered selection, used when there is no real console."""
        # Say why the arrow keys are not offered, otherwise a user piped
        # through a wrapper just sees a dead menu and no explanation.
        print(style("  No interactive console detected - select by number.", C.WARN))
        options = [item for item in self.items if item.enabled]
        for position, item in enumerate(options, start=1):
            note = f"  {item.note}" if item.note else ""
            print(f"  {style(str(position).rjust(3), C.ACCENT)}  {style(item.label, C.MUTED)}{style(note, C.FAINT)}")
        while True:
            try:
                raw = input(style("\n  # ", C.ACCENT)).strip()
            except EOFError:
                return CANCELLED
            if raw.isdigit() and 1 <= int(raw) <= len(options):
                return options[int(raw) - 1].value
            print(style("  Enter a number between 1 and %d." % len(options), C.ERR))

    def run(self) -> str | object:
        if keys.is_interactive():
            return self._run_interactive()
        return self._run_fallback()


def ask_choice(
    title: str,
    items: Sequence[MenuItem],
    *,
    visible: int = 12,
    initial: int = 0,
    cancellable: bool = False,
) -> str | None:
    """Run a :class:`SelectMenu` and return the chosen value (or ``None``)."""
    menu = SelectMenu(
        title, items, visible=visible, initial=initial, cancellable=cancellable,
    )
    result = menu.run()
    return None if result is CANCELLED else result  # type: ignore[return-value]


# --------------------------------------------------------------------------
# Text input
# --------------------------------------------------------------------------
def _input_line(*, cancellable: bool = False) -> str | None:
    """A minimal single-line editor used when Escape must cancel the prompt.

    ``input()`` swallows Escape, so the URL prompt runs this instead: regular
    characters echo as they are typed, Backspace erases in place, Enter submits
    and Escape returns ``None`` so the caller can go back. Ctrl+C still raises
    KeyboardInterrupt.
    """
    sys.stdout.write(f"  {style(G.CURSOR, C.ACCENT)} ")
    sys.stdout.flush()
    buf: list[str] = []
    while True:
        key, char = keys.read_key()
        if key is Key.ENTER:
            sys.stdout.write("\n")
            sys.stdout.flush()
            return "".join(buf)
        if key is Key.ESC:
            sys.stdout.write("\n")
            sys.stdout.flush()
            return None
        if key is Key.BACKSPACE:
            if buf:
                buf.pop()
                sys.stdout.write("\b \b")
                sys.stdout.flush()
        elif key is Key.CHAR and char:
            if char == "\x03":
                raise KeyboardInterrupt
            buf.append(char)
            sys.stdout.write(char)
            sys.stdout.flush()


def ask_text(
    title: str,
    placeholder: str = "",
    *,
    default: str | None = None,
    cancellable: bool = False,
) -> str | None:
    """Prompt for a line of text. Returns ``None`` on EOF (or on Escape when
    *cancellable* is set on a real console)."""
    print()
    print(f"  {style(title, C.TEXT)}")
    if placeholder:
        print(f"  {style(placeholder, C.FAINT)}")
    if cancellable:
        print(f"  {style('ESC goes back.', C.FAINT)}")
    if cancellable and keys.is_interactive():
        raw = _input_line(cancellable=True)
    else:
        suffix = f" {style('[Enter = ' + default + ']', C.FAINT)}" if default else ""
        try:
            raw = input(f"  {style(G.CURSOR, C.ACCENT)} {suffix}")
        except EOFError:
            print()
            return None
    if raw is None:
        return None
    return raw.strip() or (default or "")


def ask_yes_no(title: str, *, default: bool = False) -> bool:
    """A compact yes/no prompt."""
    options = "Y/n" if default else "y/N"
    print()
    print(f"  {style(title, C.TEXT)}")
    while True:
        try:
            raw = input(f"  {style(G.CURSOR, C.ACCENT)} {style('[' + options + ']', C.FAINT)} ").strip().lower()
        except EOFError:
            return default
        if not raw:
            return default
        if raw in ("y", "yes", "o", "oui"):
            return True
        if raw in ("n", "no", "non"):
            return False
        print(style(f"  Please answer yes or no.", C.ERR))


# --------------------------------------------------------------------------
# Progress
# --------------------------------------------------------------------------
def human_bytes(count: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if count < 1024 or unit == "GB":
            return f"{count:.0f} {unit}" if unit == "B" else f"{count:.1f} {unit}"
        count /= 1024
    return f"{count:.1f} GB"


def human_time(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def stdout_is_tty() -> bool:
    """True when stdout is a real terminal we can safely redraw in place."""
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


class ProgressBar:
    """A two-line in-place progress indicator: a caption above a bar.

    The bar is sized to the terminal so the row can never wrap. That matters:
    when a row is wider than the screen the carriage return only comes back to
    the start of the last *visual* line, so every repaint would push another
    line onto the console instead of overwriting the previous one.

    When stdout is not a terminal the repaints are dropped entirely - a pipe
    has no cursor to return to, so each frame would become its own line.
    """

    MIN_BAR_WIDTH = 4
    # indent(2) + gap(2) + percent(4) + gap(2): the room the row needs besides
    # the bar itself.
    CHROME = 10

    def __init__(self, caption: str, icon: str = G.SPARK, bar_width: int = 30) -> None:
        self.caption = caption
        self.icon = icon
        self._last = -1.0
        self._drawn = False
        self.bar_width = max(self.MIN_BAR_WIDTH, min(bar_width, term_width() - self.CHROME))

    def _row(self, fraction: float, detail: str = "") -> str:
        filled = int(round(fraction * self.bar_width))
        bar = style(G.BLOCK * filled, C.ACCENT) + style(
            G.BLOCK_LIGHT * (self.bar_width - filled), C.FAINT
        )
        percent = f"{fraction * 100:3.0f}%"
        row = f"  {bar}  {style(percent, C.MUTED)}  {style(detail, C.FAINT)}"
        if visible_len(row) > term_width():
            # The detail is the first thing to go; the bar and the count matter more.
            row = f"  {bar}  {style(percent, C.MUTED)}"
        return row

    def _paint(self, fraction: float, detail: str = "") -> None:
        fraction = min(1.0, max(0.0, fraction))
        if not stdout_is_tty():
            return
        sys.stdout.write(_ERASE_LINE + self._row(fraction, detail) + "\r")
        sys.stdout.flush()
        self._drawn = True

    def update(self, fraction: float, detail: str = "") -> None:
        self._paint(fraction, detail)

    def start(self, detail: str = "") -> None:
        print(f"  {style(self.icon, C.ACCENT)} {style(self.caption, C.TEXT)}")
        self._last = -1.0
        self._paint(0.0, detail)

    def finish(self, detail: str = "") -> None:
        self._paint(1.0, detail)
        if stdout_is_tty():
            sys.stdout.write("\n")
            sys.stdout.flush()
        else:
            print()
        self._drawn = False

    def stop(self) -> None:
        """Terminate the bar without claiming completion."""
        if not self._drawn:
            return
        if stdout_is_tty():
            sys.stdout.write(_ERASE_LINE + "\n")
            sys.stdout.flush()
        self._drawn = False


class Spinner:
    """An indeterminate activity indicator for waits such as model loading."""

    FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
    ASCII_FRAMES = ("|", "/", "-", "\\")

    def __init__(self, caption: str, interval: float = 0.08) -> None:
        from .theme import UNICODE

        self.caption = caption
        self.interval = interval
        self.frames = self.FRAMES if UNICODE else self.ASCII_FRAMES
        self._frame = 0
        self._running = False
        self._thread: threading.Thread | None = None

    def _spin(self) -> None:
        if not stdout_is_tty():
            # A pipe has no cursor; spinning would add a line per frame.
            return
        while self._running:
            frame = self.frames[self._frame % len(self.frames)]
            sys.stdout.write(_ERASE_LINE + f"  {style(frame, C.ACCENT)} {style(self.caption, C.MUTED)}\r")
            sys.stdout.flush()
            self._frame += 1
            time.sleep(self.interval)

    def __enter__(self) -> "Spinner":
        self._running = True
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=0.3)
        sys.stdout.write(_ERASE_LINE + "\r")
        sys.stdout.flush()
