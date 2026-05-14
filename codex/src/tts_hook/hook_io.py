"""Codex hook JSON input and output helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TextIO

import json
import sys


@dataclass(frozen=True)
class HookInputResult:
    """Parsed hook input plus a non-fatal warning when input is unusable."""

    payload: dict[str, Any]
    warning: str | None = None

    @property
    def ok(self) -> bool:
        """Return true when stdin contained a JSON object."""

        return self.warning is None


def read_hook_json(stdin: TextIO | None = None) -> HookInputResult:
    """Read a Codex hook JSON object from stdin.

    Empty, malformed, or non-object input returns a safe warning result. This
    helper does not write diagnostics, which keeps hook stdout reserved for the
    hook response JSON.
    """

    stream = stdin or sys.stdin
    raw = stream.read()
    if not raw.strip():
        return HookInputResult(payload={}, warning="Hook stdin was empty")

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        return HookInputResult(payload={}, warning=f"Hook stdin was not valid JSON: {exc.msg}")

    if not isinstance(payload, dict):
        return HookInputResult(payload={}, warning="Hook stdin JSON was not an object")

    return HookInputResult(payload=payload)


def continue_result(system_message: str | None = None) -> dict[str, Any]:
    """Build a hook-compatible continue response."""

    result: dict[str, Any] = {"continue": True}
    if system_message:
        result["systemMessage"] = system_message
    return result


def write_hook_json(result: dict[str, Any], stdout: TextIO | None = None) -> None:
    """Write hook response JSON to stdout and terminate with a newline."""

    stream = stdout or sys.stdout
    json.dump(result, stream, separators=(",", ":"))
    stream.write("\n")
    stream.flush()

