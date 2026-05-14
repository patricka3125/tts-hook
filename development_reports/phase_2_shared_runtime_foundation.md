# Phase 2 Shared Runtime Foundation

## Summary

Implemented the shared Python runtime foundation for the Codex Kokoro TTS plugin under `codex/`. This phase adds reusable modules for plugin-local config loading, baked-in Kokoro URL and payload construction, hook JSON I/O, diagnostics logging, and Kokoro HTTP access. No startup hook behavior, stop hook behavior, playback implementation, container lifecycle behavior, hotkeys, or runtime toggles were added.

## Files Created

- `/home/bajablast69/dev/tts-hook/codex/scripts/_bootstrap.py`
- `/home/bajablast69/dev/tts-hook/codex/src/tts_hook/__init__.py`
- `/home/bajablast69/dev/tts-hook/codex/src/tts_hook/config.py`
- `/home/bajablast69/dev/tts-hook/codex/src/tts_hook/hook_io.py`
- `/home/bajablast69/dev/tts-hook/codex/src/tts_hook/kokoro.py`
- `/home/bajablast69/dev/tts-hook/codex/src/tts_hook/logging.py`
- `/home/bajablast69/dev/tts-hook/codex/tests/test_runtime_foundation.py`

## Acceptance Criteria Coverage

- Shared modules are importable by scripts under `codex/scripts/` without installing a package via `scripts/_bootstrap.py`.
- Config loading reads only `/home/bajablast69/dev/tts-hook/codex/tts-hook.toml` for the real plugin root, plus code defaults. No home config lookup or `CODEX_TTS_CONFIG` support was implemented.
- URL and payload helpers bake in `http`, `/health`, `/v1/audio/speech`, `/v1/audio/voices`, model `kokoro`, WAV response format, and `stream = false`.
- Config tests cover no config, partial plugin-local config, all supported keys, and ignored stable integration constants.
- Default URL tests verify `http://localhost:8880/health`, `http://localhost:8880/v1/audio/speech`, and `http://localhost:8880/v1/audio/voices`.
- Hook I/O helpers parse valid JSON and return safe warning results for empty, invalid, or non-object stdin without writing diagnostics to stdout.
- Logging creates parent directories, writes no stdout output, supports stderr only when requested, and truncates optional logged content to keep assistant content brief.
- Kokoro client helpers expose `KokoroResult`, use configured connect and read timeouts separately, and build speech requests with full input text, configured voice and speed, model `kokoro`, WAV format, and `stream = false`.

## Validation

- `python3 -m compileall codex/src codex/scripts codex/tests` passed.
- `tmpenv=$(mktemp -d) && python3 -m venv "$tmpenv/venv" && "$tmpenv/venv/bin/python" -m pip install --quiet pytest && "$tmpenv/venv/bin/python" -m pytest codex/tests && rm -rf "$tmpenv"` passed with 12 tests.
- Review revision validation:
  - `python3 -m compileall codex/src codex/scripts codex/tests` passed.
  - `uv run --with pytest pytest codex/tests` passed with 17 tests.
  - `python3 -m pytest codex/tests` still fails because system Python has no pytest installed.

System Python does not currently have pytest installed, so `python3 -m pytest codex/tests` fails with `No module named pytest`. Validation was performed in a temporary virtualenv to avoid changing global Python state.

## Review Feedback Response

1. Make logging best-effort for unwritable log paths.
   - Implemented. `HookLogger` now catches `OSError` from parent directory creation and file writes. It returns without raising, and when stderr diagnostics were requested it emits a concise stderr fallback that includes `log_write_failed=...`.
2. Include method/URL context in Kokoro transport errors.
   - Implemented. Transport and non-2xx errors now include context such as `GET http://127.0.0.1:9999/health failed: ...`.
3. Add regression tests for non-object stdin plus home/env config ignoring.
   - Implemented. Tests now cover JSON arrays and strings as safe warning results, and verify `HOME/.codex/tts-hook.toml` plus `CODEX_TTS_CONFIG` are ignored when no plugin-local config exists.

## Design Notes

- The runtime stays dependency-free for hook execution by using only the Python standard library.
- `http.client` is used instead of `urllib` so connect and read timeouts can be applied independently.
- Unknown config keys are ignored intentionally, which prevents stable integration constants from becoming configurable during this phase.
- Playback configuration is represented as a small shared config type only; actual playback remains Phase 4.

## Commit

- `81d529e Implement shared TTS hook runtime`
- `e3b50e7 Address phase 2 runtime review feedback`
