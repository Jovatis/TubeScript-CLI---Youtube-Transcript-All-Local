"""Whisper model catalogue shown on the very first launch.

Each entry carries the file stem, the approximate download size, the hardware
it realistically needs and the **SHA-256 pin** of the exact GGML file, so a user
with no model yet can pick the right trade-off between accuracy, speed and RAM.
The names are valid GGML files on the official whisper.cpp mirror - downloading
one is as simple as ``https://huggingface.co/ggerganov/whisper.cpp/resolve/main/<name>.bin``.

Sizes and hashes come from the HuggingFace API for ``ggerganov/whisper.cpp``
(``tree/main?recursive=true&expand=true``); they pin *that* file, so a download
that returns anything else - an HTML error page, a tampered binary, ... - is
rejected before the model is ever loaded.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelOption:
    #: File stem, e.g. ``ggml-tiny`` -> ``models/ggml-tiny.bin``.
    name: str
    #: Approximate download size, shown in the menu.
    size: str
    #: Realistic hardware requirement, shown in the menu.
    hardware: str
    #: Exact size in bytes of the pinned file (checked after download).
    size_bytes: int
    #: SHA-256 of the official file used to verify every download.
    sha256: str


OPTIONS: tuple[ModelOption, ...] = (
    ModelOption(
        "ggml-large-v3-turbo-q8_0",
        "~834 MB",
        "4 GB+ RAM - strongest speed/accuracy, GPU optional (recommended)",
        874188075,
        "317eb69c11673c9de1e1f0d459b253999804ec71ac4c23c17ecf5fbe24e259a1",
    ),
    ModelOption(
        "ggml-medium-q5_0",
        "~514 MB",
        "2-4 GB RAM - best quality per megabyte, good on CPU",
        539212467,
        "19fea4b380c3a618ec4723c3eef2eb785ffba0d0538cf43f8f235e7b3b34220f",
    ),
    ModelOption(
        "ggml-small",
        "~465 MB",
        "2 GB+ RAM - solid all-rounder for weaker machines",
        487601967,
        "1be3a9b2063867b937e64e2ec7483364a79917e157fa98c5d94b5c1fffea987b",
    ),
    ModelOption(
        "ggml-base",
        "~141 MB",
        "1 GB+ RAM - light and quick",
        147951465,
        "60ed5bc3dd14eea856493d334349b405782ddcaf0028d4b5df4088345fba2efe",
    ),
    ModelOption(
        "ggml-tiny",
        "~74 MB",
        "512 MB+ RAM - smallest and fastest, lowest accuracy",
        77691713,
        "be07e048e1e599ad46341c8d2a135645097a538221678b7acdd1b1919c6e1b21",
    ),
)

#: The model used when the user never picks one.
DEFAULT: str = OPTIONS[0].name


def normalise(name: str) -> str:
    """Return *name* when it is a known model, otherwise the default."""
    return DEFAULT if lookup(name) is None else name


def lookup(name: str) -> ModelOption | None:
    """The catalogue entry for *name*, or ``None`` for unknown models."""
    for option in OPTIONS:
        if option.name == name:
            return option
    return None