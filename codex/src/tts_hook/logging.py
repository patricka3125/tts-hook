"""Diagnostic logging helpers for hook scripts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TextIO

import sys

from .config import TtsHookConfig

MAX_CONTENT_LOG_CHARS = 120


@dataclass(frozen=True)
class HookLogger:
    """Write hook diagnostics to a log file and optionally stderr."""

    log_path: Path
    stderr: TextIO | None = None

    @classmethod
    def from_config(cls, config: TtsHookConfig, stderr: TextIO | None = None) -> "HookLogger":
        """Create a logger using the configured log path."""

        return cls(log_path=Path(config.logging.path).expanduser(), stderr=stderr or sys.stderr)

    def info(self, message: str, *, content: str | None = None, stderr: bool = False) -> None:
        """Write an informational diagnostic."""

        self._write("INFO", message, content=content, stderr=stderr)

    def warning(self, message: str, *, content: str | None = None, stderr: bool = False) -> None:
        """Write a warning diagnostic."""

        self._write("WARN", message, content=content, stderr=stderr)

    def error(self, message: str, *, content: str | None = None, stderr: bool = False) -> None:
        """Write an error diagnostic."""

        self._write("ERROR", message, content=content, stderr=stderr)

    def _write(self, level: str, message: str, *, content: str | None, stderr: bool) -> None:
        line = self._format_line(level, message, content)
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except OSError as exc:
            if stderr:
                self._write_stderr(f"{line} log_write_failed={exc}")
            return
        if stderr and self.stderr is not None:
            self._write_stderr(line)

    def _write_stderr(self, line: str) -> None:
        if self.stderr is None:
            return
        try:
            self.stderr.write(line + "\n")
            self.stderr.flush()
        except OSError:
            return

    def _format_line(self, level: str, message: str, content: str | None) -> str:
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        sanitized_message = message.replace("\n", " ").strip()
        if content is None:
            return f"{timestamp} {level} {sanitized_message}"
        return f"{timestamp} {level} {sanitized_message} content={_brief_content(content)!r}"


def _brief_content(content: str) -> str:
    normalized = " ".join(content.split())
    if len(normalized) <= MAX_CONTENT_LOG_CHARS:
        return normalized
    return f"{normalized[:MAX_CONTENT_LOG_CHARS]}..."
