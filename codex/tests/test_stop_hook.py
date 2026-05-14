from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
from pathlib import Path
from threading import Thread
from typing import Any
import json
import os
import shutil
import subprocess
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from codex_stop_tts import extract_assistant_message, main, speak_last_assistant_message  # noqa: E402
from tts_hook.config import load_config  # noqa: E402
from tts_hook.logging import HookLogger  # noqa: E402
from tts_hook.playback import choose_player_command, play_audio_file  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "stop"


def read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def write_config(
    plugin_root: Path,
    *,
    port: int,
    log_path: Path,
    player: str = "auto",
    blocking: bool = False,
    voice: str = "am_liam",
) -> None:
    (plugin_root / "tts-hook.toml").write_text(
        f"""
[kokoro]
host = "127.0.0.1"
port = {port}

[speech]
voice = "{voice}"
speed = 1.2

[playback]
player = "{player}"
blocking = {str(blocking).lower()}

[logging]
path = "{log_path}"
""",
        encoding="utf-8",
    )


def make_fake_player(bin_dir: Path, name: str = "pw-play", *, sleep_seconds: float = 0.0) -> Path:
    marker = bin_dir / "played.txt"
    player = bin_dir / name
    player.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' \"$1\" >> {marker}\n"
        f"sleep {sleep_seconds}\n",
        encoding="utf-8",
    )
    player.chmod(0o755)
    return marker


@pytest.fixture
def kokoro_speech_server() -> tuple[ThreadingHTTPServer, dict[str, Any]]:
    state: dict[str, Any] = {
        "status": 200,
        "body": b"RIFFfake-wave",
        "requests": [],
    }

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            body = self.rfile.read(int(self.headers["Content-Length"]))
            state["requests"].append(
                {
                    "path": self.path,
                    "content_type": self.headers.get("Content-Type"),
                    "payload": json.loads(body.decode("utf-8")),
                }
            )
            self.send_response(state["status"])
            self.send_header("Content-Type", "audio/wav")
            self.end_headers()
            self.wfile.write(state["body"])

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_extract_assistant_message_preserves_multiparagraph_text() -> None:
    text = " First paragraph.\n\nSecond paragraph.\n\nThird paragraph. "

    assert extract_assistant_message({"last_assistant_message": text}) == text.strip()


def test_empty_and_missing_messages_are_skipped_without_kokoro(tmp_path: Path) -> None:
    write_config(tmp_path, port=9, log_path=tmp_path / "hook.log")
    stdout = StringIO()
    stderr = StringIO()

    exit_code = main(
        stdin=StringIO(read_fixture("empty.json")),
        stdout=stdout,
        stderr=stderr,
        plugin_root=tmp_path,
    )

    assert exit_code == 0
    assert json.loads(stdout.getvalue()) == {"continue": True}
    assert stderr.getvalue() == ""
    assert "skipping speech" in (tmp_path / "hook.log").read_text(encoding="utf-8")


def test_malformed_stop_input_returns_valid_json_and_stderr_only(tmp_path: Path) -> None:
    stdout = StringIO()
    stderr = StringIO()

    exit_code = main(
        stdin=StringIO(read_fixture("malformed.txt")),
        stdout=stdout,
        stderr=stderr,
        plugin_root=tmp_path,
    )

    assert exit_code == 0
    assert json.loads(stdout.getvalue()) == {"continue": True}
    assert "not valid JSON" in stderr.getvalue()


def test_successful_kokoro_response_writes_unique_wavs_and_preserves_full_payload(
    tmp_path: Path,
    kokoro_speech_server: tuple[ThreadingHTTPServer, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server, state = kokoro_speech_server
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    marker = make_fake_player(bin_dir)
    monkeypatch.setenv("PATH", str(bin_dir))
    write_config(tmp_path, port=server.server_port, log_path=tmp_path / "hook.log", voice="af_sarah")
    config = load_config(tmp_path)
    logger = HookLogger.from_config(config, stderr=StringIO())
    message = read_fixture("long_multiparagraph.json")
    payload = json.loads(message)

    first = speak_last_assistant_message(payload, config, logger)
    second = speak_last_assistant_message(payload, config, logger)

    assert first is not None
    assert second is not None
    assert first != second
    assert first.suffix == ".wav"
    assert second.suffix == ".wav"
    assert first.read_bytes() == b"RIFFfake-wave"
    assert second.read_bytes() == b"RIFFfake-wave"
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and not marker.exists():
        time.sleep(0.05)
    assert marker.exists()
    assert state["requests"][0]["path"] == "/v1/audio/speech"
    assert state["requests"][0]["content_type"] == "application/json"
    assert state["requests"][0]["payload"] == {
        "model": "kokoro",
        "input": payload["last_assistant_message"],
        "voice": "af_sarah",
        "response_format": "wav",
        "stream": False,
        "speed": 1.2,
    }


def test_kokoro_request_failure_logs_without_breaking_hook(tmp_path: Path) -> None:
    write_config(tmp_path, port=9, log_path=tmp_path / "hook.log")
    stdout = StringIO()
    stderr = StringIO()

    exit_code = main(
        stdin=StringIO(read_fixture("normal.json")),
        stdout=stdout,
        stderr=stderr,
        plugin_root=tmp_path,
    )

    assert exit_code == 0
    assert json.loads(stdout.getvalue()) == {"continue": True}
    assert "Kokoro speech request failed" in stderr.getvalue()


def test_no_playback_command_logs_warning_and_returns_valid_hook_json(
    tmp_path: Path,
    kokoro_speech_server: tuple[ThreadingHTTPServer, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server, _state = kokoro_speech_server
    monkeypatch.setenv("PATH", "")
    write_config(tmp_path, port=server.server_port, log_path=tmp_path / "hook.log")
    stdout = StringIO()
    stderr = StringIO()

    exit_code = main(
        stdin=StringIO(read_fixture("normal.json")),
        stdout=stdout,
        stderr=stderr,
        plugin_root=tmp_path,
    )

    assert exit_code == 0
    assert json.loads(stdout.getvalue()) == {"continue": True}
    assert "Playback did not start" in stderr.getvalue()


def test_auto_player_selection_order(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("aplay", "ffplay", "paplay"):
        make_fake_player(bin_dir, name)

    command = choose_player_command("auto", path_env=str(bin_dir))

    assert command is not None
    assert Path(command[0]).name == "paplay"


def test_ffplay_auto_arguments_are_included(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    make_fake_player(bin_dir, "ffplay")

    command = choose_player_command("auto", path_env=str(bin_dir))

    assert command is not None
    assert Path(command[0]).name == "ffplay"
    assert command[1:] == ("-nodisp", "-autoexit")


def test_non_blocking_playback_returns_before_player_exits(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    marker = make_fake_player(bin_dir, sleep_seconds=1.0)
    wav = tmp_path / "audio.wav"
    wav.write_bytes(b"RIFF")
    start = time.monotonic()

    result = play_audio_file(wav, player="auto", blocking=False, path_env=str(bin_dir))

    elapsed = time.monotonic() - start
    assert result.ok is True
    assert elapsed < 0.5
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and not marker.exists():
        time.sleep(0.05)
    assert marker.exists()


def test_blocking_playback_waits_for_player(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    make_fake_player(bin_dir, sleep_seconds=0.15)
    wav = tmp_path / "audio.wav"
    wav.write_bytes(b"RIFF")
    start = time.monotonic()

    result = play_audio_file(wav, player="auto", blocking=True, path_env=str(bin_dir))

    assert result.ok is True
    assert time.monotonic() - start >= 0.1


def test_stop_fixture_subprocess_posts_audio_and_spawns_playback(
    tmp_path: Path,
    kokoro_speech_server: tuple[ThreadingHTTPServer, dict[str, Any]],
) -> None:
    server, state = kokoro_speech_server
    plugin_root = tmp_path / "codex"
    shutil.copytree(ROOT / "scripts", plugin_root / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(ROOT / "src", plugin_root / "src", ignore=shutil.ignore_patterns("__pycache__"))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    marker = make_fake_player(bin_dir, sleep_seconds=0.5)
    write_config(plugin_root, port=server.server_port, log_path=tmp_path / "hook.log")
    start = time.monotonic()

    result = subprocess.run(
        [sys.executable, "./scripts/codex_stop_tts.py"],
        cwd=plugin_root,
        input=read_fixture("normal.json"),
        text=True,
        capture_output=True,
        env={"HOME": str(tmp_path / "home"), "PATH": str(bin_dir)},
        check=False,
    )

    elapsed = time.monotonic() - start
    assert result.returncode == 0
    assert json.loads(result.stdout) == {"continue": True}
    assert result.stderr == ""
    assert elapsed < 0.5
    assert state["requests"][0]["payload"]["input"] == "Codex finished the requested change."
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and not marker.exists():
        time.sleep(0.05)
    assert marker.exists()


def test_no_max_chars_policy_exists() -> None:
    checked = [
        ROOT / "scripts" / "codex_stop_tts.py",
        ROOT / "src" / "tts_hook" / "config.py",
        ROOT / "src" / "tts_hook" / "playback.py",
    ]

    for path in checked:
        assert "max_chars" not in path.read_text(encoding="utf-8")
