#!/usr/bin/env python3
"""Compatibility wrapper for the packaged SessionStart entrypoint."""

from __future__ import annotations

from pathlib import Path
from typing import TextIO

import _bootstrap

_bootstrap.ensure_src_on_path()

from tts_hook.session_start import check_startup, extract_voice_names  # noqa: E402,F401
from tts_hook.session_start import main as _main  # noqa: E402


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
