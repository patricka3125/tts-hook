# Kokoro TTS Codex Plugin

This directory is the proposed packageable Codex plugin unit.

## Shape

```text
codex/
  .codex-plugin/
    plugin.json
  hooks/
    hooks.json
  scripts/
    codex_session_start_tts_check.py
    codex_stop_tts.py
  src/
    tts_hook/
      __init__.py
      config.py
      kokoro.py
      playback.py
  config.example.toml
  README.md
```

The manifest points Codex at `hooks/hooks.json`. The hooks invoke Python scripts
that live inside the same plugin unit. The Python scripts should import shared
logic from `src/tts_hook`.

## Setup Notes

Assume hook commands in `hooks/hooks.json` are resolved relative to this plugin
root. The hook commands should therefore use paths like:

```text
python3 ./scripts/codex_stop_tts.py
```

The only default config location is plugin-local:

```text
tts-hook.toml
```

If `tts-hook.toml` is absent, the implementation should use code defaults that
match `config.example.toml`.

## Runtime Assumptions

- Kokoro API is already running.
- Health endpoint is `http://{host}:{port}/health`.
- Speech endpoint is `http://{host}:{port}/v1/audio/speech`.
- Voices endpoint is `http://{host}:{port}/v1/audio/voices`.
- Model is always `kokoro`.
- Response format is WAV for the first implementation.
- Playback is non-blocking by default.
