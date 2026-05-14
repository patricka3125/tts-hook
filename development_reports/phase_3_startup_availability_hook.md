# Phase 3 Startup Availability Hook

## Summary

Implemented the Codex `SessionStart` startup availability hook for the Kokoro TTS plugin. The hook reads Codex hook JSON from stdin, loads only plugin-local configuration, checks Kokoro health, validates the configured or default voice, and always returns valid hook JSON while continuing Codex.

No playback, stop-hook behavior, hotkey/runtime toggle behavior, or container lifecycle behavior was added.

## Files Created

- `/home/bajablast69/dev/tts-hook/codex/scripts/codex_session_start_tts_check.py`
- `/home/bajablast69/dev/tts-hook/codex/tests/test_session_start_hook.py`
- `/home/bajablast69/dev/tts-hook/codex/tests/fixtures/session_start/startup.json`
- `/home/bajablast69/dev/tts-hook/codex/tests/fixtures/session_start/resume.json`
- `/home/bajablast69/dev/tts-hook/codex/tests/fixtures/session_start/unavailable_api.json`
- `/home/bajablast69/dev/tts-hook/codex/tests/fixtures/session_start/invalid_voice.json`

## Acceptance Criteria Coverage

- `codex/scripts/codex_session_start_tts_check.py` reads hook JSON, loads plugin-local config through the Phase 2 loader, checks `/health`, validates `/v1/audio/voices`, and emits valid hook JSON.
- Startup failures return `{"continue": true, "systemMessage": "..."}` with warning-oriented text and exit `0`.
- Healthy Kokoro plus a valid configured/default voice returns only `{"continue": true}` without a warning.
- Health failures warn and continue without blocking.
- Voice endpoint failures or unreadable voice responses warn and continue.
- Invalid voices warn, name the configured voice, and tell the user to update `speech.voice` or remove it to use `am_liam`.
- Local JSON fixtures can be piped into the startup script without Codex.
- The hook does not start containers, stop containers, delete containers, play audio, or add runtime toggles.

## Validation

- `python3 -m compileall codex/src codex/scripts codex/tests` passed.
- `uv run --with pytest pytest codex/tests` passed with 27 tests.
- `for f in ./tests/fixtures/session_start/*.json; do HOME=$(mktemp -d) python3 ./scripts/codex_session_start_tts_check.py < "$f" >/tmp/tts-hook-fixture-output.json && python3 -m json.tool /tmp/tts-hook-fixture-output.json >/dev/null || exit 1; done` passed from `/home/bajablast69/dev/tts-hook/codex`.
- `python3 -m json.tool` validation passed for all four startup fixture files.
- `python3 -m pytest codex/tests` still fails because system Python has no `pytest` installed.

## Design Notes

- The script uses `scripts/_bootstrap.py` so it can import shared modules from `codex/src` without package installation.
- Hook stdin parse failures and config failures return warning JSON immediately; diagnostics go to stderr, never stdout.
- Health success is based on successful HTTP access through the shared Kokoro client. Voice validation accepts common response shapes: `{"voices": [...]}`, `{"data": [...]}`, plain string lists, and dictionaries with `id`, `name`, or `voice`.
- If the voice list cannot be read or parsed, the hook warns instead of silently skipping validation.
- Tests use a temporary local HTTP server rather than requiring a real Kokoro container.

## Review Feedback Response

1. Make the invalid configured voice warning more actionable.
   - Implemented. The warning now tells the user to update `speech.voice` in `tts-hook.toml`, or remove it to use `am_liam`.
2. Add a subprocess-level healthy-path fixture test.
   - Implemented. A new pytest case copies the plugin script and `src` tree to a temporary plugin root, writes plugin-local config pointing at a local test HTTP server, pipes a startup fixture through the real script process, and verifies `{"continue": true}` with no warning.
3. List the report commit in this development report.
   - Implemented. The commit list now includes both the implementation commit and the report commit.

## Review Revision Validation

- `python3 -m compileall codex/src codex/scripts codex/tests` passed.
- `uv run --with pytest pytest codex/tests` passed with 28 tests.
- `for f in ./tests/fixtures/session_start/*.json; do HOME=$(mktemp -d) python3 ./scripts/codex_session_start_tts_check.py < "$f" >/tmp/tts-hook-fixture-output.json && python3 -m json.tool /tmp/tts-hook-fixture-output.json >/dev/null || exit 1; done` passed from `/home/bajablast69/dev/tts-hook/codex`.
- `python3 -m pytest codex/tests` still fails because system Python has no `pytest` installed.

## Commit

- `a21153d Implement startup availability hook`
- `b8b3aca Add phase 3 development report`
