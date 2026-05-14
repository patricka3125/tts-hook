# tts-hook

Design notes for a Codex `Stop` hook that reads the final assistant message,
sends it to a local Kokoro TTS API, and plays the generated audio on the host.

This repo is currently a brainstorm/design workspace. Implementation comes
after the hook scope and behavior are settled.

## Local context

- Kokoro API: `http://localhost:8880`
- Speech endpoint: `POST /v1/audio/speech`
- Preferred first target: Codex `SessionStart` check plus `Stop` speech hook
- Host audio target: Fedora desktop session audio

## Docs

- [Codex hook design](docs/codex-hook-design.md)
- [Escape cancel playback design](docs/escape-cancel-playback-design.md)
- [Codex plugin scaffold](codex/README.md)

## Proposed config

- [Codex plugin config example](codex/config.example.toml)
