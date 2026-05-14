"""Configuration and Kokoro URL helpers for the TTS hook plugin."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import tomllib

KOKORO_SCHEME = "http"
KOKORO_API_PREFIX = "/v1"
KOKORO_MODEL = "kokoro"
HEALTH_PATH = "/health"
SPEECH_PATH = "/audio/speech"
VOICES_PATH = "/audio/voices"
RESPONSE_FORMAT = "wav"
STREAM = False

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 8880
DEFAULT_VOICE = "am_liam"
DEFAULT_SPEED = 1.0
DEFAULT_PLAYER = "auto"
DEFAULT_CONNECT_TIMEOUT_SECONDS = 2.0
DEFAULT_READ_TIMEOUT_SECONDS = 20.0
DEFAULT_LOG_PATH = "~/.codex/tts-hook.log"
CONFIG_FILENAME = "tts-hook.toml"


class ConfigError(ValueError):
    """Raised when plugin-local configuration cannot be parsed."""


@dataclass(frozen=True)
class KokoroConfig:
    """Host and port for the Kokoro-FastAPI service."""

    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT


@dataclass(frozen=True)
class SpeechConfig:
    """Speech settings that are expected to vary per user."""

    voice: str = DEFAULT_VOICE
    speed: float = DEFAULT_SPEED


@dataclass(frozen=True)
class PlaybackConfig:
    """Playback settings shared by future hook implementations."""

    player: str = DEFAULT_PLAYER


@dataclass(frozen=True)
class TimeoutConfig:
    """HTTP timeout settings for Kokoro requests."""

    connect_seconds: float = DEFAULT_CONNECT_TIMEOUT_SECONDS
    read_seconds: float = DEFAULT_READ_TIMEOUT_SECONDS


@dataclass(frozen=True)
class LoggingConfig:
    """Diagnostic logging settings."""

    path: str = DEFAULT_LOG_PATH


@dataclass(frozen=True)
class TtsHookConfig:
    """Complete runtime configuration for the plugin."""

    plugin_root: Path
    config_path: Path
    kokoro: KokoroConfig = KokoroConfig()
    speech: SpeechConfig = SpeechConfig()
    playback: PlaybackConfig = PlaybackConfig()
    timeouts: TimeoutConfig = TimeoutConfig()
    logging: LoggingConfig = LoggingConfig()


@dataclass(frozen=True)
class KokoroUrls:
    """Fully constructed Kokoro endpoint URLs."""

    base_url: str
    health_url: str
    speech_url: str
    voices_url: str


def default_plugin_root() -> Path:
    """Return the plugin root that contains this source tree."""

    return Path(__file__).resolve().parents[2]


def config_path_for(plugin_root: Path | None = None) -> Path:
    """Return the only supported config path for a plugin root."""

    root = plugin_root or default_plugin_root()
    return root / CONFIG_FILENAME


def load_config(plugin_root: Path | None = None) -> TtsHookConfig:
    """Load plugin-local config and merge it with code defaults.

    Only ``<plugin-root>/tts-hook.toml`` is consulted. Environment variables
    and user-home config files are intentionally not part of this phase.
    Unknown keys are ignored so stable integration constants cannot be promoted
    to runtime config by accident.
    """

    root = (plugin_root or default_plugin_root()).resolve()
    path = config_path_for(root)
    raw: dict[str, Any] = {}

    if path.exists():
        try:
            raw = tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"Invalid TOML in {path}: {exc}") from exc
        except OSError as exc:
            raise ConfigError(f"Could not read config {path}: {exc}") from exc

    return TtsHookConfig(
        plugin_root=root,
        config_path=path,
        kokoro=KokoroConfig(
            host=_string_value(raw, "kokoro", "host", DEFAULT_HOST) or DEFAULT_HOST,
            port=_int_value(raw, "kokoro", "port", DEFAULT_PORT),
        ),
        speech=SpeechConfig(
            voice=_string_value(raw, "speech", "voice", DEFAULT_VOICE) or DEFAULT_VOICE,
            speed=_float_value(raw, "speech", "speed", DEFAULT_SPEED),
        ),
        playback=PlaybackConfig(
            player=_string_value(raw, "playback", "player", DEFAULT_PLAYER) or DEFAULT_PLAYER,
        ),
        timeouts=TimeoutConfig(
            connect_seconds=_float_value(
                raw,
                "timeouts",
                "connect_seconds",
                DEFAULT_CONNECT_TIMEOUT_SECONDS,
            ),
            read_seconds=_float_value(raw, "timeouts", "read_seconds", DEFAULT_READ_TIMEOUT_SECONDS),
        ),
        logging=LoggingConfig(
            path=_string_value(raw, "logging", "path", DEFAULT_LOG_PATH) or DEFAULT_LOG_PATH,
        ),
    )


def build_kokoro_urls(config: TtsHookConfig) -> KokoroUrls:
    """Build Kokoro URLs with baked-in scheme, API prefix, and endpoint paths."""

    host = _format_host(config.kokoro.host)
    base_url = f"{KOKORO_SCHEME}://{host}:{config.kokoro.port}"
    return KokoroUrls(
        base_url=base_url,
        health_url=f"{base_url}{HEALTH_PATH}",
        speech_url=f"{base_url}{KOKORO_API_PREFIX}{SPEECH_PATH}",
        voices_url=f"{base_url}{KOKORO_API_PREFIX}{VOICES_PATH}",
    )


def build_speech_payload(config: TtsHookConfig, input_text: str) -> dict[str, Any]:
    """Build the OpenAI-compatible Kokoro speech payload."""

    return {
        "model": KOKORO_MODEL,
        "input": input_text,
        "voice": config.speech.voice or DEFAULT_VOICE,
        "response_format": RESPONSE_FORMAT,
        "stream": STREAM,
        "speed": config.speech.speed,
    }


def _section(raw: dict[str, Any], name: str) -> dict[str, Any]:
    value = raw.get(name, {})
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"Config section [{name}] must be a table")
    return value


def _string_value(raw: dict[str, Any], section: str, key: str, default: str) -> str:
    value = _section(raw, section).get(key, default)
    if value is None:
        return default
    if not isinstance(value, str):
        raise ConfigError(f"Config key {section}.{key} must be a string")
    return value.strip()


def _int_value(raw: dict[str, Any], section: str, key: str, default: int) -> int:
    value = _section(raw, section).get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"Config key {section}.{key} must be an integer")
    if value <= 0:
        raise ConfigError(f"Config key {section}.{key} must be positive")
    return value


def _float_value(raw: dict[str, Any], section: str, key: str, default: float) -> float:
    value = _section(raw, section).get(key, default)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ConfigError(f"Config key {section}.{key} must be a number")
    value = float(value)
    if value <= 0:
        raise ConfigError(f"Config key {section}.{key} must be positive")
    return value


def _bool_value(raw: dict[str, Any], section: str, key: str, default: bool) -> bool:
    value = _section(raw, section).get(key, default)
    if not isinstance(value, bool):
        raise ConfigError(f"Config key {section}.{key} must be true or false")
    return value


def _format_host(host: str) -> str:
    stripped = host.strip()
    if stripped.startswith("[") and stripped.endswith("]"):
        return stripped
    if ":" in stripped:
        return f"[{stripped}]"
    return quote(stripped, safe=".-_~")
