# Codex Stop Hook TTS Design

## Goal

When a Codex turn stops, speak the full final assistant message through the
local Kokoro-FastAPI container.

The first version should be boring and reliable:

1. Codex runs a `SessionStart` hook on startup or resume.
2. The startup hook reads config and checks that the Kokoro API is available.
3. Codex runs a `Stop` hook when a turn completes.
4. The stop hook reads JSON from stdin.
5. The stop hook extracts `last_assistant_message`.
6. The stop hook sends text to the configured Kokoro speech endpoint.
7. The stop hook plays the returned audio through the host audio stack.
8. Hook scripts print valid hook JSON to stdout and write diagnostics elsewhere.

## Current External Contracts

### Codex hook contract

Official Codex hook docs describe hooks in `hooks.json` or inline `config.toml`.
`SessionStart` can match `startup|resume`. `Stop` runs at turn scope. Command
hooks receive JSON on stdin. `Stop` must emit JSON on stdout when it exits `0`;
plain text is invalid for that event. The `Stop` input includes
`last_assistant_message`.

For repo-local hooks, the docs recommend resolving paths from the git root
because Codex may start from a subdirectory.

Reference: <https://developers.openai.com/codex/hooks>

### Kokoro API contract

The running local API exposes an OpenAI-compatible speech endpoint:

```http
POST http://localhost:8880/v1/audio/speech
Content-Type: application/json
```

Useful request fields:

```json
{
  "model": "kokoro",
  "input": "Text to speak",
  "voice": "am_michael",
  "response_format": "wav",
  "stream": false,
  "speed": 1.0
}
```

Supported response formats in the local schema are `mp3`, `opus`, `aac`,
`flac`, `wav`, and `pcm`. The schema notes that `pcm` is raw 16-bit audio
without a header. Kokoro examples use 24 kHz mono PCM for streaming playback.

The local API also exposes:

```http
GET /health
GET /v1/audio/voices
```

The startup hook should use `/health` to detect API availability and
`/v1/audio/voices` to validate the configured voice when possible.

## Proposed Files

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

`config.py` should be shared by both hook scripts. That keeps URL construction,
defaults, timeouts, and voice settings identical between startup validation and
turn-end speech.

## Codex Plugin Shape

The Codex-facing implementation should live under `codex/`, with `codex/` as
the plugin root. The packageable unit needs a plugin manifest:

```text
codex/.codex-plugin/plugin.json
```

Initial manifest shape:

```json
{
  "name": "tts-hook",
  "version": "0.1.0",
  "description": "Speak Codex final responses through a local Kokoro-FastAPI server.",
  "hooks": "./hooks/hooks.json",
  "interface": {
    "displayName": "Kokoro TTS Hook",
    "shortDescription": "Speak Codex responses with local Kokoro TTS.",
    "longDescription": "Uses Codex hooks to check Kokoro availability on startup and play assistant responses when a turn stops.",
    "developerName": "Local",
    "category": "Productivity",
    "capabilities": ["Read"]
  }
}
```

Lifecycle hook config should live at:

```text
codex/hooks/hooks.json
```

Assumption: commands in plugin-bundled `hooks/hooks.json` are resolved relative
to the plugin root. Use relative commands like `python3 ./scripts/...` and
iterate if this assumption turns out to be incorrect in Codex.

## Config File

Use TOML for the config file. Python 3.11+ can parse TOML with the standard
library `tomllib`, so this avoids a dependency for normal Fedora installs.

### Minimum Exposed Config Evaluation

Expose only values that are expected to vary for a normal local install:

- `kokoro.host`: needed when the API is not on the same host, or when `localhost`
  resolves differently under a future runtime.
- `kokoro.port`: needed because the Kokoro container port can be remapped.
- `speech.voice`: personal preference and the most likely thing to tune.
  If omitted, the implementation should use `am_liam`.
- `speech.speed`: personal preference and accessibility tuning.
- `playback.player`: needed if `auto` chooses the wrong host audio tool.
- `playback.blocking`: defaults to `false`; keep it configurable in case a
  later user explicitly wants synchronous playback for debugging.
- `timeouts.connect_seconds` and `timeouts.read_seconds`: useful for machines
  with slower first-token TTS generation or network hiccups.
- `logging.path`: useful for debugging hook behavior without polluting stdout.

Do not expose stable integration constants in the user config:

- `model`: always `kokoro` for this project.
- `scheme`: always `http` for localhost development.
- `api_prefix`: always `/v1`.
- `health_path`: always `/health`.
- `speech_path`: always `/audio/speech`.
- `voices_path`: always `/audio/voices`.
- `response_format`: use `wav` for the MVP.
- `stream`: use non-streaming for the MVP.
- `startup_health_seconds`: use the normal connect/read timeout pair.
- `max_chars`: no truncation for the first implementation; speak the full
  `last_assistant_message`.

These can still be code constants. If one needs to vary later, promote it to
config after the actual need appears.

Config resolution:

```text
<plugin-root>/tts-hook.toml
```

The plugin should ship `config.example.toml`. The user-owned config should be
plugin-local at `codex/tts-hook.toml` and ignored by git. If that file is
absent, use code defaults.

Initial config shape:

```toml
[kokoro]
host = "localhost"
port = 8880

[speech]
voice = "am_liam"
speed = 1.0

[playback]
player = "auto"
blocking = false

[timeouts]
connect_seconds = 2.0
read_seconds = 20.0

[logging]
path = "~/.codex/tts-hook.log"
```

Code constants:

```text
KOKORO_SCHEME = "http"
KOKORO_API_PREFIX = "/v1"
KOKORO_MODEL = "kokoro"
HEALTH_PATH = "/health"
SPEECH_PATH = "/audio/speech"
VOICES_PATH = "/audio/voices"
RESPONSE_FORMAT = "wav"
STREAM = false
```

Default URL construction, using configured `host` and `port` plus code
constants:

```text
base_url = "http://{host}:{port}"
health_url = "{base_url}/health"
speech_url = "{base_url}/v1/audio/speech"
voices_url = "{base_url}/v1/audio/voices"
```

With defaults, those resolve to:

```text
http://localhost:8880/health
http://localhost:8880/v1/audio/speech
http://localhost:8880/v1/audio/voices
```

Do not add environment-variable config overrides in the first implementation.

## Startup Hook

Build one Python startup script:

```text
scripts/codex_session_start_tts_check.py
```

Initial behavior:

- Read hook JSON from stdin.
- Load config.
- Build `health_url` from configured `host` and `port` plus the baked-in
  `/health` path.
- Send `GET /health` with a short timeout.
- If healthy, optionally call `GET /v1/audio/voices` and verify the configured
  voice exists. If no voice is configured, use `am_liam`.
- Write a concise `systemMessage` if Kokoro is unavailable or the voice is
  invalid.
- Return `{"continue": true}` so startup check failures do not block Codex
  while we iterate.
- Write detailed diagnostics to stderr or the configured log file.

The startup hook should not start containers in the MVP. Starting containers
from a hook adds lifecycle and failure-mode complexity. The first version should
only verify that the API is already reachable and tell the user what is wrong.

Possible later behavior:

- Optional `auto_start_command`, disabled by default.
- Optional warmup speech phrase to verify audio playback, disabled by default.

## Stop Hook

Build one Python stop script:

```text
scripts/codex_stop_tts.py
```

Initial behavior:

- Read all stdin as JSON.
- Load config.
- Extract `last_assistant_message`.
- Ignore empty messages.
- Strip markdown fences and excessive whitespace only lightly.
- Speak the full message. Do not truncate in the first implementation.
- POST to Kokoro using configured host, port, voice, and speed. The model,
  endpoint path, response format, and non-streaming mode are baked in for the
  MVP.
- Write audio to a temporary WAV file.
- Spawn playback in the background and return immediately.
- Play the temp WAV with the first available host command:
  - `pw-play`
  - `paplay`
  - `ffplay -nodisp -autoexit`
  - `aplay`
- Return hook JSON on stdout even if TTS fails.
- Write errors to stderr or a log file, never stdout.

MVP stdout shape:

```json
{"continue": true}
```

MVP hook config:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup|resume",
        "hooks": [
          {
            "type": "command",
            "command": "python3 ./scripts/codex_session_start_tts_check.py",
            "timeout": 5,
            "statusMessage": "Checking Kokoro TTS"
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 ./scripts/codex_stop_tts.py",
            "timeout": 5,
            "statusMessage": "Speaking final response"
          }
        ]
      }
    ]
  }
}
```

Feature flag needed in `~/.codex/config.toml` or project config:

```toml
[features]
codex_hooks = true
```

## Why WAV First

WAV avoids adding Python audio dependencies in the first pass. The hook can rely
on the desktop audio tools already present on Fedora. It is less low-latency
than streaming PCM, but the failure modes are easier to understand.

After the MVP works, a streaming mode can request `response_format: "pcm"` and
feed 24 kHz mono int16 chunks directly to an audio process or a Python audio
library.

## Configuration Surface

The config file is plugin-local only:

```text
<plugin-root>/tts-hook.toml
```

Defaults should be usable with no config file beyond the Kokoro API running on
`http://localhost:8880`.

Do not add a hotkey or runtime enable toggle for the first version. If the
plugin hook is enabled, playback should occur.

## Reliability Rules

- Hook failure should not block Codex unless explicitly configured later.
- Startup failures should warn only. They should not stop Codex.
- Network timeout should be short: about 2 seconds to connect, 20 seconds to
  generate.
- Playback failure should not fail the hook.
- The hook should be re-entrant because multiple hooks can run concurrently.
- Temporary files should be unique and cleaned after playback when possible.
- Logs should redact or truncate content because assistant messages may contain
  sensitive project text.

## Text Selection

The simplest text source is the entire `last_assistant_message`. That may be too
verbose for long implementation summaries.

Potential later modes:

- `full`: speak the whole message.
- `summary`: speak the first paragraph plus verification status.
- `final_only`: speak only final responses, not intermediate updates, if the
  hook event provides enough context.
- `notify`: speak a fixed phrase like "Codex finished" and optionally the first
  sentence.

For the MVP, use `full` with no truncation. If long responses become annoying,
add a later speech policy after observing real use.

## Host Integration

The Kokoro container is exposed on host port `8880`, so the hook does not need
container networking or volume mounts. It only needs HTTP access to localhost.

Audio playback happens on the host. That avoids bridging PipeWire/PulseAudio
into the container.

## Decisions

- Do not solve hook installation yet. Keep implementation under `codex/` and
  include setup guidance for Codex.
- Use a packageable Codex plugin shape with `.codex-plugin/plugin.json`.
- Startup failures warn only.
- Speak the full assistant message with no truncation.
- Playback is non-blocking. The hook spawns playback and returns immediately.
- If no voice is configured, default to `am_liam`.
- Do not add a hotkey or runtime toggle yet. If the hook is enabled, playback
  occurs.
- Assume hook command paths in `hooks/hooks.json` are relative to the plugin
  root.
- Use plugin-local config only: `<plugin-root>/tts-hook.toml`.

## Implementation Plan

Multi-phase implementation plan derived from this design document. Phases are sequential; tasks within a phase are independent.

### Phase 1: Packageable Plugin Scaffold

**Goal:** Establish the Codex plugin unit described in `Proposed Files` and `Codex Plugin Shape`, with valid metadata and hook declarations under `codex/`.

**Acceptance Criteria:**
- `codex/` is the plugin root and contains `.codex-plugin/plugin.json`, `hooks/hooks.json`, `config.example.toml`, and setup notes.
- Plugin metadata and hook JSON parse successfully with standard JSON tooling.
- Hook commands assume paths are relative to the plugin root, matching the decision in `Decisions`.

**Depends on:** None

**Tasks:**

- **Validate Plugin Manifest**
  - **Description:** Ensure `codex/.codex-plugin/plugin.json` contains the plugin name, version, description, interface metadata, and `hooks` pointer described in `Codex Plugin Shape`.
  - **Acceptance Criteria:** `python3 -m json.tool codex/.codex-plugin/plugin.json` succeeds, and the manifest points to `./hooks/hooks.json`.

- **Validate Lifecycle Hook Config**
  - **Description:** Ensure `codex/hooks/hooks.json` declares `SessionStart` with `startup|resume` and `Stop` with relative commands for `./scripts/codex_session_start_tts_check.py` and `./scripts/codex_stop_tts.py`, as shown in `MVP hook config`.
  - **Acceptance Criteria:** `python3 -m json.tool codex/hooks/hooks.json` succeeds, and both hook commands are plugin-root relative.

- **Finalize Plugin-Local Config Example**
  - **Description:** Keep `codex/config.example.toml` aligned with `Config File` and `Configuration Surface`: host, port, voice, speed, playback, timeouts, and logging only.
  - **Acceptance Criteria:** The example contains no configurable model, scheme, API paths, response format, stream flag, truncation setting, or environment-variable override.

- **Document Plugin Setup Assumptions**
  - **Description:** Update `codex/README.md` so it states that hook command paths are assumed plugin-root relative and `tts-hook.toml` is the only default config location.
  - **Acceptance Criteria:** The README describes the plugin shape, runtime assumptions, config location, and no longer recommends absolute hook command paths.

### Phase 2: Shared Runtime Foundation

**Goal:** Implement reusable Python modules under `codex/src/tts_hook/` for config loading, URL construction, hook I/O, logging, and Kokoro HTTP access. This phase supports both hooks without implementing hook-specific behavior yet.

**Acceptance Criteria:**
- Shared modules can be imported by scripts under `codex/scripts/` without installing a package.
- Config loading uses only plugin-local `tts-hook.toml` plus code defaults, as required by `Config File`.
- URL construction always bakes in `http`, `/health`, `/v1/audio/speech`, `/v1/audio/voices`, model `kokoro`, WAV response format, and non-streaming mode.

**Depends on:** Phase 1

**Tasks:**

- **Implement Config Loader**
  - **Description:** Create `codex/src/tts_hook/config.py` with defaults matching `codex/config.example.toml`, TOML parsing via `tomllib`, plugin-root config resolution for `tts-hook.toml`, and fallback to code defaults when the file is absent.
  - **Acceptance Criteria:** Loading succeeds with no config file, with a partial plugin-local config, and with all supported keys; unsupported stable integration constants are not read from config.

- **Implement URL and Payload Constants**
  - **Description:** Add code constants and helpers for the Kokoro endpoints described in `Kokoro API contract` and `Config File`: health URL, speech URL, voices URL, model `kokoro`, response format `wav`, and `stream = false`.
  - **Acceptance Criteria:** Helpers produce `http://localhost:8880/health`, `http://localhost:8880/v1/audio/speech`, and `http://localhost:8880/v1/audio/voices` with default config.

- **Implement Hook I/O Helpers**
  - **Description:** Add helpers for reading hook JSON from stdin and writing valid hook JSON to stdout, following `Codex hook contract` and the `MVP stdout shape`.
  - **Acceptance Criteria:** Helpers parse valid JSON, tolerate empty or invalid stdin by returning a safe warning result, and never write diagnostics to stdout.

- **Implement Logging Helper**
  - **Description:** Add a logging utility that writes diagnostics to the configured log path from `Config File` and can also write concise details to stderr.
  - **Acceptance Criteria:** Logs are written without creating stdout noise, parent directories are created when needed, and logged assistant content is omitted or kept brief enough to satisfy `Reliability Rules`.

- **Implement Kokoro HTTP Client**
  - **Description:** Create `codex/src/tts_hook/kokoro.py` with functions for `GET /health`, `GET /v1/audio/voices`, and `POST /v1/audio/speech` using the shared config, URL helpers, and timeout settings.
  - **Acceptance Criteria:** Client functions expose clear success/error results, use configured connect/read timeouts, and build the speech request with full input text, configured voice, configured speed, model `kokoro`, WAV format, and non-streaming mode.

### Phase 3: Startup Availability Hook

**Goal:** Implement `SessionStart` behavior from `Startup Hook`: warn when Kokoro is unavailable or the voice is invalid, but never block Codex.

**Acceptance Criteria:**
- `codex/scripts/codex_session_start_tts_check.py` reads hook JSON, loads plugin-local config, checks health, validates the configured or default voice, and returns valid JSON.
- Startup failures produce a warning-oriented `systemMessage` and still continue.
- The hook does not start containers or play audio.

**Depends on:** Phase 2

**Tasks:**

- **Create Startup Script Entrypoint**
  - **Description:** Add `codex/scripts/codex_session_start_tts_check.py` that imports shared modules from `codex/src/tts_hook`, reads stdin JSON, and always emits hook-compatible JSON.
  - **Acceptance Criteria:** Running the script with a minimal `SessionStart` fixture exits `0` and prints valid JSON to stdout.

- **Add Health Check Behavior**
  - **Description:** Call Kokoro `GET /health` using the configured host and port, as required by `Startup Hook` and `Kokoro API contract`.
  - **Acceptance Criteria:** When health is reachable and returns healthy, no warning is emitted; when unavailable, the hook emits a concise warning and continues.

- **Add Voice Validation Behavior**
  - **Description:** Use `GET /v1/audio/voices` to validate the configured voice when health succeeds, defaulting to `am_liam` when no voice is specified.
  - **Acceptance Criteria:** Valid voices pass silently; invalid voices produce a warning that names the configured voice and default behavior without blocking Codex.

- **Add Startup Fixtures**
  - **Description:** Add local JSON fixtures for startup, resume, unavailable API, and invalid voice scenarios.
  - **Acceptance Criteria:** Fixtures can be piped into the startup script for deterministic local testing without Codex.

### Phase 4: Stop Speech Hook

**Goal:** Implement `Stop` behavior from `Stop Hook`: speak the full `last_assistant_message` through Kokoro, spawn host playback, and return immediately with valid hook JSON.

**Acceptance Criteria:**
- `codex/scripts/codex_stop_tts.py` extracts `last_assistant_message`, sends the full message to Kokoro, writes a unique temp WAV, spawns playback, and exits without waiting for playback when `blocking = false`.
- Empty messages and Kokoro/playback failures never break the Codex hook contract.
- No truncation, summarization, hotkey, or runtime enable toggle is implemented.

**Depends on:** Phase 2

**Tasks:**

- **Create Stop Script Entrypoint**
  - **Description:** Add `codex/scripts/codex_stop_tts.py` that imports shared modules, reads `Stop` JSON, and always emits `{"continue": true}` on stdout.
  - **Acceptance Criteria:** Running the script with an empty or minimal `Stop` fixture exits `0`, writes valid JSON to stdout, and writes diagnostics only to stderr/log.

- **Extract Full Assistant Message**
  - **Description:** Extract `last_assistant_message` exactly as the speech source, applying only light whitespace cleanup described in `Stop Hook` and no truncation.
  - **Acceptance Criteria:** Multi-paragraph messages are preserved, empty messages are skipped, and no `max_chars` policy exists in code or config.

- **Generate WAV From Kokoro**
  - **Description:** POST the full message to `/v1/audio/speech` with configured voice and speed, baked-in model `kokoro`, response format `wav`, and `stream = false`.
  - **Acceptance Criteria:** A successful Kokoro response is written to a unique temporary `.wav` file, and request failures are logged without failing the hook.

- **Implement Non-Blocking Playback**
  - **Description:** Add `codex/src/tts_hook/playback.py` to choose `pw-play`, `paplay`, `ffplay -nodisp -autoexit`, or `aplay` when `player = "auto"`, then spawn playback in the background by default.
  - **Acceptance Criteria:** The hook returns before playback completes when `blocking = false`; if no player exists, it logs a warning and still returns valid hook JSON.

- **Add Stop Fixtures**
  - **Description:** Add local JSON fixtures covering a normal assistant response, an empty message, a long multi-paragraph message, and malformed input.
  - **Acceptance Criteria:** Fixtures can be piped into the stop script to validate stdout, logging, Kokoro call behavior, and playback spawning.

### Phase 5: Local Verification Against Kokoro

**Goal:** Prove the hooks work against the running local Kokoro-FastAPI container and Fedora host audio tools before testing inside Codex.

**Acceptance Criteria:**
- Startup and stop scripts work from the plugin root with relative paths, matching the `Codex Plugin Shape` assumption.
- Kokoro health, voice validation, speech generation, and non-blocking playback all work locally.
- Failures are logged and surfaced as warnings without blocking.

**Depends on:** Phase 3 and Phase 4

**Tasks:**

- **Run Static Validation**
  - **Description:** Validate JSON files, Python syntax, and import paths for all plugin files.
  - **Acceptance Criteria:** JSON validation succeeds, Python files compile, and both scripts can import `tts_hook` modules when run from `codex/`.

- **Verify Startup Hook Locally**
  - **Description:** Pipe startup fixtures into `python3 ./scripts/codex_session_start_tts_check.py` from `codex/`.
  - **Acceptance Criteria:** Healthy Kokoro produces a continue result, unavailable Kokoro produces a warning continue result, and invalid voice produces a warning continue result.

- **Verify Stop Hook Locally**
  - **Description:** Pipe stop fixtures into `python3 ./scripts/codex_stop_tts.py` from `codex/` with the local Kokoro API running.
  - **Acceptance Criteria:** The hook returns immediately with valid JSON, generates audio for the full message, and starts host playback.

- **Verify Failure Handling**
  - **Description:** Test stopped Kokoro, invalid host/port, invalid voice, and missing playback command scenarios.
  - **Acceptance Criteria:** Each failure logs a useful diagnostic, returns valid hook JSON, and does not leave the terminal stdout polluted.

### Phase 6: Codex Integration Trial

**Goal:** Exercise the packageable plugin scaffold inside Codex with `SessionStart` and `Stop` lifecycle events, then document any adjustments needed for actual plugin behavior.

**Acceptance Criteria:**
- Codex can load the plugin metadata and hook configuration from `codex/`.
- `SessionStart` warnings and `Stop` playback behavior work in a real Codex session.
- If plugin-root relative hook command paths are wrong, the command wrapper is adjusted and documented.

**Depends on:** Phase 5

**Tasks:**

- **Enable Plugin for Local Trial**
  - **Description:** Follow Codex plugin setup guidance for a local plugin unit using `codex/.codex-plugin/plugin.json` and `codex/hooks/hooks.json`; do not broaden the design to solve long-term installation mechanics.
  - **Acceptance Criteria:** Codex attempts to load the plugin and recognizes its hook configuration.

- **Test SessionStart in Codex**
  - **Description:** Start or resume a Codex session with Kokoro running and then with Kokoro unavailable.
  - **Acceptance Criteria:** Healthy startup is quiet; unavailable startup produces a warning and continues.

- **Test Stop Playback in Codex**
  - **Description:** Complete a Codex turn and verify the final assistant response is sent to Kokoro and played through host audio.
  - **Acceptance Criteria:** Playback starts after `Stop`, Codex is not blocked by full audio playback, and stdout contract errors do not occur.

- **Resolve Relative Path Assumption if Needed**
  - **Description:** If Codex does not execute hook commands relative to the plugin root, add the smallest wrapper or command adjustment that preserves the plugin shape.
  - **Acceptance Criteria:** The plugin works in Codex without requiring absolute user-specific paths in `hooks/hooks.json`.

- **Update Setup Guide**
  - **Description:** Update `codex/README.md` with verified setup steps, assumptions, troubleshooting, and expected Kokoro startup state.
  - **Acceptance Criteria:** A reader can reproduce the working local Codex trial using the documented steps and plugin-local config file.
