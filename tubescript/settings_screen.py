"""The ``/settings`` screen.

Presents the current configuration as a table and lets the user change one
field at a time. Edits are kept in a working copy, so the screen can either
apply them or throw them away without touching ``config.json``.
"""

from __future__ import annotations

from typing import Callable, Sequence

from . import config
from .config import Settings
from .theme import C, G, rule, style
from .widgets import MenuItem, ask_choice, ask_yes_no, term_width

#: Menu values for the top level of the settings screen.
PROFILE = "profile"
THREADS = "threads"
BACK = "back"
DISCARD = "discard"

#: CPU thread counts offered as fixed values.
THREAD_CHOICES: tuple[int, ...] = (2, 4, 8, 12, 16)

_Apply = Callable[[str], bool]


def _profile_label(key: str) -> str:
    return {
        "auto": "Automatic",
        "cpu": "CPU only",
    }.get(key, key)


def describe(settings: Settings) -> list[tuple[str, str]]:
    """Return the (label, current value) rows shown at the top of the screen."""
    return [
        ("Profile", _profile_label(settings.profile)),
        ("CPU threads", "automatic" if settings.threads is None else str(settings.threads)),
    ]


def field(label: str, value: str) -> str:
    """Format one label/value row for the settings table."""
    return f"  {style(G.BULLET, C.FAINT)} {style(f'{label:<22}', C.MUTED)} {style(value, C.ACCENT)}"


def _menu_items() -> list[MenuItem]:
    """The settings menu."""
    return [
        MenuItem("Change profile", PROFILE, "auto / cpu"),
        MenuItem("CPU threads", THREADS, "automatic or fixed"),
        MenuItem("Save and close", BACK),
        MenuItem("Discard changes", DISCARD),
    ]


def _ask(title: str, items: Sequence[MenuItem], apply: _Apply) -> bool:
    """Show a submenu and apply one selection. Returns True when it changed."""
    print()
    rule(min(60, term_width() - 4))
    print(f"  {style(title, C.ACCENT, '1')}")
    print()
    choice = ask_choice("", list(items), visible=len(items), cancellable=True)
    if choice is None:
        return False
    return apply(choice)


def _profile_items() -> list[MenuItem]:
    return [
        MenuItem("Automatic", "auto", "CPU"),
        MenuItem("CPU only", "cpu", "CPU"),
    ]


def _threads_items() -> list[MenuItem]:
    items = [MenuItem("Automatic", "auto", f"uses {config.default_threads()} threads")]
    items += [MenuItem(str(n), str(n)) for n in THREAD_CHOICES]
    return items


def run(settings: Settings) -> Settings:
    """Interactively edit *settings* and return the configuration to use."""
    original = Settings.from_dict(settings.to_dict())
    working = Settings.from_dict(settings.to_dict())
    dirty = False

    while True:
        print()
        rule(min(60, term_width() - 4))
        print(f"  {style('Settings', C.ACCENT, '1')}")
        print()
        print("\n".join(field(name, value) for name, value in describe(working)))
        print()
        if dirty:
            print(f"  {style(G.BULLET, C.FAINT)} {style('You have unapplied changes.', C.MUTED)}")

        choice = ask_choice("", _menu_items(), visible=8, cancellable=True)

        # Escape behaves like "save and close": the user edited on purpose, so
        # silently reverting would be surprising.
        if choice is None or choice == BACK:
            return working

        if choice == DISCARD:
            if dirty and not ask_yes_no("Discard the changes you made?", default=False):
                # Answered "no": stay in the screen with the edits intact.
                print(f"  {style(G.BULLET, C.FAINT)} {style('Changes kept.', C.MUTED)}")
                continue
            print(f"  {style(G.CHECK, C.OK)} {style('Changes discarded.', C.MUTED)}")
            return original

        if choice == PROFILE:
            dirty |= _ask(
                "Profile",
                _profile_items(),
                lambda value: _set(working, value, config.PROFILES, lambda v: setattr(working, "profile", v)),
            )

        elif choice == THREADS:
            dirty |= _ask(
                "CPU threads",
                _threads_items(),
                lambda value: _set(
                    working,
                    value,
                    ("auto", *(str(n) for n in THREAD_CHOICES)),
                    lambda v: setattr(working, "threads", None if v == "auto" else int(v)),
                ),
            )


def _set(working: Settings, value: str, valid: Sequence[str], mutate: Callable[[str], None]) -> bool:
    """Validate *value* and apply *mutate* if it actually changes something."""
    if value not in valid:
        return False
    before = working.to_dict()
    mutate(value)
    return working.to_dict() != before