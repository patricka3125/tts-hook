# Kokoro TTS Codex Plugin

This directory is the packageable Codex plugin unit for speaking Codex final
responses through a local Kokoro-FastAPI server.

## Layout

```text
codex/
  .codex-plugin/
    plugin.json
  hooks/
    hooks.json
  config.example.toml
  README.md
src/
  tts_hook/
    config.py
    kokoro.py
    playback.py
    session_start.py
    stop.py
    tts_playback_supervisor.py
pyproject.toml
```

The manifest points Codex at `./hooks/hooks.json`. Manifest paths are resolved
relative to the plugin root.

Hook commands are different: Codex runs command hooks from the active session
`cwd`, not from the plugin root. For that reason, `hooks/hooks.json` launches
package console scripts through `uvx --from`:

```text
uvx --from 'git+https://github.com/patricka3125/tts-hook.git@main' tts-hook-startup
uvx --from 'git+https://github.com/patricka3125/tts-hook.git@main' tts-hook-stop
```

The packaged runtime entrypoints are defined in the repository-root
`pyproject.toml`, and the Python runtime source lives under repository-root
`src/tts_hook`. The `codex/` directory contains Codex plugin metadata and hook
configuration only.

## Requirements

- Codex CLI with plugin hooks enabled.
- `uv` available on `PATH`; `uvx` is used by the hook commands.
- Kokoro-FastAPI running locally, defaulting to `http://localhost:8880`.
- A host audio player on `PATH`; auto-detection tries `pw-play`, `paplay`,
  `ffplay`, then `aplay`.

## Install The Plugin

The personal marketplace entry should point at this Git-backed plugin:

```json
{
  "name": "tts-hook",
  "source": {
    "source": "git-subdir",
    "url": "https://github.com/patricka3125/tts-hook.git",
    "path": "./codex",
    "ref": "main"
  },
  "policy": {
    "installation": "INSTALLED_BY_DEFAULT",
    "authentication": "ON_INSTALL"
  },
  "category": "Productivity"
}
```

After changing the marketplace or plugin source, restart Codex, open
`/plugins`, install `tts-hook` from the personal marketplace, and enable it.

## Run Codex With The Plugin

Launch Codex with hook support and the plugin enabled:

```bash
codex --enable hooks --enable plugin_hooks -c 'plugins."tts-hook@local-personal".enabled=true'
```

On first use, `uvx` may need to fetch and build the package from GitHub. Later
runs should use uv's cache unless the source is refreshed.

## Manual Smoke Checks

Run the startup entrypoint with local source:

```bash
printf '{"hook_event_name":"SessionStart","source":"startup","cwd":"%s"}\n' "$PWD" \
  | uvx --from . tts-hook-startup
```

Run the stop entrypoint with local source:

```bash
printf '{"hook_event_name":"Stop","last_assistant_message":"Codex TTS smoke test.","cwd":"%s"}\n' "$PWD" \
  | uvx --from . tts-hook-stop
```

To test the same command shape used by the installed plugin, replace `./codex`
with:

```text
git+https://github.com/patricka3125/tts-hook.git@main
```

## Configuration

The current packaged runtime uses code defaults when launched through
`uvx --from`:

- host: `localhost`
- port: `8880`
- voice: `am_liam`
- speed: `1.0`
- playback: non-blocking auto player

`config.example.toml` documents the intended settings shape, but `uvx --from`
does not execute from the Codex plugin cache. A future iteration should add a
stable user config path or environment override if per-user settings are needed
with the Git-backed launcher.

## Playback Cancellation

The Stop hook writes the generated WAV and starts the packaged playback
supervisor with `python -m tts_hook.tts_playback_supervisor`. The supervisor
owns playback until the audio player exits, then removes the temporary WAV file.

Press Escape in the focused Codex terminal or tmux pane to cancel the current
playback. Cancellation is best-effort and terminal-scoped: it only affects the
audio player launched for the current hook result, and it depends on the
supervisor being able to read `/dev/tty`.

If `/dev/tty` is unavailable or cannot be configured for cbreak input, playback
continues normally without Escape cancellation. There is no fallback cancel
command or global hotkey.

The cancel key is fixed to Escape. It is not configurable.
