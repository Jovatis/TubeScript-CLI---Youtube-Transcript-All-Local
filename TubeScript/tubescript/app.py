"""The main application orchestrator.

Brings together the UI, downloader, transcriber and settings into the exact
workflow requested: ASCII logo, URL prompt, audio download,
transcription, cleanup, and results summary. The language is always
auto-detected; there is no manual language picker.
"""

from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

try:
    import msvcrt
except ImportError:  # pragma: no cover - paste capture is Windows only
    msvcrt = None  # type: ignore[assignment]

from . import config, downloader, fetch, keys, languages, model_catalog, paths, settings_screen
from .downloader import MediaInfo
from .errors import TubeScriptError
from .keys import Key
from .languages import AUTO
from .theme import (
    C,
    G,
    blank,
    clear,
    frame,
    hint,
    kv_block,
    line,
    rule,
    style,
    warn,
)
from .transcriber import Transcriber
from .widgets import (
    MenuItem,
    ProgressBar,
    Spinner,
    ask_choice,
    ask_text,
    ask_yes_no,
    human_bytes,
    human_time,
    term_width,
)

#: Audio older than this in ``tmp/`` is considered abandoned by a crashed run.
_STALE_TMP_AGE = 3600.0

#: Values returned by the end-of-run menu.
NEXT_OPEN = "open"
NEXT_HOME = "home"
NEXT_EXIT = "exit"

#: Transcription modes chosen on the home screen.
MODE_SINGLE = "single"
MODE_MULTI = "multi"
MODE_MODELS = "models"

#: Choices inside the model manager.
MODELS_SWITCH = "switch"
MODELS_INSTALL = "install"
MODELS_UNINSTALL = "uninstall"
MODELS_BACK = "back"

#: Sent return code when the queue input is cancelled with ESC: run() then
#: falls back to the mode choice instead of exiting.
BACK = -1

#: Open-transcript picker: video titles longer than this get "…".
_TITLE_LIMIT = 50

#: Paste detection: a gap this long ends the current clip, and shorter
#: bursts are discarded as stray typing rather than pasted links.
_PASTE_GAP = 0.25
_PASTE_MIN = 4

#: A lone ESC - not followed by a sequence within this window - backs out of
#: the queue input. Bracketed-paste markers and escape sequences land inside
#: this gap, so a paste is never mistaken for an ESC press.
_ESC_GAP = 0.05



class App:
    """The TubeScript CLI runtime."""

    def __init__(self) -> None:
        paths.ensure_dirs()
        self.settings = config.load()
        self._status: list[str] = []
        self._detected_language: str | None = None
        self._transcripts: list[tuple[str, Path]] = []

    # -- helpers -----------------------------------------------------------
    def _set_status(self, text: str) -> None:
        """Record a line for the summary shown once the run finishes."""
        self._status.append(text)

    def _welcome(self) -> None:
        """The splash screen: a title card and a prompt to carry on."""
        width = term_width()
        blank()
        for row in frame("Welcome to TubeScript CLI", width, "YouTube \u2192 Text Transcription").splitlines():
            line(row)
        blank()
        line(f"  {style('press enter to continue', C.DIM)}")
        blank()
        self._wait_for_enter()

    def _wait_for_enter(self) -> None:
        """Block until Enter is pressed, with a non-interactive fallback."""
        try:
            while keys.read_key()[0] is not Key.ENTER:
                pass
        except keys.KeyboardUnavailable:
            # Piped stdin: read a line so the splash does not just scroll past.
            input()

    def _after_run_error(self) -> int:
        """A failed run: keep the error readable, then loop back to the menu.

        Piped runs return a failure exit code instead - there is no menu to go
        back to, and the caller expects a non-zero status for a failed batch.
        """
        if not keys.is_interactive():
            return 1
        blank()
        line(f"  {style('Press Enter to return to the menu.', C.DIM)}")
        self._wait_for_enter()
        return BACK

    def _confirm(self, canonical: str) -> bool:
        """Show what is about to run and ask for the go-ahead."""
        blank()
        line(f"  {style('Ready to transcribe', C.ACCENT, '1')}")
        blank()
        line(
            kv_block(
                [
                    ("Video", canonical),
                    ("Language", self._language_report()),
                    ("Model", paths.MODEL_NAME),
                ]
            )
        )
        blank()
        return ask_yes_no("Start the transcription?", default=True)

    def _print_error(self, exc: TubeScriptError) -> None:
        blank()
        line(f"  {style(G.CROSS, C.ERR)} {style(exc.message, C.ERR)}")
        if exc.hint:
            for paragraph in str(exc.hint).splitlines():
                line(f"    {style(paragraph, C.FAINT)}")

    # -- screens -----------------------------------------------------------
    def _ask_url(self) -> str | None:
        while True:
            blank()
            url = ask_text(
                "Paste a YouTube video URL",
                placeholder="https://www.youtube.com/watch?v=...",
                cancellable=True,
            )
            if url is None:
                return None
            url = url.strip()
            if url == "/settings":
                self._open_settings()
                clear()  # settings was its own page
                continue
            if not url:
                line(style("  A URL is required.", C.ERR))
                if keys.is_interactive():
                    time.sleep(1.0)  # let the message sink in, then start over
                    clear()
                continue
            try:
                url = downloader.normalise_url(url)  # validate and canonicalise
            except TubeScriptError as exc:
                line(style(f"  {exc.message}", C.ERR))
                if exc.hint:
                    for paragraph in str(exc.hint).splitlines():
                        line(f"    {style(paragraph, C.FAINT)}")
                if keys.is_interactive():
                    time.sleep(1.0)  # keep the message readable, then re-prompt
                    clear()
                continue
            return url

    def _language_report(self) -> str:
        """Describe the language actually used, naming the detected one."""
        detected = self._detected_language
        if not detected:
            return "Auto-detect"
        language = languages.find(detected)
        name = language.label if language else detected
        return f"Auto-detect \u2192 {name}"

    # -- workflow ----------------------------------------------------------
    def _download_step(self, url: str) -> MediaInfo:
        blank()
        pb = ProgressBar("Downloading audio", icon=G.DOWNLOAD)
        pb.start(detail="starting...")

        def on_progress(fraction: float, detail: str) -> None:
            pb.update(fraction, detail)

        media = downloader.download_audio(url, on_progress=on_progress)
        pb.finish(detail="done")
        return media

    def _load_transcriber(self) -> Transcriber:
        """Prepare the Whisper model once and report its configuration.

        A queue must not call this per video: whisper.cpp on Windows can
        fight over the mapped model file when a second context is created
        while - or right after - another one lived. Loading once keeps every
        queued video decodable.
        """
        trans = Transcriber(self.settings)

        with Spinner("Initialising Whisper model"):
            trans.load()

        self._set_status(f"Model: {paths.MODEL_NAME}")
        self._set_status(f"Load time: {human_time(trans.load_seconds)}")
        self._set_status(f"Compute: {trans.describe_compute()}")
        return trans

    def _transcribe_audio(self, trans: Transcriber, media: MediaInfo) -> str:
        """Decode one downloaded audio file with an already-loaded model."""
        blank()
        duration = media.duration
        pb = ProgressBar("Transcribing", icon=G.BRAIN)
        pb.start(detail="0:00 / --:--" if duration else "")

        def on_progress(fraction: float, detail: str) -> None:
            if duration:
                pb.update(fraction, detail=f"{human_time(duration * fraction)} / {human_time(duration)}")
            else:
                pb.update(fraction, detail="")

        text = trans.transcribe(
            media.audio_file, AUTO.code, duration_seconds=duration, on_progress=on_progress
        )
        pb.finish(detail="complete")
        self._detected_language = trans.detected_language
        return text

    def _save_step(self, media: MediaInfo, text: str) -> Path:
        blank()
        base = downloader.safe_filename(media.title, fallback="transcription")
        target = paths.OUTPUT_DIR / f"{base}.txt"
        counter = 1
        while target.exists() and counter < 100:
            target = paths.OUTPUT_DIR / f"{base} ({counter}).txt"
            counter += 1

        try:
            target.write_text(text, encoding="utf-8")
        except OSError as exc:
            raise TubeScriptError(
                f"Could not write the transcript: {exc}",
                f"Check the permissions of:\n  {paths.OUTPUT_DIR}",
            ) from exc

        self._set_status(f"Characters: {len(text):,}")
        self._set_status(f"Size: {human_bytes(target.stat().st_size)}")
        self._set_status(f"Paragraphs: {text.count(chr(10) * 2) + 1}")
        return target

    def _cleanup_step(self, media: MediaInfo) -> None:
        """Remove the temporary audio and report any file we could not delete."""
        problems = downloader.cleanup(media.audio_file)
        if problems:
            self._status.append("Temporary files left behind:")
            self._status.extend(f"  {problem}" for problem in problems)

    def _sweep_tmp(self) -> None:
        """Delete audio left behind by a crashed or force-closed run.

        Files younger than an hour are kept so a second TubeScript window that
        is still working is never disturbed.
        """
        try:
            removed = downloader.sweep(older_than_seconds=_STALE_TMP_AGE)
        except Exception:
            return
        if not removed:
            return
        names = ", ".join(p.name for p in removed[:3])
        extra = f" (+{len(removed) - 3} more)" if len(removed) > 3 else ""
        # Printed straight away rather than queued in _status, because the user
        # may cancel at the next prompt and never reach the summary.
        line(style(f"  {G.DOWN} Cleaned up {len(removed)} leftover file(s) in tmp/: {names}{extra}", C.FAINT))

    # -- settings ----------------------------------------------------------
    def _open_settings(self) -> None:
        self.settings = settings_screen.run(self.settings)
        try:
            config.save(self.settings)
            line(style(f"  {G.CHECK} Settings saved.", C.OK))
        except Exception as exc:
            line(style(f"  {G.CROSS} Could not save settings: {exc}", C.ERR))

    # -- run ---------------------------------------------------------------
    def run(self) -> int:
        try:
            self._fix_console()
            self._welcome()
            clear()  # page 2: the mode choice and the prompts
            self._sweep_tmp()
            self._print_notices()
            paths.set_model(self.settings.model)  # honour the persisted choice
            self._ensure_model()

            while True:
                mode = self._ask_mode()
                if mode is None:
                    return 0
                if mode == "CLOSE":
                    return 0
                if mode == MODE_MODELS:
                    self._run_models()
                    clear()
                    continue
                if mode == MODE_MULTI:
                    code = self._run_queue()
                else:
                    code = self._run_single()
                if code != BACK:
                    return code
                clear()  # ESC on the URL input: redraw the mode menu cleanly

        except KeyboardInterrupt:
            blank()
            line(f"  {style(G.CROSS, C.ERR)} Cancelled.")
            return 130
        except TubeScriptError as exc:
            self._print_error(exc)
            return 1
        except Exception as exc:  # last-resort guard: never dump a traceback
            blank()
            line(f"  {style(G.CROSS, C.ERR)} Unexpected error: {exc}")
            line(f"    {style(type(exc).__name__, C.FAINT)}")
            return 1

    def _ask_mode(self) -> str | None:
        """Offer a single transcription, a whole queue, or the model manager."""
        return ask_choice(
            "What would you like to transcribe?",
            [
                MenuItem("A single video", MODE_SINGLE, note="transcribe one URL"),
                MenuItem("A queue of videos", MODE_MULTI, note="paste several URLs"),
                MenuItem("", "", enabled=False),
                MenuItem("Manage models", MODE_MODELS, note="install or switch Whisper models"),
                MenuItem("", "", enabled=False),
                MenuItem("Close TubeScript", "CLOSE", note="exit the application"),
            ],
            visible=6,
            initial=0,
            cancellable=False,
        )

    def _run_single(self) -> int:
        url = self._ask_url()
        if url is None:
            # ESC on the interactive prompt backs out to the mode choice; on
            # a piped run an EOF is a clean finish, not a back-navigation.
            return BACK if keys.is_interactive() else 0

        try:
            canonical = downloader.normalise_url(url)
        except TubeScriptError as exc:
            self._print_error(exc)
            return self._after_run_error()

        clear()  # page 3: the summary, which stays up while we work
        if not self._confirm(canonical):
            blank()
            line(f"  {style('Cancelled before downloading.', C.MUTED)}")
            return 0

        try:
            media = self._download_step(canonical)
        except TubeScriptError as exc:
            self._print_error(exc)
            return self._after_run_error()

        try:
            trans = self._load_transcriber()
            text = self._transcribe_audio(trans, media)
            target = self._save_step(media, text)
        except TubeScriptError as exc:
            # Always drop the temporary audio, even on a model or decode error.
            self._cleanup_step(media)
            self._print_error(exc)
            return self._after_run_error()

        self._transcripts = [(media.display_title, target)]
        self._cleanup_step(media)
        clear()  # page 4: the result
        self._print_result(target, media)
        return 0

    def _ask_urls(self) -> list[str] | None:
        """Collect the queue: pastes are captured instantly, an Enter only to finish.

        Each paste becomes its own line with an arrow - ``\u276f url`` - and the
        input moves to a fresh arrow below, ready for the next link. Backspace
        removes the last link, ESC goes back, Enter finishes. ``None`` means the
        user backed out; an empty list means they finished with nothing.
        Without a real console the input falls back to plain lines.
        """
        header = (
            style("  Paste links one after another - one link per line.", C.TEXT),
            style("  Backspace removes the last link, Enter finishes.", C.FAINT),
            style("  ESC goes back.", C.FAINT),
        )
        urls: list[str] = []
        if keys.is_interactive() and msvcrt is not None:
            if self._capture_url_pastes(urls, header):
                return None
            return urls
        blank()
        for head in header:
            line(head)
        self._collect_url_lines(urls)
        return urls

    def _collect_url_lines(self, urls: list[str]) -> None:
        """Line-by-line fallback used when there is no interactive console."""
        blank()
        while True:
            try:
                raw = input(f"  {style(G.CURSOR, C.ACCENT)} ").strip()
            except EOFError:
                break
            if not raw:
                break
            urls.append(raw)

    def _capture_url_pastes(self, urls: list[str], header: tuple[str, ...] = ()) -> bool:
        """Capture pasted clips and ignore stray typing.

        A paste - with or without bracketed-paste markers - arrives as a quick
        flood of characters. The flood is accumulated, and as soon as a
        newline or a short pause marks its end, every line lands on its own
        arrow line. A lone typed letter is too short to count and is dropped.
        Backspace removes the last line, Enter pressed when idle finishes the
        queue, and a lone ESC backs out. Returns ``True`` when the user pressed
        ESC, ``False`` otherwise.
        """
        heading = tuple(header)

        def prompt() -> str:
            return f"  {style(G.CURSOR, C.ACCENT)} "

        def render() -> None:
            """Repaint the whole page from the top-left corner.

            Anchored on the absolute home position, nothing is ever moved up or
            down: the tips above the paste lines - and any line wrapped by a
            long URL - can never be overwritten or eaten while pasting or
            deleting.
            """
            sys.stdout.write("\x1b[H\x1b[J")
            for head in heading:
                sys.stdout.write(head + "\n")
            for url in urls:
                sys.stdout.write(f"{prompt()}{url}\n")
            sys.stdout.write(prompt())
            sys.stdout.flush()

        def tidy(raw: str) -> str:
            for marker in ("\x1b[200~", "\x1b[201~", "[200~", "[201~"):
                raw = raw.replace(marker, "")
            return raw

        def commit(raw: str) -> None:
            for url in (
                p.strip()
                for p in tidy(raw).replace("\r\n", "\n").replace("\r", "\n").split("\n")
                if p.strip()
            ):
                urls.append(url)
            render()

        sys.stdout.write("\x1b[?2004h")
        sys.stdout.flush()
        buf = ""
        last_at = time.monotonic()
        render()
        try:
            while True:
                if not msvcrt.kbhit():
                    if buf and time.monotonic() - last_at >= _PASTE_GAP:
                        if len(tidy(buf)) >= _PASTE_MIN:
                            commit(buf)
                        buf = ""  # too short to be a paste: a stray key press
                    time.sleep(0.01)
                    continue
                ch = msvcrt.getwch()
                if ch == "\x03":
                    raise KeyboardInterrupt
                if ch in ("\x00", "\xe0"):  # extended keys, e.g. arrows
                    try:
                        msvcrt.getwch()
                    except Exception:
                        pass
                    continue
                now = time.monotonic()
                if ch == "\x1b":
                    seq = ch
                    deadline = time.monotonic() + _ESC_GAP
                    while time.monotonic() < deadline and msvcrt.kbhit():
                        nxt = msvcrt.getwch()
                        seq += nxt
                        if nxt.isalpha() or nxt == "~":  # sequence or paste marker
                            break
                    if seq == "\x1b":  # lone ESC pressed when idle: go back
                        return True
                    continue  # a pasted escape sequence or marker: swallow it
                if ch in ("\b", "\x7f"):  # Backspace: drop the last link line
                    if urls:
                        urls.pop()
                        render()
                    buf = ""
                    last_at = now
                    continue
                if ch in ("\r", "\n"):
                    cleaned = tidy(buf)
                    if cleaned and len(cleaned) >= _PASTE_MIN:
                        commit(buf)  # a pasted line, with or without a newline
                    elif cleaned:
                        return False  # a short typed reply on one line: called done
                    elif now - last_at > _PASTE_GAP:
                        return False  # an idle Enter: the queue is complete
                    buf = ""
                elif ch != "\x1b":
                    buf += ch
                last_at = now
        finally:
            sys.stdout.write("\x1b[?2004l")
            sys.stdout.flush()

    def _confirm_queue(self, urls: list[str]) -> bool:
        """Show the queued videos and ask for the go-ahead."""
        blank()
        line(f"  {style('Ready to transcribe', C.ACCENT, '1')}  "
             f"{style(f'{len(urls)} videos', C.ACCENT)}")
        blank()
        for position, url in enumerate(urls, 1):
            line(f"  {position:>2}. {url}")
        blank()
        line(f"      Model: {paths.MODEL_NAME}")
        blank()
        return ask_yes_no("Start the transcription?", default=True)

    def _run_queue(self) -> int:
        urls = self._ask_urls()
        if urls is None:  # ESC pressed: back to the mode choice
            return BACK
        if not urls:
            return 0

        clear()  # page 3: the queue summary, which stays up while we work
        if not self._confirm_queue(urls):
            blank()
            line(f"  {style('Cancelled before downloading.', C.MUTED)}")
            return 0

        # One model instance for the whole queue. Re-loading it per video was
        # both slow and the cause of the second (and later) videos never being
        # transcribed on Windows.
        try:
            trans = self._load_transcriber()
        except TubeScriptError as exc:
            self._print_error(exc)
            return self._after_run_error()

        results: list[tuple[bool, str, object]] = []
        for position, url in enumerate(urls, 1):
            media = None
            label = url
            try:
                canonical = downloader.normalise_url(url)
                line(f"  {style(f'[{position}/{len(urls)}]', C.FAINT)} {style(canonical, C.TEXT)}")
                media = self._download_step(canonical)
                label = media.display_title
                text = self._transcribe_audio(trans, media)
                target = self._save_step(media, text)
                self._transcripts.append((media.display_title, target))
                results.append((True, media.display_title, target))
            except Exception as exc:  # one bad video must not stall the queue
                results.append((False, label, getattr(exc, "message", str(exc))))
            finally:
                if media is not None:
                    self._cleanup_step(media)

        clear()  # page 4: the queue results
        self._print_queue_result(results)
        return 0

    def _print_queue_result(self, results: list[tuple[bool, str, object]]) -> None:
        blank()
        rule(min(60, term_width() - 4))
        saved = sum(1 for ok, _, _ in results if ok)
        line(f"  {style(G.CHECK, C.OK)} {style('Transcription completed', C.OK, '1')}  "
             f"{style(f'{saved}/{len(results)} saved', C.OK)}")
        blank()
        for ok, label, detail in results:
            if ok:
                line(f"  {style(G.CHECK, C.OK)} {style(label, C.TEXT)}")
                line(f"    {style(str(detail), C.FAINT)}")
            else:
                line(f"  {style(G.CROSS, C.ERR)} {style(label, C.ERR)}")
                line(f"    {style(str(detail), C.FAINT)}")
        blank()
        line(f"  {style('Find your transcripts in', C.DIM)}  {style(str(paths.OUTPUT_DIR), C.ACCENT)}")
        blank()

    def _fix_console(self) -> None:
        """Enable ANSI processing on the Windows console."""
        try:
            import colorama

            colorama.just_fix_windows_console()
        except Exception:
            pass

    def _print_notices(self) -> None:
        """Surface missing dependencies up front instead of mid-run."""
        missing: list[str] = []
        for mod in ("colorama", "yt_dlp", "numpy", "tqdm", "platformdirs", "pywhispercpp"):
            try:
                __import__(mod)
            except Exception:
                missing.append(mod)
        if missing:
            raise TubeScriptError(
                "Some Python dependencies are missing: " + ", ".join(missing),
                "Install them with:\n  pip install -r requirements.txt\n\n"
                "Official links:\n"
                "  colorama: https://pypi.org/project/colorama/\n"
                "  yt-dlp: https://pypi.org/project/yt-dlp/\n"
                "  numpy: https://pypi.org/project/numpy/\n"
                "  tqdm: https://pypi.org/project/tqdm/\n"
                "  platformdirs: https://pypi.org/project/platformdirs/\n"
                "  pywhispercpp: https://pypi.org/project/pywhispercpp/",
            )
        if shutil.which("ffmpeg") is None:
            warn("ffmpeg was not found - audio conversion will fail.")
            hint("Download FFmpeg: https://ffmpeg.org/download.html\n"
                 "Quick install (Windows): winget install Gyan.FFmpeg")

    def _ensure_model(self) -> None:
        """Plug-and-play: make sure a verified Whisper model is ready.

        * configured model present   -> verify it (size + SHA-256 pin);
        * some other model exists    -> adopt it, then verify;
        * ``models/`` completely empty -> show the picker, download, verify.
        """
        target = paths.model_path()
        if not target.is_file():
            existing = sorted(paths.MODELS_DIR.glob("*.bin"))
            if existing:
                self._adopt_model(existing[0])
            else:
                self._pick_model()
            target = paths.model_path()
        self._verify_model(target)

    def _verify_model(self, target: Path) -> None:
        """Refuse to run an unverifiable or tampered model.

        Catalogue models are pinned: the file must match the exact size and
        SHA-256 from the catalogue. Unknown (hand-dropped) files only need to
        actually *be* a binary model, not an HTML/text page renamed to ``.bin``.
        """
        option = model_catalog.lookup(target.stem)
        if option is not None:
            actual_size = target.stat().st_size
            if actual_size != option.size_bytes:
                self._bad_model(target, f"size {actual_size} != expected {option.size_bytes}")
            digest = fetch.hexdigest(target)
            if digest != option.sha256:
                self._bad_model(target, f"SHA-256 {digest} != pinned {option.sha256}")
        else:
            reason = fetch.validate_model(target)
            if reason:
                self._bad_model(target, reason)

    def _bad_model(self, target: Path, reason: str) -> None:
        raise TubeScriptError(
            "Whisper model integrity check failed - refusing to load it.",
            f"{target}\n{reason}\n"
            f"delete the file and relaunch: TubeScript will redownload it cleanly "
            f"(or drop a fresh .bin into {paths.MODELS_DIR}).",
        )

    def _adopt_model(self, model_file: Path) -> None:
        """Reuse whichever model is already in ``models/``."""
        paths.set_model(model_file.stem)
        if self.settings.model != paths.MODEL_NAME:
            self.settings.model = paths.MODEL_NAME
            config.save(self.settings)
        self._set_status(f"Model: {paths.MODEL_NAME}")

    def _pick_model(self) -> None:
        """First launch: let the user choose the model to download."""
        items = [
            MenuItem(option.name, option.name, note=f"{option.size} - {option.hardware}")
            for option in model_catalog.OPTIONS
        ]
        choice = ask_choice(
            "No Whisper model found - which one do you want to download?",
            items,
            visible=len(items),
            initial=0,
            cancellable=False,
        )
        paths.set_model(str(choice))
        self.settings.model = str(choice)
        config.save(self.settings)
        self._download_model()

    def _download_model(self) -> None:
        """Download the selected model (with resume support) into ``models/``."""
        target = paths.model_path()
        line(f"  {style(G.DOWNLOAD, C.ACCENT)} "
             f"{style('Downloading Whisper model.', C.TEXT)}")
        line(f"    {style(str(target), C.FAINT)}")
        blank()
        pb = ProgressBar(f"Downloading {target.name}", icon=G.DOWNLOAD)
        pb.start(detail="connecting...")
        option = model_catalog.lookup(paths.MODEL_NAME)
        pins = {
            "expected_size": option.size_bytes if option else None,
            "expected_sha256": option.sha256 if option else None,
        }
        try:
            size = fetch.download(paths.MODEL_URL, target, on_progress=pb.update, **pins)
        except fetch.ChecksumError as exc:
            pb.stop()
            raise TubeScriptError(
                f"Model download rejected: {exc}",
                "The unusable file was removed. Relaunch to download the model again "
                "cleanly (or fetch it manually and drop the .bin into models/).",
            ) from exc
        except Exception as exc:
            pb.stop()
            raise TubeScriptError(
                f"Could not download the Whisper model: {exc}",
                "The partial download is kept and resumed on the next launch.\n"
                f"Offline? Fetch it manually:\n  {paths.MODEL_URL}\n"
                f"and place it in:\n  {paths.MODELS_DIR}",
            ) from exc
        pb.finish(detail=f"{human_bytes(size)} downloaded")
        self._set_status(f"Model: {paths.MODEL_NAME} (downloaded)")

    # -- model manager -----------------------------------------------------
    def _installed_models(self) -> list[Path]:
        """Every GGML model file present in ``models/``."""
        return sorted(paths.MODELS_DIR.glob("*.bin"))

    def _run_models(self) -> None:
        """Manage Whisper models: install a new one or switch the active one."""
        while True:
            choice = ask_choice(
                f"Models - in use: {paths.MODEL_NAME}",
                [
                    MenuItem(MODELS_SWITCH, MODELS_SWITCH,
                             note="pick another installed model"),
                    MenuItem(MODELS_INSTALL, MODELS_INSTALL,
                             note="download a new one from the catalogue"),
                    MenuItem(MODELS_UNINSTALL, MODELS_UNINSTALL,
                             note="delete installed models"),
                    MenuItem(MODELS_BACK, MODELS_BACK,
                             note="return to the main menu"),
                ],
                visible=5,
                initial=0,
                cancellable=True,
            )
            if choice is None or choice == MODELS_BACK:
                return
            if choice == MODELS_SWITCH:
                self._switch_model()
            elif choice == MODELS_INSTALL:
                self._install_model()
            else:
                self._uninstall_model()

    def _switch_model(self) -> None:
        """Mark one of the installed models as the one TubeScript uses."""
        installed = self._installed_models()
        if not installed:
            line(f"  {style('No models installed.', C.WARN)}")
            return
        active = paths.MODEL_NAME
        items = [
            MenuItem(
                model_file.stem,
                model_file.stem,
                note="in use" if model_file.stem == active else "installed",
            )
            for model_file in installed
        ]
        try:
            initial = [f.stem for f in installed].index(active)
        except ValueError:
            initial = 0
        choice = ask_choice(
            "Which model should TubeScript use?",
            items,
            visible=max(4, len(items)),
            initial=initial,
            cancellable=True,
        )
        if choice is None or choice == active:
            return
        paths.set_model(str(choice))
        self.settings.model = str(choice)
        config.save(self.settings)
        self._set_status(f"Model: {paths.MODEL_NAME}")
        line(f"  {style(G.CHECK, C.OK)} {style(f'Now using {paths.MODEL_NAME}.', C.OK)}")

    def _uninstall_model(self) -> None:
        """Delete one or more installed models."""
        installed = self._installed_models()
        if not installed:
            line(f"  {style('No models installed.', C.WARN)}")
            return
        active = paths.MODEL_NAME
        items = [
            MenuItem(
                model_file.stem,
                model_file.stem,
                note="(in use) cannot uninstall" if model_file.stem == active else "installed",
                enabled=model_file.stem != active,
            )
            for model_file in installed
        ]
        if not any(item.enabled for item in items):
            line(f"  {style(f'{active}.bin is in use and cannot be uninstalled.', C.WARN)}")
            return
        choice = ask_choice(
            "Which model do you want to uninstall?",
            items,
            visible=max(4, len(items)),
            initial=0,
            cancellable=True,
        )
        if choice is None:
            return
        target = paths.MODELS_DIR / f"{choice}.bin"
        try:
            if target.exists():
                target.unlink()
        except Exception as exc:
            line(f"  {style(f'Could not delete {target.name}: {exc}', C.ERR)}")
            return
        line(f"  {style(G.CROSS, C.WARN)} {style(f'Removed {target.name}.', C.TEXT)}")
        if paths.MODEL_NAME == choice:
            # safety: should not happen as in-use is disabled
            paths.set_model(model_catalog.DEFAULT)

    def _install_model(self) -> None:
        """Download another catalogue model, skipping the ones already there."""
        installed = {f.stem for f in self._installed_models()}
        items = [
            MenuItem(
                option.name,
                option.name,
                note=f"{option.size} - {option.hardware}"
                     + ("   [already installed]" if option.name in installed else ""),
                enabled=option.name not in installed,
            )
            for option in model_catalog.OPTIONS
        ]
        if not any(item.enabled for item in items):
            line(f"  {style('Every catalogue model is already installed.', C.WARN)}")
            return
        choice = ask_choice(
            "Install a Whisper model",
            items,
            visible=len(items),
            initial=0,
            cancellable=True,
        )
        if choice is None:
            return
        paths.set_model(str(choice))
        self.settings.model = str(choice)
        config.save(self.settings)
        self._download_model()

    def _print_result(self, target: Path, media: MediaInfo) -> None:
        blank()
        rule(min(60, term_width() - 4))
        line(f"  {style(G.CHECK, C.OK)} {style('Transcription completed', C.OK, '1')}")
        blank()
        rows = [
            ("Output", str(target)),
            ("Title", media.display_title),
            ("Language", self._language_report()),
        ]
        line(kv_block(rows))
        for entry in self._status:
            line(f"  {style(G.BULLET, C.FAINT)} {style(entry, C.MUTED)}")
        blank()
        line(f"  {style('Find your transcript in', C.DIM)}  {style(str(target), C.ACCENT)}")
        blank()

    def _short_title(self, title: str, limit: int = _TITLE_LIMIT) -> str:
        """A menu label for a video title: kept short, ended with an ellipsis."""
        title = (title or "").strip()
        if len(title) <= limit:
            return title
        return title[:limit] + G.ELLIPSIS

    def _pick_transcript(self) -> Path | None:
        """Let the user choose which saved transcript to open.

        A single transcript is opened straight away; a queue offers a menu of
        the video titles (truncated with an ellipsis). ``None`` means the user
        cancelled the picker.
        """
        if len(self._transcripts) == 1:
            return self._transcripts[0][1]
        items = [
            MenuItem(self._short_title(title), str(position))
            for position, (title, _) in enumerate(self._transcripts, start=1)
        ]
        choice = ask_choice(
            "Which transcript to open?",
            items,
            visible=min(len(items), 12),
            initial=0,
            cancellable=True,
        )
        if choice is None:
            return None
        return self._transcripts[int(choice) - 1][1]

    def _open_transcript(self) -> None:
        """Open a saved transcript with the system's default handler."""
        if not self._transcripts:
            warn("No transcript is available to open.")
            return
        target = self._pick_transcript()
        if target is None:
            return  # picker cancelled: back to the end-of-run menu
        if not target.is_file():
            warn("The transcript file is missing.")
            return
        opener = getattr(os, "startfile", None)
        if opener is None:
            warn("Opening files is not supported on this platform.")
            return
        try:
            opener(str(target))
            line(style(f"  {G.CHECK} Opened: {target}", C.OK))
        except OSError as exc:
            warn(f"Could not open the transcript: {exc}")

    def ask_next(self) -> bool:
        """Offer to open the transcript, start again, or close the app.

        Returns ``True`` to go back to the home screen, ``False`` to close.
        "Open transcript" opens the saved file and then re-shows the menu, so
        it never returns. The menu is driven with the arrow keys and Enter, so
        the launcher no longer needs its own "press any key" prompt.
        """
        while True:
            clear()  # page 5: the end-of-run menu
            has_transcript = bool(self._transcripts)
            if not has_transcript:
                open_note = "no transcript saved"
            elif len(self._transcripts) == 1:
                open_note = "open the saved .txt file"
            else:
                open_note = f"pick one of {len(self._transcripts)} transcripts"
            items = [
                MenuItem(
                    "Open transcript",
                    NEXT_OPEN,
                    note=open_note,
                    enabled=has_transcript,
                ),
                MenuItem("Back to the home screen", NEXT_HOME, note="transcribe another video"),
                MenuItem("Close TubeScript", NEXT_EXIT, note="quit"),
            ]
            choice = ask_choice(
                "What would you like to do?",
                items,
                visible=4,
                initial=0,
                cancellable=False,
            )
            if choice == NEXT_OPEN:
                self._open_transcript()
                continue
            return choice == NEXT_HOME


def main() -> int:
    """Run the app, letting the user chain runs from the end-of-run menu."""
    while True:
        app = App()
        code = app.run()
        if code != 0:
            # Cancelled with Ctrl+C, or a real error: the launcher shows it.
            return code
        if not app.ask_next():
            return 0
        # "Back to the home screen": loop round for a fresh App, which also
        # re-reads config.json in case /settings changed the compute profile.


if __name__ == "__main__":
    sys.exit(main())
