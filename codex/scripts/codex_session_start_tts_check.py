#!/usr/bin/env python3
"""Compatibility wrapper for the packaged SessionStart entrypoint."""

from __future__ import annotations

import _bootstrap

_bootstrap.ensure_src_on_path()

from tts_hook.session_start import check_startup, extract_voice_names, main  # noqa: E402,F401


if __name__ == "__main__":
    raise SystemExit(main())
