#!/usr/bin/env python3
"""Compatibility wrapper for the packaged Stop entrypoint."""

from __future__ import annotations

from pathlib import Path
from typing import TextIO

import _bootstrap

_bootstrap.ensure_src_on_path()

from tts_hook.stop import extract_assistant_message, speak_last_assistant_message, write_unique_wav  # noqa: E402,F401
from tts_hook.stop import main as _main  # noqa: E402


def main(
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    plugin_root: Path | None = None,
) -> int:
    root = plugin_root or Path(__file__).resolve().parents[1]
    return _main(stdin=stdin, stdout=stdout, stderr=stderr, plugin_root=root)


if __name__ == "__main__":
    raise SystemExit(main())
