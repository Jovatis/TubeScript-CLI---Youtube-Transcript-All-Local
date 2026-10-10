"""Persistent user settings.

The whole configuration lives in a single ``config.json`` at the project root so
it survives between launches. Every field has a sensible default, and unknown
or corrupt values fall back to that default instead of crashing the app.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields
from typing import Any

from . import paths
from .errors import SettingsError
from .model_catalog import DEFAULT as _DEFAULT_MODEL
from .model_catalog import normalise as _normalise_model

#: Compute profiles, all CPU-only at the moment. ``auto`` sizes the thread pool
#: from the machine; ``cpu`` is an alias kept for readability.
PROFILES: tuple[str, ...] = ("auto", "cpu")


def default_threads() -> int:
    """Half of the available cores: a good speed/stability compromise."""
    cores = os.cpu_count() or 4
    return max(1, min(8, cores // 2))


@dataclass
class Settings:
    """The full persisted configuration."""

    #: ``auto`` | ``cpu``
    profile: str = "auto"
    #: Whisper model picked on the first launch (catalogue name).
    model: str = _DEFAULT_MODEL
    #: ``None`` means "decide automatically from the CPU count".
    threads: int | None = None

    # -- validation --------------------------------------------------------
    def normalised(self) -> "Settings":
        """Return a copy with every field forced into a valid range."""
        profile = self.profile if self.profile in PROFILES else "auto"
        threads = self.threads
        if threads is not None:
            threads = max(1, min(64, int(threads)))
        return Settings(
            profile=profile,
            model=_normalise_model(self.model),
            threads=threads,
        )

    @property
    def effective_threads(self) -> int:
        return self.threads or default_threads()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Settings":
        known = {f.name for f in fields(cls)}
        data = {k: v for k, v in raw.items() if k in known}
        try:
            settings = cls(**data)
        except TypeError as exc:  # pragma: no cover - defensive
            raise SettingsError(f"Invalid settings file: {exc}") from exc
        return settings.normalised()


def load() -> Settings:
    """Read ``config.json``, falling back to defaults on any problem."""
    path = paths.CONFIG_PATH
    if not path.is_file():
        return Settings().normalised()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return Settings().normalised()
    if not isinstance(raw, dict):
        return Settings().normalised()
    try:
        return Settings.from_dict(raw)
    except (SettingsError, TypeError, ValueError):
        return Settings().normalised()


def save(settings: Settings) -> None:
    """Write the configuration back to disk."""
    path = paths.CONFIG_PATH
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(settings.normalised().to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise SettingsError(
            "Could not save settings.",
            f"{path}\n{exc}",
        ) from exc