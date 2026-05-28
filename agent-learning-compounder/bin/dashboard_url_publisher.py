#!/usr/bin/env python3
"""Dashboard URL publication policy for ALC project state."""

from __future__ import annotations

import json
import os
import pathlib
import time
import uuid
from typing import Any
from urllib.parse import urlparse

from state_handle import StateHandle


SERVER_MARKER = "server.json"
DASHBOARD_HTML = "dashboard.html"
LEGACY_INDEX_HTML = "index.html"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
LIVE_MARKER_TTL_SECONDS = 12 * 60 * 60


def _canonical_host(host: str) -> str:
    value = host.strip().lower()
    if value.startswith("[") and value.endswith("]"):
        return value[1:-1]
    return value


def _state(value: StateHandle | str | pathlib.Path) -> StateHandle:
    if isinstance(value, StateHandle):
        return value
    return StateHandle.for_repo(pathlib.Path(value))


def marker_path(state: StateHandle) -> pathlib.Path:
    return state.dashboard_dir / SERVER_MARKER


def _read_marker(path: pathlib.Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return loaded if isinstance(loaded, dict) else None


def is_loopback_dashboard_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme != "http":
        return False
    try:
        host = parsed.hostname
        parsed.port
    except ValueError:
        return False
    return host in LOOPBACK_HOSTS


def _valid_marker_url(payload: dict[str, Any]) -> str | None:
    url = payload.get("url")
    if not isinstance(url, str) or not is_loopback_dashboard_url(url):
        return None

    host = payload.get("host")
    if host is not None:
        if not isinstance(host, str) or _canonical_host(host) not in LOOPBACK_HOSTS:
            return None

    port = payload.get("port")
    if port is not None:
        try:
            marker_port = int(port)
            url_port = urlparse(url).port
        except (TypeError, ValueError):
            return None
        if marker_port != url_port:
            return None

    timestamp = payload.get("timestamp")
    if timestamp is not None:
        try:
            if time.time() - float(timestamp) > LIVE_MARKER_TTL_SECONDS:
                return None
        except (TypeError, ValueError):
            return None

    return url


def live_dashboard_url(state: StateHandle) -> str | None:
    payload = _read_marker(marker_path(state))
    if payload is None:
        return None
    return _valid_marker_url(payload)


def static_dashboard_url(state: StateHandle) -> str:
    for filename in (DASHBOARD_HTML, LEGACY_INDEX_HTML):
        artifact = state.dashboard_dir / filename
        if artifact.exists():
            return artifact.resolve().as_uri()
    return state.dashboard_dir.resolve().as_uri()


def dashboard_url(repo: StateHandle | str | pathlib.Path) -> str:
    state = _state(repo)
    return live_dashboard_url(state) or static_dashboard_url(state)


def dashboard_url_status(repo: StateHandle | str | pathlib.Path) -> dict[str, Any]:
    state = _state(repo)
    payload = _read_marker(marker_path(state))
    live = _valid_marker_url(payload) if payload else None
    age_seconds = None
    if payload and payload.get("timestamp") is not None:
        try:
            age_seconds = time.time() - float(payload["timestamp"])
        except (TypeError, ValueError):
            age_seconds = None
    return {
        "url": live or static_dashboard_url(state),
        "live_url": live,
        "marker_present": payload is not None,
        "healthy": live is not None,
        "age_seconds": age_seconds,
    }


def _url_for(host: str, port: int) -> str:
    host = _canonical_host(host)
    display_host = f"[{host}]" if ":" in host else host
    return f"http://{display_host}:{int(port)}/"


def publish_live_url(
    state: StateHandle,
    *,
    host: str,
    port: int,
    surface: str = "dashboard",
) -> str | None:
    host = _canonical_host(host)
    url = _url_for(host, port)
    if not is_loopback_dashboard_url(url):
        return None

    token = uuid.uuid4().hex
    payload = {
        "url": url,
        "host": host,
        "port": int(port),
        "surface": surface,
        "pid": os.getpid(),
        "token": token,
        "timestamp": time.time(),
    }

    path = marker_path(state)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{token}.tmp")
    tmp.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    tmp.replace(path)
    return token


def clear_live_url(state: StateHandle, token: str | None) -> bool:
    if not token:
        return False

    path = marker_path(state)
    payload = _read_marker(path)
    if payload is None or payload.get("token") != token:
        return False

    try:
        path.unlink()
    except FileNotFoundError:
        return False
    return True
