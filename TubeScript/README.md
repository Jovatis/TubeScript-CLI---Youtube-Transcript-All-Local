# TubeScript CLI

TubeScript CLI is a simple, fast, and reliable terminal tool for transcribing YouTube videos to text. It runs entirely in your terminal with a clean, interactive interface.

## Features

- **Simple terminal UI** — Clean, keyboard-driven interface with clear menus and progress bars.
- **Single or batch transcription** — Transcribe one video or a queue of multiple YouTube URLs.
- **Automatic audio extraction** — Downloads only the audio using `yt-dlp` and converts it to 16 kHz mono for optimal transcription.
- **Local Whisper transcription** — Uses `pywhispercpp` (whisper.cpp) for fully offline transcription once the model is downloaded.
- **Smart model management** — On first launch, choose from a curated list of Whisper models by size, speed, and accuracy. Switch, install, or uninstall models from the built-in manager.
- **Secure model verification** — Every model is pinned by exact file size and SHA-256 (verified on download and at every launch). Invalid, tampered, or non-binary payloads are rejected.
- **Automatic cleanup** — Temporary audio files are removed after each run and stale temp files are swept automatically.
- **Persistent settings** — CPU preferences, threads, and active model are saved in `config.json`.
- **Keyboard-first workflow** — Navigate with arrow keys, `Enter`, `Esc`, and `Backspace`. Works well in standard Windows terminals.
- **Safe and self-contained** — All files (models, transcripts, temp data) stay inside the project folder. No external system writes outside the project.

## Requirements

- Windows 10/11
- [Python 3.10+](https://www.python.org/downloads/) available in your PATH
- [FFmpeg](https://ffmpeg.org/download.html) (recommended: `winget install Gyan.FFmpeg`)

## Installation

### Option 1: Quick start (recommended)

1. Download or extract the `TubeScript CLI` folder to any location.
2. Double-click `TubeScript.bat` to launch the app.

On the very first launch the launcher creates a local `.venv/` and installs the pinned dependencies from `requirements.txt` automatically. Later launches skip the setup and reuse the environment.

### Option 2: Manual setup (optional)

The launcher covers this for you; only follow these steps if you prefer to.

1. Extract the `TubeScript CLI` folder to any location.
2. Open a terminal in that folder.
3. Create a virtual environment: `python -m venv .venv && .venv\Scripts\activate.bat`
4. Install dependencies: `pip install -r requirements.txt`
5. Double-click `TubeScript.bat` to launch.

## Usage

### Launch the app

Double-click `TubeScript.bat`. It creates a local virtual environment on first run (installing the dependencies), then launches the CLI.

You can also run it from a terminal: `python main.py`

### Workflow

1. **Choose a mode** — Select `A single video`, `A queue of videos`, or `Manage models` from the main menu.
2. **Enter URLs** — For a single video, paste a YouTube URL (e.g. `https://www.youtube.com/watch?v=...` or `https://youtu.be/...`). For a queue, paste multiple URLs, one per line. `Backspace` removes the last line, `Esc` returns to the menu.
3. **Confirm** — Review the video(s) to transcribe, then confirm to proceed.
4. **Transcribe** — Audio is downloaded, converted, and transcribed with Whisper. Progress bars show download and transcription status.
5. **Get your transcript** — `.txt` files are saved to `output/` (named after each video's title). Temporary audio files are cleaned up automatically.

### Manage models

From `Manage models` you can:
- **Switch model** — Choose which installed model TubeScript should use (the active model is marked `in use`).
- **Install a model** — Download any model from the built-in catalogue. Models already installed are disabled.
- **Uninstall a model** — Remove installed models (the currently active model cannot be uninstalled).

Model choice is saved to `config.json` and persists between launches.

### Settings (/settings)

From the URL input screen, type /settings and press Enter to open settings.

Available options:
- **Compute profile** - auto or cpu
- **CPU threads** - Automatic or a fixed number of threads

Press Esc or Save and close to apply changes. Settings are saved to config.json.

## Project structure

```text
TubeScript CLI/
├── TubeScript.bat        # Windows launcher (creates .venv + deps on first run)
├── main.py               # CLI entry point
├── config.json           # Persistent settings (auto-generated)
├── LICENSE               # Usage terms (personal and educational use)
├── .gitattributes        # Line-ending rules (Windows-safe)
├── .editorconfig         # Editor style defaults
├── .gitignore            # Ignores runtime data and caches
├── models/               # Whisper GGML models (auto-downloaded on first use)
├── output/               # Transcripts (.txt) saved here
├── tmp/                  # Temporary audio files (auto-cleaned)
└── tubescript/           # Source code
    ├── __init__.py       # Package metadata
    ├── __main__.py       # `python -m tubescript` entry point
    ├── app.py            # UI, workflow, and orchestration
    ├── cleanup.py        # Temp file cleanup and sweeping
    ├── config.py         # Load/save config.json
    ├── downloader.py     # yt-dlp audio download + conversion
    ├── errors.py         # Application error types
    ├── fetch.py          # Secure HTTP download with resume + integrity checks
    ├── keys.py           # Keyboard input handling
    ├── languages.py      # Whisper language list
    ├── model_catalog.py  # Model catalogue with pinned sizes and SHA-256
    ├── paths.py          # Project paths (self-contained)
    ├── settings_screen.py# Settings screen (CPU preferences)
    ├── theme.py          # Terminal colors, icons, and layout
    ├── transcriber.py    # Whisper backend via pywhispercpp
    └── widgets.py        # Menus, prompts, and progress bars
```

## Troubleshooting

| Issue | Solution |
|---|---|
| `ffmpeg` not found | Install FFmpeg: `winget install Gyan.FFmpeg`, then relaunch. Or download from [ffmpeg.org](https://ffmpeg.org/download.html). |
| Missing Python dependencies | Run `pip install -r requirements.txt`. |
| Model download fails or is rejected | TubeScript verifies SHA-256 and size. If verification fails, the corrupt file is removed. Relaunch and it will redownload cleanly. You can also manually place a valid `.bin` model in `models/` and TubeScript will adopt it. |
| Age-restricted/private videos | Some videos cannot be downloaded by `yt-dlp` due to restrictions. |
| Encoding/emoji issues | Run via `TubeScript.bat` (forces UTF-8) or use a modern UTF-8 terminal. |

## License

Personal and educational use. See [LICENSE](LICENSE). Respect YouTube's Terms of Service and the rights of the content you transcribe.