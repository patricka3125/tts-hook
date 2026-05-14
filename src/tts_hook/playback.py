"""Host audio playback helpers for generated speech files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import os
import shutil
import signal
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


@dataclass(frozen=True)
class PlaybackProcessResult:
    """Success or failure details for a process-group playback launch."""

    ok: bool
    command: tuple[str, ...] = ()
    process: subprocess.Popen[bytes] | None = None
    error: str | None = None

    @property
    def pid(self) -> int | None:
        """Return the child PID when playback was launched."""

        return None if self.process is None else self.process.pid


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


def build_playback_command(
    wav_path: Path,
    *,
    player: str = "auto",
    path_env: str | None = None,
) -> tuple[str, ...] | None:
    """Return the full audio playback command for ``wav_path``."""

    command_prefix = choose_player_command(player, path_env=path_env)
    if command_prefix is None:
        return None
    return (*command_prefix, str(wav_path))


def launch_process_group(command: Sequence[str]) -> subprocess.Popen[bytes]:
    """Launch ``command`` in a new process group with child output suppressed."""

    return subprocess.Popen(  # noqa: S603
        tuple(command),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def launch_audio_player_process(
    wav_path: Path,
    *,
    player: str = "auto",
    path_env: str | None = None,
) -> PlaybackProcessResult:
    """Start host playback for a WAV file in its own process group."""

    command = build_playback_command(wav_path, player=player, path_env=path_env)
    if command is None:
        return PlaybackProcessResult(ok=False, error=f"No playback command found for player={player!r}")

    try:
        process = launch_process_group(command)
    except OSError as exc:
        return PlaybackProcessResult(ok=False, command=command, error=str(exc))

    return PlaybackProcessResult(ok=True, command=command, process=process)


def terminate_process_group(process: subprocess.Popen[bytes], *, timeout_seconds: float = 0.5) -> bool:
    """Terminate a playback process group, escalating to SIGKILL after timeout.

    Returns ``True`` when the process had already exited or stopped after
    SIGTERM, and ``False`` when SIGKILL escalation was needed.
    """

    if process.poll() is not None:
        return True

    try:
        process_group_id = os.getpgid(process.pid)
    except ProcessLookupError:
        return True

    try:
        os.killpg(process_group_id, signal.SIGTERM)
    except ProcessLookupError:
        return True

    try:
        process.wait(timeout=timeout_seconds)
        return True
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process_group_id, signal.SIGKILL)
        except ProcessLookupError:
            return False
        process.wait()
        return False


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

    command = build_playback_command(wav_path, player=player, path_env=path_env)
    if command is None:
        return PlaybackResult(ok=False, error=f"No playback command found for player={player!r}")

    try:
        process = (
            subprocess.Popen(  # noqa: S603
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=False,
            )
            if blocking
            else launch_process_group(command)
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
