"""Import helper for plugin-bundled hook scripts."""

from __future__ import annotations

from pathlib import Path
import sys


def ensure_src_on_path() -> None:
    """Allow scripts under ``codex/scripts`` to import ``tts_hook``."""

    plugin_root = Path(__file__).resolve().parents[1]
    src = plugin_root / "src"
    src_text = str(src)
    if src_text not in sys.path:
        sys.path.insert(0, src_text)

