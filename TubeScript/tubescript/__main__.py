"""TubeScript CLI - YouTube to text transcription in the terminal."""

from __future__ import annotations

import sys

if __name__ == "__main__":
    from . import __version__

    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg in ("-v", "--version"):
            print(f"TubeScript CLI {__version__}")
            sys.exit(0)
        if arg in ("-h", "--help"):
            print(
                "TubeScript CLI - YouTube to text transcription in the terminal\n\n"
                "Usage: python -m tubescript [options]\n\n"
                "Options:\n"
                "  -h, --help     Show this help message and exit\n"
                "  -v, --version  Show version and exit"
            )
            sys.exit(0)
        print(f"Unknown option: {arg}")
        print("Try 'python -m tubescript --help' for more information.")
        sys.exit(2)

    from .app import main

    sys.exit(main())