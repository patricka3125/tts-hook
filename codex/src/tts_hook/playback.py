"""Host audio playback helpers for generated speech files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import os
import shutil
import subprocess

AUTO_PLAYERS: tuple[tuple[str, ...], ...] = (
    ("pw-play",),
    ("paplay",),
    ("ffplay", "-nodisp", "-autoexit"),
    ("aplay",),
)


@dataclass(frozen=True)
class PlaybackResult:
    """Success or failure details for a playback launch."""

    ok: bool
    command: tuple[str, ...] = ()
    pid: int | None = None
    error: str | None = None


def choose_player_command(player: str, *, path_env: str | None = None) -> tuple[str, ...] | None:
    """Return the configured playback command, or the first available auto player."""

    if player == "auto":
        for candidate in AUTO_PLAYERS:
            executable = shutil.which(candidate[0], path=path_env)
            if executable:
                return (executable, *candidate[1:])
        return None

    configured = tuple(part for part in player.split() if part)
    if not configured:
        return None

    executable = shutil.which(configured[0], path=path_env)
    if executable:
        return (executable, *configured[1:])
    if os.path.isabs(configured[0]) and Path(configured[0]).exists():
        return configured
    return None


def play_audio_file(
    wav_path: Path,
    *,
    player: str = "auto",
    blocking: bool = False,
    path_env: str | None = None,
) -> PlaybackResult:
    """Start host playback for a WAV file.

    Background playback suppresses child stdout/stderr so hook stdout remains
    reserved for Codex hook JSON.
    """

    command_prefix = choose_player_command(player, path_env=path_env)
    if command_prefix is None:
        return PlaybackResult(ok=False, error=f"No playback command found for player={player!r}")

    command = (*command_prefix, str(wav_path))
    try:
        process = subprocess.Popen(  # noqa: S603
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=not blocking,
        )
    except OSError as exc:
        return PlaybackResult(ok=False, command=command, error=str(exc))

    if blocking:
        return_code = process.wait()
        if return_code != 0:
            return PlaybackResult(ok=False, command=command, pid=process.pid, error=f"Playback exited {return_code}")

    return PlaybackResult(ok=True, command=command, pid=process.pid)


def command_display(command: Sequence[str]) -> str:
    """Return a concise command string for logs."""

    return " ".join(command)

