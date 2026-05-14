"""HTTP client helpers for Kokoro-FastAPI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import http.client
import json
import socket

from .config import TtsHookConfig, build_kokoro_urls, build_speech_payload


@dataclass(frozen=True)
class KokoroResult:
    """Clear success/error result for Kokoro HTTP calls."""

    ok: bool
    status: int | None = None
    data: Any = None
    error: str | None = None


def check_health(config: TtsHookConfig) -> KokoroResult:
    """Call Kokoro ``GET /health``."""

    return _json_request(config, build_kokoro_urls(config).health_url)


def list_voices(config: TtsHookConfig) -> KokoroResult:
    """Call Kokoro ``GET /v1/audio/voices``."""

    return _json_request(config, build_kokoro_urls(config).voices_url)


def synthesize_speech(config: TtsHookConfig, input_text: str) -> KokoroResult:
    """Call Kokoro ``POST /v1/audio/speech`` and return audio bytes."""

    payload = build_speech_payload(config, input_text)
    return _bytes_request(
        config,
        build_kokoro_urls(config).speech_url,
        method="POST",
        body=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "audio/wav"},
    )


def _json_request(config: TtsHookConfig, url: str) -> KokoroResult:
    result = _bytes_request(config, url, method="GET", headers={"Accept": "application/json"})
    if not result.ok:
        return result
    if not result.data:
        return KokoroResult(ok=True, status=result.status, data=None)
    try:
        return KokoroResult(ok=True, status=result.status, data=json.loads(result.data.decode("utf-8")))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return KokoroResult(ok=False, status=result.status, error=f"Invalid JSON response: {exc}")


def _bytes_request(
    config: TtsHookConfig,
    url: str,
    *,
    method: str,
    headers: dict[str, str],
    body: bytes | None = None,
) -> KokoroResult:
    parsed = urlsplit(url)
    if parsed.scheme != "http":
        return KokoroResult(ok=False, error=f"Unsupported Kokoro URL scheme: {parsed.scheme}")
    if parsed.hostname is None or parsed.port is None:
        return KokoroResult(ok=False, error=f"Invalid Kokoro URL: {url}")
    request_context = f"{method} {url}"

    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"

    connection = http.client.HTTPConnection(
        parsed.hostname,
        parsed.port,
        timeout=config.timeouts.connect_seconds,
    )
    try:
        connection.request(method, path, body=body, headers=headers)
        if connection.sock is not None:
            connection.sock.settimeout(config.timeouts.read_seconds)
        response = connection.getresponse()
        status = response.status
        data = response.read()
        reason = response.reason
    except (http.client.HTTPException, TimeoutError, socket.timeout, OSError) as exc:
        detail = str(exc) or exc.__class__.__name__
        return KokoroResult(ok=False, error=f"{request_context} failed: {detail}")
    finally:
        connection.close()

    if status < 200 or status >= 300:
        detail = data[:512].decode("utf-8", errors="replace").strip()
        return KokoroResult(
            ok=False,
            status=status,
            error=f"{request_context} failed: HTTP {status}: {detail or reason}",
        )
    return KokoroResult(ok=True, status=status, data=data)
