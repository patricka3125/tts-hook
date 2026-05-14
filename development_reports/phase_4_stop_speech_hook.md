# Phase 4 Stop Speech Hook

## Summary

Implemented the Codex `Stop` hook that speaks `last_assistant_message` through Kokoro and launches host audio playback. The hook reads Stop JSON, extracts the full assistant message with only outer whitespace removed, posts it to Kokoro, writes the WAV response to a unique temporary `.wav` file, starts playback, and always returns valid hook JSON.

No truncation, summarization, hotkey/runtime toggle behavior, or container lifecycle behavior was added.

## Files Created

- `/home/bajablast69/dev/tts-hook/codex/scripts/codex_stop_tts.py`
- `/home/bajablast69/dev/tts-hook/codex/src/tts_hook/playback.py`
- `/home/bajablast69/dev/tts-hook/codex/tests/test_stop_hook.py`
- `/home/bajablast69/dev/tts-hook/codex/tests/fixtures/stop/empty.json`
- `/home/bajablast69/dev/tts-hook/codex/tests/fixtures/stop/minimal.json`
- `/home/bajablast69/dev/tts-hook/codex/tests/fixtures/stop/normal.json`
- `/home/bajablast69/dev/tts-hook/codex/tests/fixtures/stop/long_multiparagraph.json`
- `/home/bajablast69/dev/tts-hook/codex/tests/fixtures/stop/malformed.txt`

## Acceptance Criteria Coverage

- `codex/scripts/codex_stop_tts.py` reads hook JSON, loads plugin-local config, extracts `last_assistant_message`, sends the full message to Kokoro, writes a unique temp WAV, starts playback, and emits `{"continue": true}`.
- Empty or missing assistant messages are skipped before any Kokoro call and still return valid hook JSON.
- Malformed hook input, config errors, Kokoro request failures, WAV write failures, and playback failures return valid hook JSON and write diagnostics only to stderr/log.
- Multi-paragraph messages are preserved in the Kokoro `input` payload with no truncation or summarization.
- The speech request continues to use the shared baked-in model `kokoro`, WAV response format, `stream = false`, configured voice, and configured speed.
- Playback auto-selects `pw-play`, `paplay`, `ffplay -nodisp -autoexit`, or `aplay`, suppresses child stdout/stderr, and runs in the background when `blocking = false`.
- If no playback command exists, the hook logs a warning and still returns valid hook JSON.
- Stop fixtures can be piped into the script without Codex.

## Validation

- `python3 -m compileall codex/src codex/scripts codex/tests` passed.
- `uv run --with pytest pytest codex/tests` passed with 40 tests.
- `python3 -m json.tool` passed for the four JSON Stop fixtures.
- Isolated plugin-copy fixture pipe validation passed for all Stop fixtures, including malformed input:
  - `tmp=$(mktemp -d); mkdir -p "$tmp/codex"; cp -R codex/scripts codex/src codex/tests "$tmp/codex/"; printf '[kokoro]\nhost = "127.0.0.1"\nport = 9\n\n[logging]\npath = "%s/hook.log"\n' "$tmp" > "$tmp/codex/tts-hook.toml"; for f in "$tmp"/codex/tests/fixtures/stop/*.json "$tmp"/codex/tests/fixtures/stop/malformed.txt; do HOME="$tmp/home" /usr/bin/python3 "$tmp/codex/scripts/codex_stop_tts.py" < "$f" > "$tmp/out.json" || exit 1; /usr/bin/python3 -m json.tool "$tmp/out.json" >/dev/null || exit 1; done`
- `rg -n "max_chars|hotkey|runtime toggle|docker|podman|start.*container|stop.*container|delete.*container" codex/src codex/scripts codex/config.example.toml || true` returned no matches.
- `python3 -m pytest codex/tests` still fails because system Python has no `pytest` installed.

## Design Notes

- Playback is implemented in `codex/src/tts_hook/playback.py` so command selection can be tested independently from the Stop hook.
- The hook writes generated WAV data with `NamedTemporaryFile(delete=False)`. It does not run broad cleanup or destructive cleanup actions.
- Tests use a temporary local HTTP server for Kokoro and fake playback executables on `PATH`; no real Kokoro service or host audio player is required for validation.
- Background playback redirects stdin, stdout, and stderr to avoid polluting the Codex hook stdout contract.

## Commit

- `966f127 Implement stop speech hook`
