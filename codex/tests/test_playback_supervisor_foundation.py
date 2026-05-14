from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence
import signal
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from tts_hook import playback as playback_module  # noqa: E402
from tts_hook.playback import (  # noqa: E402
    build_playback_command,
    launch_audio_player_process,
    launch_process_group,
    play_audio_file,
    terminate_process_group,
)


class CapturingPopen:
    calls: list[dict[str, Any]] = []

    def __init__(self, command: Sequence[str], **kwargs: Any) -> None:
        self.command = tuple(command)
        self.kwargs = kwargs
        self.pid = 12345
        self.returncode = None
        CapturingPopen.calls.append({"command": self.command, "kwargs": kwargs})

    def wait(self, timeout: float | None = None) -> int:
        self.returncode = 0
        return 0


class FakeProcess:
    def __init__(self, *, pid: int = 222, already_exited: bool = False, timeout: bool = False) -> None:
        self.pid = pid
        self._already_exited = already_exited
        self._timeout = timeout
        self.wait_calls = 0

    def poll(self) -> int | None:
        return 0 if self._already_exited else None

    def wait(self, timeout: float | None = None) -> int:
        self.wait_calls += 1
        if self._timeout and timeout is not None:
            raise subprocess.TimeoutExpired(["player"], timeout)
        return 0


def test_build_playback_command_reuses_auto_player_selection(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    ffplay = bin_dir / "ffplay"
    ffplay.write_text("#!/bin/sh\n", encoding="utf-8")
    ffplay.chmod(0o755)
    wav = tmp_path / "audio.wav"

    command = build_playback_command(wav, player="auto", path_env=str(bin_dir))

    assert command == (str(ffplay), "-nodisp", "-autoexit", str(wav))


def test_play_audio_file_and_supervisor_launch_use_same_command_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wav = tmp_path / "audio.wav"
    wav.write_bytes(b"RIFF")
    seen: list[tuple[Path, str, str | None]] = []

    def fake_build(wav_path: Path, *, player: str = "auto", path_env: str | None = None) -> tuple[str, ...]:
        seen.append((wav_path, player, path_env))
        return ("/bin/echo", str(wav_path))

    monkeypatch.setattr(playback_module, "build_playback_command", fake_build)
    monkeypatch.setattr(playback_module, "launch_process_group", lambda command: CapturingPopen(command))
    CapturingPopen.calls.clear()

    direct = play_audio_file(wav, player="auto", blocking=False, path_env="/tmp/bin")
    supervisor = launch_audio_player_process(wav, player="auto", path_env="/tmp/bin")

    assert direct.ok is True
    assert supervisor.ok is True
    assert seen == [(wav, "auto", "/tmp/bin"), (wav, "auto", "/tmp/bin")]
    assert CapturingPopen.calls[0]["command"] == CapturingPopen.calls[1]["command"]


def test_launch_process_group_suppresses_output_and_starts_new_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subprocess, "Popen", CapturingPopen)
    CapturingPopen.calls.clear()

    process = launch_process_group(("/bin/echo", "audio.wav"))

    assert process.pid == 12345
    assert CapturingPopen.calls == [
        {
            "command": ("/bin/echo", "audio.wav"),
            "kwargs": {
                "stdin": subprocess.DEVNULL,
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
                "start_new_session": True,
            },
        }
    ]


def test_terminate_process_group_returns_when_process_already_exited(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[int, signal.Signals]] = []
    monkeypatch.setattr(playback_module.os, "killpg", lambda pgid, sig: calls.append((pgid, sig)))

    graceful = terminate_process_group(FakeProcess(already_exited=True))

    assert graceful is True
    assert calls == []


def test_terminate_process_group_sends_sigterm_and_waits(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[int, signal.Signals]] = []
    monkeypatch.setattr(playback_module.os, "getpgid", lambda pid: 777)
    monkeypatch.setattr(playback_module.os, "killpg", lambda pgid, sig: calls.append((pgid, sig)))
    process = FakeProcess()

    graceful = terminate_process_group(process, timeout_seconds=0.1)

    assert graceful is True
    assert process.wait_calls == 1
    assert calls == [(777, signal.SIGTERM)]


def test_terminate_process_group_escalates_to_sigkill_after_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[int, signal.Signals]] = []
    monkeypatch.setattr(playback_module.os, "getpgid", lambda pid: 888)
    monkeypatch.setattr(playback_module.os, "killpg", lambda pgid, sig: calls.append((pgid, sig)))
    process = FakeProcess(timeout=True)

    graceful = terminate_process_group(process, timeout_seconds=0.1)

    assert graceful is False
    assert process.wait_calls == 2
    assert calls == [(888, signal.SIGTERM), (888, signal.SIGKILL)]


def test_supervisor_entrypoint_help_imports_tts_hook_modules() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "tts_playback_supervisor.py"), "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "usage:" in result.stdout
    assert "Codex" not in result.stdout
