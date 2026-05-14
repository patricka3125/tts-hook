"""Codex SessionStart hook that checks Kokoro TTS availability."""

from __future__ import annotations

from pathlib import Path
from typing import Any, TextIO
import sys

from .config import ConfigError, DEFAULT_VOICE, TtsHookConfig, load_config
from .hook_io import continue_result, read_hook_json, write_hook_json
from .kokoro import check_health, list_voices
from .logging import HookLogger

WARNING_PREFIX = "Kokoro TTS startup check warning:"


def main(
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    plugin_root: Path | None = None,
) -> int:
    """Run the startup availability check and always emit hook JSON."""

    input_result = read_hook_json(stdin)
    if not input_result.ok:
        _write_stderr(stderr, input_result.warning or "Hook stdin could not be parsed")
        write_hook_json(continue_result(_warning(input_result.warning or "Could not parse hook input")), stdout)
        return 0

    try:
        config = load_config(plugin_root)
    except ConfigError as exc:
        message = f"Could not load plugin-local TTS config; startup will continue. {exc}"
        _write_stderr(stderr, message)
        write_hook_json(continue_result(_warning(message)), stdout)
        return 0

    logger = HookLogger.from_config(config, stderr=stderr)
    warning = check_startup(config, logger)
    write_hook_json(continue_result(_warning(warning) if warning else None), stdout)
    return 0


def check_startup(config: TtsHookConfig, logger: HookLogger | None = None) -> str | None:
    """Check Kokoro health and configured/default voice."""

    health = check_health(config)
    if not health.ok:
        warning = f"Kokoro is unavailable at startup; continuing without blocking Codex. {health.error or 'Health check failed.'}"
        if logger is not None:
            logger.warning(warning, stderr=True)
        return warning

    voices = list_voices(config)
    if not voices.ok:
        warning = f"Kokoro health passed, but voices could not be checked; continuing. {voices.error or 'Voice check failed.'}"
        if logger is not None:
            logger.warning(warning, stderr=True)
        return warning

    available_voices = extract_voice_names(voices.data)
    configured_voice = config.speech.voice or DEFAULT_VOICE
    if not available_voices:
        warning = "Kokoro health passed, but the voices response did not include voice names; continuing."
        if logger is not None:
            logger.warning(warning, stderr=True)
        return warning

    if configured_voice not in available_voices:
        warning = (
            f"Kokoro voice '{configured_voice}' is not listed by the server; continuing. "
            f"Update speech.voice in tts-hook.toml, or remove it to use '{DEFAULT_VOICE}'."
        )
        if logger is not None:
            logger.warning(warning, stderr=True)
        return warning

    return None


def extract_voice_names(data: Any) -> set[str]:
    """Extract voice names from common Kokoro voices response shapes."""

    if isinstance(data, dict):
        for key in ("voices", "data"):
            voices = data.get(key)
            extracted = extract_voice_names(voices)
            if extracted:
                return extracted
        return set()

    if not isinstance(data, list):
        return set()

    names: set[str] = set()
    for item in data:
        if isinstance(item, str):
            names.add(item)
        elif isinstance(item, dict):
            for key in ("id", "name", "voice"):
                value = item.get(key)
                if isinstance(value, str) and value:
                    names.add(value)
                    break
    return names


def cli() -> int:
    """Console-script entrypoint."""

    return main()


def _warning(message: str) -> str:
    return f"{WARNING_PREFIX} {message}"


def _write_stderr(stderr: TextIO | None, message: str) -> None:
    stream = stderr or sys.stderr
    try:
        stream.write(message + "\n")
        stream.flush()
    except OSError:
        return
