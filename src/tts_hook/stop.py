"""Codex Stop hook that speaks the final assistant message through Kokoro."""

from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, TextIO
import sys

from .config import ConfigError, TtsHookConfig, load_config
from .hook_io import continue_result, read_hook_json, write_hook_json
from .kokoro import synthesize_speech
from .logging import HookLogger
from .playback import command_display, play_audio_file


def main(
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    plugin_root: Path | None = None,
) -> int:
    """Run the stop hook and always emit hook-compatible JSON."""

    input_result = read_hook_json(stdin)
    if not input_result.ok:
        _write_stderr(stderr, input_result.warning or "Hook stdin could not be parsed")
        write_hook_json(continue_result(), stdout)
        return 0

    try:
        config = load_config(plugin_root)
    except ConfigError as exc:
        _write_stderr(stderr, f"Could not load plugin-local TTS config: {exc}")
        write_hook_json(continue_result(), stdout)
        return 0

    logger = HookLogger.from_config(config, stderr=stderr)
    speak_last_assistant_message(input_result.payload, config, logger)
    write_hook_json(continue_result(), stdout)
    return 0


def speak_last_assistant_message(
    payload: dict[str, Any],
    config: TtsHookConfig,
    logger: HookLogger,
) -> Path | None:
    """Generate speech for ``last_assistant_message`` and launch playback."""

    text = extract_assistant_message(payload)
    if not text:
        logger.info("Stop hook received no assistant message; skipping speech")
        return None

    speech = synthesize_speech(config, text)
    if not speech.ok or not isinstance(speech.data, bytes):
        logger.warning(f"Kokoro speech request failed; skipping playback. {speech.error or 'No audio returned.'}", stderr=True)
        return None

    try:
        wav_path = write_unique_wav(speech.data)
    except OSError as exc:
        logger.warning(f"Could not write Kokoro WAV response; skipping playback. {exc}", stderr=True)
        return None

    playback = play_audio_file(
        wav_path,
        player=config.playback.player,
        blocking=config.playback.blocking,
    )
    if not playback.ok:
        logger.warning(f"Playback did not start; continuing. {playback.error or 'Unknown playback error.'}", stderr=True)
        return wav_path

    logger.info(f"Started playback with {command_display(playback.command)}")
    return wav_path


def extract_assistant_message(payload: dict[str, Any]) -> str:
    """Return the full final assistant message with only outer whitespace removed."""

    value = payload.get("last_assistant_message", "")
    if not isinstance(value, str):
        return ""
    return value.strip()


def write_unique_wav(audio: bytes) -> Path:
    """Write audio bytes to a unique temporary WAV file."""

    with NamedTemporaryFile(prefix="tts-hook-", suffix=".wav", delete=False) as handle:
        handle.write(audio)
        return Path(handle.name)


def cli() -> int:
    """Console-script entrypoint."""

    return main()


def _write_stderr(stderr: TextIO | None, message: str) -> None:
    stream = stderr or sys.stderr
    try:
        stream.write(message + "\n")
        stream.flush()
    except OSError:
        return
