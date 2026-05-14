from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
from pathlib import Path
from threading import Thread
from typing import Any
import http.client
import json
import subprocess
import sys

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PLUGIN_ROOT.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

import tts_hook.kokoro as kokoro_module  # noqa: E402
from tts_hook.config import (  # noqa: E402
    KOKORO_MODEL,
    RESPONSE_FORMAT,
    STREAM,
    build_kokoro_urls,
    build_speech_payload,
    load_config,
)
from tts_hook.hook_io import continue_result, read_hook_json, write_hook_json  # noqa: E402
from tts_hook.kokoro import check_health, list_voices, synthesize_speech  # noqa: E402
from tts_hook.logging import HookLogger  # noqa: E402


def test_loads_defaults_without_config_file(tmp_path: Path) -> None:
    config = load_config(tmp_path)

    assert config.kokoro.host == "localhost"
    assert config.kokoro.port == 8880
    assert config.speech.voice == "am_liam"
    assert config.speech.speed == 1.0
    assert config.playback.player == "auto"
    assert config.playback.blocking is False
    assert config.timeouts.connect_seconds == 2.0
    assert config.timeouts.read_seconds == 20.0
    assert config.logging.path == "~/.codex/tts-hook.log"


def test_loads_partial_plugin_local_config(tmp_path: Path) -> None:
    (tmp_path / "tts-hook.toml").write_text('[speech]\nvoice = "af_sarah"\n', encoding="utf-8")

    config = load_config(tmp_path)

    assert config.kokoro.host == "localhost"
    assert config.speech.voice == "af_sarah"
    assert config.speech.speed == 1.0


def test_ignores_home_and_environment_config_locations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin_root = tmp_path / "plugin"
    plugin_root.mkdir()
    home = tmp_path / "home"
    home_config = home / ".codex"
    home_config.mkdir(parents=True)
    (home_config / "tts-hook.toml").write_text('[speech]\nvoice = "home_voice"\n', encoding="utf-8")
    env_config = tmp_path / "env-config.toml"
    env_config.write_text('[kokoro]\nport = 9999\n', encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CODEX_TTS_CONFIG", str(env_config))

    config = load_config(plugin_root)
    urls = build_kokoro_urls(config)
    payload = build_speech_payload(config, "hello")

    assert config.speech.voice == "am_liam"
    assert urls.health_url == "http://localhost:8880/health"
    assert payload["model"] == KOKORO_MODEL
    assert payload["response_format"] == RESPONSE_FORMAT
    assert payload["stream"] is False


def test_loads_all_supported_keys_and_ignores_stable_constants(tmp_path: Path) -> None:
    (tmp_path / "tts-hook.toml").write_text(
        """
[kokoro]
host = "127.0.0.1"
port = 9999
scheme = "https"

[speech]
voice = "am_adam"
speed = 1.25
model = "not-kokoro"
response_format = "mp3"
stream = true

[playback]
player = "pw-play"
blocking = true

[timeouts]
connect_seconds = 1.5
read_seconds = 8.0

[logging]
path = "./tmp/hook.log"
""",
        encoding="utf-8",
    )

    config = load_config(tmp_path)
    urls = build_kokoro_urls(config)
    payload = build_speech_payload(config, "hello")

    assert urls.health_url == "http://127.0.0.1:9999/health"
    assert payload["model"] == KOKORO_MODEL
    assert payload["response_format"] == RESPONSE_FORMAT
    assert payload["stream"] == STREAM
    assert payload["voice"] == "am_adam"
    assert config.playback.player == "pw-play"
    assert config.playback.blocking is True
    assert config.logging.path == "./tmp/hook.log"


def test_default_urls_are_kokoro_localhost(tmp_path: Path) -> None:
    urls = build_kokoro_urls(load_config(tmp_path))

    assert urls.health_url == "http://localhost:8880/health"
    assert urls.speech_url == "http://localhost:8880/v1/audio/speech"
    assert urls.voices_url == "http://localhost:8880/v1/audio/voices"


def test_reads_valid_hook_json() -> None:
    result = read_hook_json(StringIO('{"last_assistant_message":"done"}'))

    assert result.ok is True
    assert result.payload["last_assistant_message"] == "done"


def test_empty_stdin_returns_warning_result() -> None:
    result = read_hook_json(StringIO(""))

    assert result.ok is False
    assert result.payload == {}
    assert "empty" in (result.warning or "")


def test_invalid_stdin_returns_warning_result() -> None:
    result = read_hook_json(StringIO("not json"))

    assert result.ok is False
    assert result.payload == {}
    assert "valid JSON" in (result.warning or "")


@pytest.mark.parametrize("raw", ["[]", '"message"'])
def test_non_object_stdin_returns_warning_result(raw: str) -> None:
    result = read_hook_json(StringIO(raw))

    assert result.ok is False
    assert result.payload == {}
    assert "not an object" in (result.warning or "")


def test_write_hook_json_only_writes_json_to_stdout() -> None:
    stdout = StringIO()

    write_hook_json(continue_result("warning"), stdout)

    assert json.loads(stdout.getvalue()) == {"continue": True, "systemMessage": "warning"}


def test_logger_creates_parent_directories_without_stdout(tmp_path: Path) -> None:
    log_path = tmp_path / "nested" / "hook.log"
    (tmp_path / "tts-hook.toml").write_text(
        f'[logging]\npath = "{log_path}"\n',
        encoding="utf-8",
    )
    stderr = StringIO()
    logger = HookLogger.from_config(load_config(tmp_path), stderr=stderr)

    logger.warning("failed to speak", content="x" * 200)

    log_text = log_path.read_text(encoding="utf-8")
    assert "failed to speak" in log_text
    assert "..." in log_text
    assert stderr.getvalue() == ""


def test_logger_is_best_effort_for_unwritable_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_path = tmp_path / "hook.log"
    (tmp_path / "tts-hook.toml").write_text(
        f'[logging]\npath = "{log_path}"\n',
        encoding="utf-8",
    )
    stderr = StringIO()
    logger = HookLogger.from_config(load_config(tmp_path), stderr=stderr)

    def fail_open(self: Path, *args: object, **kwargs: object) -> object:
        raise OSError("permission denied")

    monkeypatch.setattr(Path, "open", fail_open)

    logger.warning("could not log", stderr=True)

    assert "could not log" in stderr.getvalue()
    assert "log_write_failed=permission denied" in stderr.getvalue()


@pytest.fixture
def kokoro_server() -> tuple[ThreadingHTTPServer, dict[str, Any]]:
    seen: dict[str, Any] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            seen.setdefault("paths", []).append(self.path)
            if self.path == "/health":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"status":"ok"}')
                return
            if self.path == "/v1/audio/voices":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"voices":["am_liam","af_sarah"]}')
                return
            self.send_response(404)
            self.end_headers()

        def do_POST(self) -> None:  # noqa: N802
            seen["post_path"] = self.path
            seen["content_type"] = self.headers.get("Content-Type")
            body = self.rfile.read(int(self.headers["Content-Length"]))
            seen["payload"] = json.loads(body.decode("utf-8"))
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.end_headers()
            self.wfile.write(b"RIFF")

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, seen
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_client_uses_configured_urls_timeouts_and_speech_payload(
    tmp_path: Path,
    kokoro_server: tuple[ThreadingHTTPServer, dict[str, Any]],
) -> None:
    server, seen = kokoro_server
    (tmp_path / "tts-hook.toml").write_text(
        f"""
[kokoro]
host = "127.0.0.1"
port = {server.server_port}

[speech]
voice = "af_sarah"
speed = 0.9

[timeouts]
connect_seconds = 0.5
read_seconds = 1.0
""",
        encoding="utf-8",
    )
    config = load_config(tmp_path)

    health = check_health(config)
    voices = list_voices(config)
    speech = synthesize_speech(config, "full text with no truncation")

    assert health.ok is True
    assert voices.ok is True
    assert speech.ok is True
    assert speech.data == b"RIFF"
    assert seen["paths"] == ["/health", "/v1/audio/voices"]
    assert seen["post_path"] == "/v1/audio/speech"
    assert seen["content_type"] == "application/json"
    assert seen["payload"] == {
        "model": "kokoro",
        "input": "full text with no truncation",
        "voice": "af_sarah",
        "response_format": "wav",
        "stream": False,
        "speed": 0.9,
    }


def test_client_applies_configured_connect_and_read_timeouts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, Any] = {}

    class FakeSocket:
        def settimeout(self, timeout: float) -> None:
            calls["read_timeout"] = timeout

    class FakeResponse:
        status = 200
        reason = "OK"

        def read(self) -> bytes:
            return b'{"status":"ok"}'

    class FakeConnection:
        def __init__(self, host: str, port: int, timeout: float) -> None:
            calls["host"] = host
            calls["port"] = port
            calls["connect_timeout"] = timeout
            self.sock = FakeSocket()

        def request(
            self,
            method: str,
            path: str,
            body: bytes | None = None,
            headers: dict[str, str] | None = None,
        ) -> None:
            calls["request"] = (method, path, body, headers)

        def getresponse(self) -> FakeResponse:
            return FakeResponse()

        def close(self) -> None:
            calls["closed"] = True

    (tmp_path / "tts-hook.toml").write_text(
        """
[kokoro]
host = "127.0.0.1"
port = 9999

[timeouts]
connect_seconds = 0.25
read_seconds = 3.5
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(kokoro_module.http.client, "HTTPConnection", FakeConnection)

    result = check_health(load_config(tmp_path))

    assert result.ok is True
    assert calls["host"] == "127.0.0.1"
    assert calls["port"] == 9999
    assert calls["connect_timeout"] == 0.25
    assert calls["read_timeout"] == 3.5
    assert calls["request"][0:2] == ("GET", "/health")
    assert calls["closed"] is True


def test_client_transport_errors_include_method_and_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingConnection:
        def __init__(self, host: str, port: int, timeout: float) -> None:
            self.sock = None

        def request(
            self,
            method: str,
            path: str,
            body: bytes | None = None,
            headers: dict[str, str] | None = None,
        ) -> None:
            raise http.client.HTTPException("boom")

        def close(self) -> None:
            return

    (tmp_path / "tts-hook.toml").write_text(
        """
[kokoro]
host = "127.0.0.1"
port = 9999
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(kokoro_module.http.client, "HTTPConnection", FailingConnection)

    result = check_health(load_config(tmp_path))

    assert result.ok is False
    assert result.error == "GET http://127.0.0.1:9999/health failed: boom"


def test_package_can_import_shared_modules_without_installing_package() -> None:
    script = "from tts_hook.config import build_kokoro_urls, load_config; print(build_kokoro_urls(load_config()).health_url)"

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        env={"PYTHONPATH": str(REPO_ROOT / "src")},
        check=True,
    )

    assert result.stdout.strip() == "http://localhost:8880/health"
