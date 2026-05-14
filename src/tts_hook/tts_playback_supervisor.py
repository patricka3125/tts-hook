#!/usr/bin/env python3
"""Standalone playback supervisor entrypoint for generated TTS WAV files."""

from __future__ import annotations

from argparse import ArgumentParser, Namespace
from pathlib import Path
from types import FrameType
from typing import BinaryIO, TextIO
import select
import signal
import sys
import termios
import tty

import _bootstrap

_bootstrap.ensure_src_on_path()

from tts_hook.playback import launch_audio_player_process, terminate_process_group  # noqa: E402

ESCAPE = b"\x1b"
POLL_INTERVAL_SECONDS = 0.05

_active_supervisor: "PlaybackSupervisor | None" = None


def build_parser() -> ArgumentParser:
    """Create the command-line parser for the playback supervisor."""

    parser = ArgumentParser(description="Play a generated TTS WAV file under a playback supervisor.")
    parser.add_argument("wav_path", type=Path, help="Path to the generated WAV file to play.")
    parser.add_argument(
        "--player",
        default="auto",
        help="Playback command to use, or 'auto' to select the first available supported player.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Validate CLI arguments and run supervised playback."""

    args = build_parser().parse_args(argv)
    return run(args)


def run(args: Namespace) -> int:
    """Run supervised playback for parsed supervisor arguments."""

    return supervise_playback(args.wav_path, player=args.player)


class TtyEscapeReader:
    """Read Escape key presses from a controlling terminal in cbreak mode."""

    def __init__(
        self,
        *,
        tty_path: str = "/dev/tty",
        opener=open,
        select_fn=select.select,
        termios_module=termios,
        tty_module=tty,
    ) -> None:
        self._tty_path = tty_path
        self._opener = opener
        self._select = select_fn
        self._termios = termios_module
        self._tty = tty_module
        self._stream: BinaryIO | None = None
        self._original_attrs: object | None = None

    def __enter__(self) -> "TtyEscapeReader":
        self._stream = self._opener(self._tty_path, "rb", buffering=0)
        fd = self._stream.fileno()
        self._original_attrs = self._termios.tcgetattr(fd)
        self._tty.setcbreak(fd)
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def close(self) -> None:
        """Restore terminal settings and close the terminal stream."""

        stream = self._stream
        if stream is None:
            return

        try:
            if self._original_attrs is not None:
                self._termios.tcsetattr(stream.fileno(), self._termios.TCSADRAIN, self._original_attrs)
        finally:
            self._stream = None
            stream.close()

    def escape_pressed(self, timeout_seconds: float) -> bool:
        """Return ``True`` if Escape is available on the controlling terminal."""

        if self._stream is None:
            return False

        ready, _writable, _errors = self._select([self._stream], [], [], timeout_seconds)
        if not ready:
            return False
        return self._stream.read(1) == ESCAPE


class PlaybackSupervisor:
    """Own one playback process, optional Escape reader, and temp WAV cleanup."""

    def __init__(self, wav_path: Path, *, player: str = "auto", stderr: TextIO | None = None) -> None:
        self.wav_path = wav_path
        self.player = player
        self.stderr = stderr or sys.stderr
        self.process = None
        self._cancel_requested = False

    def run(self) -> int:
        """Run supervised playback until completion or Escape cancellation."""

        if not self.wav_path.is_file():
            _write_stderr(f"WAV file does not exist: {self.wav_path}", stderr=self.stderr)
            return 2

        global _active_supervisor
        _active_supervisor = self
        try:
            return self._run_started_playback()
        finally:
            _active_supervisor = None
            self._cleanup_wav()

    def request_cancel(self) -> None:
        """Request cancellation of the active playback process."""

        self._cancel_requested = True
        if self.process is not None:
            terminate_process_group(self.process)

    def _run_started_playback(self) -> int:
        playback = launch_audio_player_process(self.wav_path, player=self.player)
        if not playback.ok:
            _write_stderr(playback.error or "Playback did not start.", stderr=self.stderr)
            return 1
        if playback.process is None:
            _write_stderr("Playback did not return a process handle.", stderr=self.stderr)
            return 1

        self.process = playback.process
        reader = open_tty_escape_reader(stderr=self.stderr)
        try:
            self._wait_for_playback(reader)
        finally:
            if reader is not None:
                reader.close()
        return 0

    def _wait_for_playback(self, reader: TtyEscapeReader | None) -> None:
        if self.process is None:
            return

        while self.process.poll() is None:
            if self._cancel_requested:
                return
            if reader is None:
                self.process.wait()
                return
            try:
                if reader.escape_pressed(POLL_INTERVAL_SECONDS):
                    self.request_cancel()
                    return
            except (OSError, select.error) as exc:
                _write_stderr(f"Disabling Escape cancel support: {exc}", stderr=self.stderr)
                reader.close()
                reader = None

    def _cleanup_wav(self) -> None:
        try:
            self.wav_path.unlink(missing_ok=True)
        except OSError as exc:
            _write_stderr(f"Could not delete temporary WAV file {self.wav_path}: {exc}", stderr=self.stderr)


def supervise_playback(wav_path: Path, *, player: str = "auto", stderr: TextIO | None = None) -> int:
    """Run a playback supervisor for one generated WAV file."""

    install_signal_handlers()
    return PlaybackSupervisor(wav_path, player=player, stderr=stderr).run()


def open_tty_escape_reader(*, stderr: TextIO | None = None) -> TtyEscapeReader | None:
    """Best-effort open of `/dev/tty` for Escape cancellation."""

    reader = TtyEscapeReader()
    try:
        return reader.__enter__()
    except (OSError, termios.error) as exc:
        _write_stderr(f"Escape cancel unavailable: {exc}", stderr=stderr)
        reader.close()
        return None


def install_signal_handlers() -> None:
    """Install best-effort cleanup handlers for supervisor termination."""

    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, _handle_termination_signal)


def _handle_termination_signal(signum: int, _frame: FrameType | None) -> None:
    if _active_supervisor is not None:
        _active_supervisor.request_cancel()
        _active_supervisor._cleanup_wav()
    raise SystemExit(128 + signum)


def _write_stderr(message: str, *, stderr: TextIO | None = None) -> None:
    stream = stderr or sys.stderr
    try:
        stream.write(message + "\n")
        stream.flush()
    except OSError:
        return


if __name__ == "__main__":
    raise SystemExit(main())
