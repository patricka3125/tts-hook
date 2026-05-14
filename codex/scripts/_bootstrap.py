"""Import helper for legacy hook script wrappers."""

from __future__ import annotations

from pathlib import Path
import sys


def ensure_src_on_path() -> None:
    """Allow scripts under ``codex/scripts`` to import root package sources."""

    repo_root = Path(__file__).resolve().parents[2]
    src = repo_root / "src"
    src_text = str(src)
    if src_text not in sys.path:
        sys.path.insert(0, src_text)
