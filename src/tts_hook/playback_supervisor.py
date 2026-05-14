"""Long-lived playback process that owns temporary WAV cleanup."""

from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path
from typing import Sequence, TextIO
import sys

from .playback import command_display, launch_audio_player_process


def run_playback_supervisor(
    wav_path: Path,
    *,
    player: str = "auto",
    stderr: TextIO | None = None,
    log_path: Path | None = None,
) -> int:
    """Play a WAV file and remove it after the player exits."""

    stream = stderr or sys.stderr
    launched = launch_audio_player_process(wav_path, player=player)
    try:
        if not launched.ok or launched.process is None:
            _write_diagnostic(
                stream,
                f"Playback did not start; cleaning up WAV. {launched.error or 'Unknown playback error.'}",
                log_path=log_path,
            )
            return 1

        return_code = launched.process.wait()
        if return_code != 0:
            _write_diagnostic(stream, f"Playback exited {return_code}: {command_display(launched.command)}", log_path=log_path)
            return return_code
        return 0
    finally:
        _cleanup_wav(wav_path, stream, log_path=log_path)


def main(argv: Sequence[str] | None = None, *, stderr: TextIO | None = None) -> int:
    """Console entrypoint for supervised playback."""

    parser = ArgumentParser(description="Play a generated TTS WAV and remove it after playback.")
    parser.add_argument("wav_path", type=Path)
    parser.add_argument("--player", default="auto")
    parser.add_argument("--log-path", type=Path)
    args = parser.parse_args(argv)
    return run_playback_supervisor(args.wav_path, player=args.player, stderr=stderr, log_path=args.log_path)


def cli() -> int:
    """Console-script entrypoint."""

    return main()


def _cleanup_wav(wav_path: Path, stderr: TextIO, *, log_path: Path | None = None) -> None:
    try:
        wav_path.unlink(missing_ok=True)
    except OSError as exc:
        _write_diagnostic(stderr, f"Could not remove temporary WAV {wav_path}: {exc}", log_path=log_path)


def _write_diagnostic(stderr: TextIO, message: str, *, log_path: Path | None = None) -> None:
    if log_path is not None:
        try:
            expanded = log_path.expanduser()
            expanded.parent.mkdir(parents=True, exist_ok=True)
            with expanded.open("a", encoding="utf-8") as handle:
                handle.write(message + "\n")
        except OSError:
            pass
    _write_stderr(stderr, message)


def _write_stderr(stderr: TextIO, message: str) -> None:
    try:
        stderr.write(message + "\n")
        stderr.flush()
    except OSError:
        return


if __name__ == "__main__":
    raise SystemExit(cli())
