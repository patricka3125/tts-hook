from __future__ import annotations

from io import StringIO
from pathlib import Path
from typing import Any
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import tts_playback_supervisor as supervisor_module  # noqa: E402
from tts_hook.playback import PlaybackProcessResult  # noqa: E402


class FakeStream:
    def __init__(self, data: bytes = b"") -> None:
        self.data = data
        self.closed = False

    def fileno(self) -> int:
        return 42

    def read(self, size: int) -> bytes:
        return self.data[:size]

    def close(self) -> None:
        self.closed = True


class FakeTermios:
    TCSADRAIN = 1

    def __init__(self) -> None:
        self.restored: list[tuple[int, int, object]] = []

    def tcgetattr(self, fd: int) -> list[int]:
        assert fd == 42
        return [1, 2, 3]

    def tcsetattr(self, fd: int, when: int, attrs: object) -> None:
        self.restored.append((fd, when, attrs))


class FakeTty:
    def __init__(self) -> None:
        self.cbreak_fds: list[int] = []

    def setcbreak(self, fd: int) -> None:
        self.cbreak_fds.append(fd)


class FakeProcess:
    def __init__(self, poll_results: list[int | None] | None = None) -> None:
        self.poll_results = poll_results or [0]
        self.wait_calls = 0
        self.pid = 321

    def poll(self) -> int | None:
        if len(self.poll_results) > 1:
            return self.poll_results.pop(0)
        return self.poll_results[0]

    def wait(self, timeout: float | None = None) -> int:
        self.wait_calls += 1
        self.poll_results = [0]
        return 0


class FakeReader:
    def __init__(self, escape_results: list[bool]) -> None:
        self.escape_results = escape_results
        self.closed = False

    def escape_pressed(self, timeout_seconds: float) -> bool:
        if len(self.escape_results) > 1:
            return self.escape_results.pop(0)
        return self.escape_results[0]

    def close(self) -> None:
        self.closed = True


def test_tty_escape_reader_detects_escape_and_restores_terminal() -> None:
    stream = FakeStream(supervisor_module.ESCAPE)
    termios = FakeTermios()
    tty = FakeTty()
    reader = supervisor_module.TtyEscapeReader(
        opener=lambda *args, **kwargs: stream,
        select_fn=lambda readable, _writable, _errors, _timeout: (readable, [], []),
        termios_module=termios,
        tty_module=tty,
    )

    with reader as active_reader:
        assert active_reader.escape_pressed(0.01) is True

    assert tty.cbreak_fds == [42]
    assert termios.restored == [(42, termios.TCSADRAIN, [1, 2, 3])]
    assert stream.closed is True


def test_tty_escape_reader_ignores_non_escape_input_and_timeout() -> None:
    stream = FakeStream(b"x")
    reader = supervisor_module.TtyEscapeReader(
        opener=lambda *args, **kwargs: stream,
        select_fn=lambda readable, _writable, _errors, _timeout: (readable, [], []),
        termios_module=FakeTermios(),
        tty_module=FakeTty(),
    )

    with reader:
        assert reader.escape_pressed(0.01) is False

    timeout_reader = supervisor_module.TtyEscapeReader(
        opener=lambda *args, **kwargs: FakeStream(supervisor_module.ESCAPE),
        select_fn=lambda _readable, _writable, _errors, _timeout: ([], [], []),
        termios_module=FakeTermios(),
        tty_module=FakeTty(),
    )
    with timeout_reader:
        assert timeout_reader.escape_pressed(0.01) is False


def test_open_tty_failure_disables_cancel_support() -> None:
    stderr = StringIO()

    class FailingReader:
        def __enter__(self) -> object:
            raise OSError("no tty")

        def close(self) -> None:
            return

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(supervisor_module, "TtyEscapeReader", FailingReader)

        reader = supervisor_module.open_tty_escape_reader(stderr=stderr)

    assert reader is None
    assert "Escape cancel unavailable" in stderr.getvalue()


def test_tty_configuration_failure_restores_terminal_and_disables_cancel() -> None:
    stream = FakeStream()
    termios = FakeTermios()
    stderr = StringIO()

    class FailingTty:
        def setcbreak(self, fd: int) -> None:
            raise supervisor_module.termios.error("cannot configure tty")

    original_reader = supervisor_module.TtyEscapeReader
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            supervisor_module,
            "TtyEscapeReader",
            lambda: original_reader(
                opener=lambda *args, **kwargs: stream,
                termios_module=termios,
                tty_module=FailingTty(),
            ),
        )

        reader = supervisor_module.open_tty_escape_reader(stderr=stderr)

    assert reader is None
    assert termios.restored == [(42, termios.TCSADRAIN, [1, 2, 3])]
    assert stream.closed is True
    assert "Escape cancel unavailable" in stderr.getvalue()


def test_supervisor_no_tty_waits_for_playback_and_cleans_wav(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wav = tmp_path / "audio.wav"
    wav.write_bytes(b"RIFF")
    process = FakeProcess([None, 0])
    monkeypatch.setattr(
        supervisor_module,
        "launch_audio_player_process",
        lambda wav_path, *, player: PlaybackProcessResult(ok=True, command=("player", str(wav_path)), process=process),
    )
    monkeypatch.setattr(supervisor_module, "open_tty_escape_reader", lambda *, stderr=None: None)
    monkeypatch.setattr(supervisor_module, "install_signal_handlers", lambda: None)

    exit_code = supervisor_module.supervise_playback(wav, player="auto", stderr=StringIO())

    assert exit_code == 0
    assert process.wait_calls == 1
    assert not wav.exists()


def test_supervisor_poll_failure_continues_playback_without_cancel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wav = tmp_path / "audio.wav"
    wav.write_bytes(b"RIFF")
    process = FakeProcess([None, None, 0])
    stderr = StringIO()

    class FailingReader:
        closed = False

        def escape_pressed(self, timeout_seconds: float) -> bool:
            raise OSError("poll failed")

        def close(self) -> None:
            self.closed = True

    reader = FailingReader()
    monkeypatch.setattr(
        supervisor_module,
        "launch_audio_player_process",
        lambda wav_path, *, player: PlaybackProcessResult(ok=True, command=("player", str(wav_path)), process=process),
    )
    monkeypatch.setattr(supervisor_module, "open_tty_escape_reader", lambda *, stderr=None: reader)
    monkeypatch.setattr(supervisor_module, "install_signal_handlers", lambda: None)

    exit_code = supervisor_module.supervise_playback(wav, player="auto", stderr=stderr)

    assert exit_code == 0
    assert process.wait_calls == 1
    assert reader.closed is True
    assert "Disabling Escape cancel support" in stderr.getvalue()
    assert not wav.exists()


def test_supervisor_escape_cancels_current_playback_and_cleans_wav(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wav = tmp_path / "audio.wav"
    wav.write_bytes(b"RIFF")
    process = FakeProcess([None, None])
    reader = FakeReader([True])
    terminated: list[FakeProcess] = []
    monkeypatch.setattr(
        supervisor_module,
        "launch_audio_player_process",
        lambda wav_path, *, player: PlaybackProcessResult(ok=True, command=("player", str(wav_path)), process=process),
    )
    monkeypatch.setattr(supervisor_module, "open_tty_escape_reader", lambda *, stderr=None: reader)
    monkeypatch.setattr(supervisor_module, "terminate_process_group", lambda active_process: terminated.append(active_process))
    monkeypatch.setattr(supervisor_module, "install_signal_handlers", lambda: None)

    exit_code = supervisor_module.supervise_playback(wav, player="auto", stderr=StringIO())

    assert exit_code == 0
    assert terminated == [process]
    assert reader.closed is True
    assert not wav.exists()


def test_supervisor_natural_completion_does_not_cancel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wav = tmp_path / "audio.wav"
    wav.write_bytes(b"RIFF")
    process = FakeProcess([None, 0])
    reader = FakeReader([False])
    terminated: list[Any] = []
    monkeypatch.setattr(
        supervisor_module,
        "launch_audio_player_process",
        lambda wav_path, *, player: PlaybackProcessResult(ok=True, command=("player", str(wav_path)), process=process),
    )
    monkeypatch.setattr(supervisor_module, "open_tty_escape_reader", lambda *, stderr=None: reader)
    monkeypatch.setattr(supervisor_module, "terminate_process_group", lambda active_process: terminated.append(active_process))
    monkeypatch.setattr(supervisor_module, "install_signal_handlers", lambda: None)

    exit_code = supervisor_module.supervise_playback(wav, player="auto", stderr=StringIO())

    assert exit_code == 0
    assert terminated == []
    assert reader.closed is True
    assert not wav.exists()


def test_cleanup_failure_is_nonfatal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    wav = tmp_path / "audio.wav"
    wav.write_bytes(b"RIFF")
    process = FakeProcess([0])
    stderr = StringIO()
    monkeypatch.setattr(
        supervisor_module,
        "launch_audio_player_process",
        lambda wav_path, *, player: PlaybackProcessResult(ok=True, command=("player", str(wav_path)), process=process),
    )
    monkeypatch.setattr(supervisor_module, "open_tty_escape_reader", lambda *, stderr=None: None)
    monkeypatch.setattr(supervisor_module, "install_signal_handlers", lambda: None)

    def fail_unlink(self: Path, *args: object, **kwargs: object) -> None:
        raise OSError("permission denied")

    monkeypatch.setattr(Path, "unlink", fail_unlink)

    exit_code = supervisor_module.supervise_playback(wav, player="auto", stderr=stderr)

    assert exit_code == 0
    assert "Could not delete temporary WAV file" in stderr.getvalue()


def test_supervisor_diagnostics_do_not_write_hook_json_to_stdout(tmp_path: Path) -> None:
    missing = tmp_path / "missing.wav"

    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "tts_playback_supervisor.py"), str(missing)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert "WAV file does not exist" in result.stderr
    assert '{"continue"' not in result.stdout
