from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
from pathlib import Path
from threading import Thread
from typing import Any
import json
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from codex_session_start_tts_check import check_startup, extract_voice_names, main  # noqa: E402
from tts_hook.config import load_config  # noqa: E402
from tts_hook.logging import HookLogger  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "session_start"


@pytest.fixture
def startup_fixture() -> str:
    return (FIXTURES / "startup.json").read_text(encoding="utf-8")


def read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def write_config(plugin_root: Path, *, port: int, voice: str = "am_liam") -> None:
    (plugin_root / "tts-hook.toml").write_text(
        f"""
[kokoro]
host = "127.0.0.1"
port = {port}

[speech]
voice = "{voice}"

[logging]
path = "{plugin_root / 'hook.log'}"
""",
        encoding="utf-8",
    )


@pytest.fixture
def kokoro_server() -> tuple[ThreadingHTTPServer, dict[str, Any]]:
    state: dict[str, Any] = {
        "health_status": 200,
        "health_body": b'{"status":"ok"}',
        "voices_status": 200,
        "voices_body": b'{"voices":["am_liam","af_sarah"]}',
        "paths": [],
    }

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            state["paths"].append(self.path)
            if self.path == "/health":
                self.send_response(state["health_status"])
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(state["health_body"])
                return
            if self.path == "/v1/audio/voices":
                self.send_response(state["voices_status"])
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(state["voices_body"])
                return
            self.send_response(404)
            self.end_headers()

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


def test_minimal_session_start_fixture_script_exits_zero_with_valid_stdout(
    tmp_path: Path,
) -> None:
    env = {"HOME": str(tmp_path)}

    result = subprocess.run(
        [sys.executable, "./scripts/codex_session_start_tts_check.py"],
        cwd=ROOT,
        input=read_fixture("resume.json"),
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0
    assert json.loads(result.stdout)["continue"] is True


def test_healthy_kokoro_and_valid_voice_pass_silently(
    tmp_path: Path,
    startup_fixture: str,
    kokoro_server: tuple[ThreadingHTTPServer, dict[str, Any]],
) -> None:
    server, state = kokoro_server
    write_config(tmp_path, port=server.server_port, voice="af_sarah")
    stdout = StringIO()
    stderr = StringIO()

    exit_code = main(
        stdin=StringIO(startup_fixture),
        stdout=stdout,
        stderr=stderr,
        plugin_root=tmp_path,
    )

    assert exit_code == 0
    assert json.loads(stdout.getvalue()) == {"continue": True}
    assert state["paths"] == ["/health", "/v1/audio/voices"]
    assert "warning" not in stderr.getvalue().lower()


def test_unavailable_kokoro_warns_and_continues(tmp_path: Path) -> None:
    write_config(tmp_path, port=9)
    stdout = StringIO()
    stderr = StringIO()

    exit_code = main(
        stdin=StringIO(read_fixture("unavailable_api.json")),
        stdout=stdout,
        stderr=stderr,
        plugin_root=tmp_path,
    )
    result = json.loads(stdout.getvalue())

    assert exit_code == 0
    assert result["continue"] is True
    assert "systemMessage" in result
    assert "Kokoro TTS startup check warning:" in result["systemMessage"]
    assert "Kokoro is unavailable" in result["systemMessage"]


def test_invalid_voice_warns_with_configured_voice_and_default_behavior(
    tmp_path: Path,
    kokoro_server: tuple[ThreadingHTTPServer, dict[str, Any]],
) -> None:
    server, state = kokoro_server
    state["voices_body"] = b'{"voices":["am_liam","af_sarah"]}'
    write_config(tmp_path, port=server.server_port, voice="bad_voice")
    stdout = StringIO()

    exit_code = main(
        stdin=StringIO(read_fixture("invalid_voice.json")),
        stdout=stdout,
        stderr=StringIO(),
        plugin_root=tmp_path,
    )
    result = json.loads(stdout.getvalue())

    assert exit_code == 0
    assert result["continue"] is True
    assert "bad_voice" in result["systemMessage"]
    assert "am_liam" in result["systemMessage"]
    assert state["paths"] == ["/health", "/v1/audio/voices"]


def test_voice_check_failure_warns_but_does_not_block(
    tmp_path: Path,
    startup_fixture: str,
    kokoro_server: tuple[ThreadingHTTPServer, dict[str, Any]],
) -> None:
    server, state = kokoro_server
    state["voices_status"] = 500
    state["voices_body"] = b"voice endpoint failed"
    write_config(tmp_path, port=server.server_port)
    stdout = StringIO()

    exit_code = main(
        stdin=StringIO(startup_fixture),
        stdout=stdout,
        stderr=StringIO(),
        plugin_root=tmp_path,
    )
    result = json.loads(stdout.getvalue())

    assert exit_code == 0
    assert result["continue"] is True
    assert "voices could not be checked" in result["systemMessage"]


def test_unreadable_voice_response_warns_but_does_not_block(
    tmp_path: Path,
    startup_fixture: str,
    kokoro_server: tuple[ThreadingHTTPServer, dict[str, Any]],
) -> None:
    server, state = kokoro_server
    state["voices_body"] = b'{"unexpected":[]}'
    write_config(tmp_path, port=server.server_port)
    stdout = StringIO()

    exit_code = main(
        stdin=StringIO(startup_fixture),
        stdout=stdout,
        stderr=StringIO(),
        plugin_root=tmp_path,
    )
    result = json.loads(stdout.getvalue())

    assert exit_code == 0
    assert result["continue"] is True
    assert "did not include voice names" in result["systemMessage"]


def test_invalid_hook_stdin_warns_and_does_not_call_kokoro(tmp_path: Path) -> None:
    stdout = StringIO()

    exit_code = main(stdin=StringIO("not-json"), stdout=stdout, stderr=StringIO(), plugin_root=tmp_path)
    result = json.loads(stdout.getvalue())

    assert exit_code == 0
    assert result["continue"] is True
    assert "not valid JSON" in result["systemMessage"]


def test_invalid_config_warns_and_continues(tmp_path: Path, startup_fixture: str) -> None:
    (tmp_path / "tts-hook.toml").write_text("[speech]\nspeed = false\n", encoding="utf-8")
    stdout = StringIO()

    exit_code = main(
        stdin=StringIO(startup_fixture),
        stdout=stdout,
        stderr=StringIO(),
        plugin_root=tmp_path,
    )
    result = json.loads(stdout.getvalue())

    assert exit_code == 0
    assert result["continue"] is True
    assert "Could not load plugin-local TTS config" in result["systemMessage"]


def test_extract_voice_names_supports_common_response_shapes() -> None:
    assert extract_voice_names({"voices": ["am_liam"]}) == {"am_liam"}
    assert extract_voice_names({"data": [{"id": "af_sarah"}]}) == {"af_sarah"}
    assert extract_voice_names([{"name": "am_adam"}, {"voice": "bf_emma"}]) == {"am_adam", "bf_emma"}


def test_check_startup_uses_default_voice_when_config_omits_voice(
    tmp_path: Path,
    kokoro_server: tuple[ThreadingHTTPServer, dict[str, Any]],
) -> None:
    server, state = kokoro_server
    (tmp_path / "tts-hook.toml").write_text(
        f"""
[kokoro]
host = "127.0.0.1"
port = {server.server_port}

[logging]
path = "{tmp_path / 'hook.log'}"
""",
        encoding="utf-8",
    )
    config = load_config(tmp_path)

    warning = check_startup(config, HookLogger.from_config(config, stderr=StringIO()))

    assert warning is None
    assert config.speech.voice == "am_liam"
    assert state["paths"] == ["/health", "/v1/audio/voices"]
