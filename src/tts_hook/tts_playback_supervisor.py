#!/usr/bin/env python3
"""Standalone playback supervisor entrypoint for generated TTS WAV files."""

from __future__ import annotations

from argparse import ArgumentParser, Namespace
from pathlib import Path
import sys

import _bootstrap

_bootstrap.ensure_src_on_path()

from tts_hook.playback import launch_audio_player_process  # noqa: E402


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
    """Validate CLI arguments and launch playback in a supervised process group."""

    args = build_parser().parse_args(argv)
    return run(args)


def run(args: Namespace) -> int:
    """Launch playback for parsed supervisor arguments."""

    wav_path = args.wav_path
    if not wav_path.is_file():
        _write_stderr(f"WAV file does not exist: {wav_path}")
        return 2

    playback = launch_audio_player_process(wav_path, player=args.player)
    if not playback.ok:
        _write_stderr(playback.error or "Playback did not start.")
        return 1

    return 0


def _write_stderr(message: str) -> None:
    try:
        sys.stderr.write(message + "\n")
        sys.stderr.flush()
    except OSError:
        return


if __name__ == "__main__":
    raise SystemExit(main())
