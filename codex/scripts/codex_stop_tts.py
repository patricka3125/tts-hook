#!/usr/bin/env python3
"""Compatibility wrapper for the packaged Stop entrypoint."""

from __future__ import annotations

import _bootstrap

_bootstrap.ensure_src_on_path()

from tts_hook.stop import extract_assistant_message, main, speak_last_assistant_message, write_unique_wav  # noqa: E402,F401


if __name__ == "__main__":
    raise SystemExit(main())
