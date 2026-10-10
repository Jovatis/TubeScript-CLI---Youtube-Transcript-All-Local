"""TubeScript CLI entry point.

Run from the project root with:

    python main.py
    python main.py --version
    python main.py --help

or double-click ``TubeScript.bat``.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the local ``tubescript`` package importable no matter where the script
# is launched from (Explorer, a terminal, or the .bat wrapper).
sys.path.insert(0, str(Path(__file__).resolve().parent))

from tubescript import __version__  # noqa: E402
from tubescript.app import main  # noqa: E402

_HELP = """TubeScript CLI - YouTube to text transcription in the terminal

Usage: python main.py [options]

Options:
  -h, --help     Show this help message and exit
  -v, --version  Show version and exit

Keyboard shortcuts (interactive UI):
  ↑/↓, k/j      Navigate menu
  Enter         Confirm
  Esc           Back/Cancel (when available)
  Ctrl+C        Quit
  Backspace     Remove last line in queue (interactive paste)

Examples:
  python main.py                Launch the interactive UI
  python main.py --version       Print version
"""


def _run_cli() -> int:
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg in ("-v", "--version"):
            print(f"TubeScript CLI {__version__}")
            return 0
        if arg in ("-h", "--help"):
            print(_HELP)
            return 0
        print(f"Unknown option: {arg}")
        print("Try 'python main.py --help' for more information.")
        return 2
    return main()


if __name__ == "__main__":
    sys.exit(_run_cli())