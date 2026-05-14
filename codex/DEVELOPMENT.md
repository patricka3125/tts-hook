# Codex Plugin Development

This document describes how to run the local development version of the Codex
plugin from this checkout.

For general repository development setup, see [../DEVELOPMENT.md](../DEVELOPMENT.md).

## Development Plugin Layout

The development plugin lives under:

```text
codex/development/
  .codex-plugin/
    plugin.json
  hooks/
    hooks.json
```

The development hooks run the repository checkout directly:

```text
uv run --project . tts-hook-startup
uv run --project . tts-hook-stop
```

Because these commands use `--project .`, start Codex from the repository root
when testing the development plugin.

## Local Marketplace Entry

Point your local Codex plugin marketplace at the development plugin directory.
Keep this marketplace file local to your machine; do not commit machine-specific
paths.

Use a local path to the development plugin, for example:

```json
{
  "name": "tts-hook",
  "source": {
    "source": "local",
    "path": "./codex/development"
  },
  "policy": {
    "installation": "INSTALLED_BY_DEFAULT",
    "authentication": "ON_INSTALL"
  },
  "category": "Productivity"
}
```

If your Codex marketplace requires an absolute path, use your own local checkout
path in that local-only marketplace file. Do not copy that path into tracked
repository files or documentation.

## Enable In Codex

After changing marketplace entries or plugin metadata:

1. Restart Codex so it reloads marketplace state.
2. Open `/plugins`.
3. Install and enable `Kokoro TTS Hook (Development)`.
4. Start Codex from the repository root while testing this development plugin.

The development plugin display name is intentionally different from the packaged
plugin:

```text
Kokoro TTS Hook (Development)
```

That makes it easier to confirm which plugin is enabled.

## Smoke Checks

Run the startup hook through the same project command shape used by the
development plugin:

```bash
printf '{"hook_event_name":"SessionStart","source":"startup","cwd":"%s"}\n' "$PWD" \
  | uv run --project . tts-hook-startup
```

Run the stop hook:

```bash
printf '{"hook_event_name":"Stop","last_assistant_message":"Codex TTS smoke test.","cwd":"%s"}\n' "$PWD" \
  | uv run --project . tts-hook-stop
```

The default hook log path is:

```text
~/.codex/tts-hook.log
```

