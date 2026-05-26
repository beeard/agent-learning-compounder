#!/usr/bin/env python3
"""Read-only HTTP dashboard server for ALC artifacts.

Endpoints:
- GET /
- GET /data.json
- GET /static/<file>

No POST endpoints are implemented; all writes stay on the CLI.
"""

from __future__ import annotations

import argparse
import contextlib
import http.server
import json
import mimetypes
import os
import pathlib
import time
import socketserver
from typing import Any

try:
    from state_handle import StateHandle
except ImportError:  # pragma: no cover
    from bin.state_handle import StateHandle

try:
    import alc_query
except ImportError:  # pragma: no cover
    import bin.alc_query as alc_query


SKILL_ROOT = pathlib.Path(__file__).resolve().parent
TEMPLATE_PATH = SKILL_ROOT / "templates" / "dashboard.html"
STATIC_ROOT = SKILL_ROOT / "static"

authored_sections = [
    "recommendations",
    "pending_patches",
    "anomalies",
    "patterns",
    "correlations",
    "apply_log",
    "gates_and_insights",
    "suggestions",
]


class _ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


@contextlib.contextmanager
def _state_env(state: pathlib.Path | None):
    if state is None:
        yield
        return
    previous = os.environ.get("AGENT_LEARNING_STATE_DIR")
    os.environ["AGENT_LEARNING_STATE_DIR"] = str(state)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("AGENT_LEARNING_STATE_DIR", None)
        else:
            os.environ["AGENT_LEARNING_STATE_DIR"] = previous


def _resolve_state(repo: pathlib.Path | None = None, state: pathlib.Path | None = None, personal: pathlib.Path | None = None) -> StateHandle:
    if repo is None and state is None:
        repo = pathlib.Path.cwd()

    if state is not None:
        candidate_parent = state.parent
        resolved = state
        if state.is_dir() and candidate_parent.name == "repos":
            # Accept either explicit state root or a pre-resolved repo state dir.
            resolved = candidate_parent.parent

        with _state_env(resolved):
            return StateHandle.for_repo(pathlib.Path(repo or pathlib.Path.cwd()))

    if personal is not None:
        personal = personal.expanduser().resolve()
        with _state_env(personal):
            return StateHandle.for_repo(pathlib.Path(repo or pathlib.Path.cwd()))
    return StateHandle.for_repo(pathlib.Path(repo or pathlib.Path.cwd()))


def _read_text(path: pathlib.Path) -> str:
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _read_suggestions(state: StateHandle) -> list[dict[str, Any]]:
    payload_path = state.repo_state_dir / "suggestions.json"
    if not payload_path.is_file():
        return []
    try:
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    rows = payload.get("suggestions") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []

    out: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, dict):
            out.append(row)
    return out


def _bucket_recommendations(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    buckets = {name: [] for name in ("anomalies", "patterns", "correlations")}
    for row in rows:
        kind = str(row.get("kind", "")).lower()
        if "anomaly" in kind:
            buckets["anomalies"].append(row)
            continue
        if "pattern" in kind:
            buckets["patterns"].append(row)
            continue
        if "correlation" in kind or "dag" in kind:
            buckets["correlations"].append(row)
            continue
    return buckets


def build_data_blob(state: StateHandle) -> dict[str, Any]:
    recommendations = alc_query.get_recommendations(state)
    rec_buckets = _bucket_recommendations(recommendations)
    gates_markdown = _read_text(state.reports_dir / "latest-approved-gates.md")
    insights_markdown = _read_text(state.reports_dir / "latest-skill-context.md")

    data = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "recommendations": recommendations,
        "pending_patches": alc_query.get_pending_patches(state),
        "anomalies": rec_buckets["anomalies"],
        "patterns": rec_buckets["patterns"],
        "correlations": rec_buckets["correlations"],
        "apply_log": alc_query.get_apply_log(state),
        "gates_and_insights": {
            "gates_markdown": gates_markdown,
            "insights_markdown": insights_markdown,
            "actor_summary": alc_query.get_actor_summary(state),
        },
        "suggestions": _read_suggestions(state),
        "sections": authored_sections,
    }

    return data


def _inject_payload(template: str, payload: dict[str, Any]) -> str:
    data_blob = json.dumps(payload, sort_keys=True, ensure_ascii=False).replace("</", "<\\/")
    return template.replace("{{ ALC_DASHBOARD_DATA }}", data_blob)


def _read_template() -> str:
    return TEMPLATE_PATH.read_text(encoding="utf-8")


class _DashboardHandler(http.server.BaseHTTPRequestHandler):
    state: StateHandle

    def _send(self, status: int, body: str | bytes, content_type: str = "text/plain; charset=utf-8"):
        raw = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        route = self.path.split("?", 1)[0]

        if route == "/":
            template = _read_template()
            payload = build_data_blob(self.state)
            self._send(200, _inject_payload(template, payload), "text/html; charset=utf-8")
            return

        if route == "/data.json":
            payload = build_data_blob(self.state)
            self._send(200, json.dumps(payload, sort_keys=True, ensure_ascii=False), "application/json; charset=utf-8")
            return

        if route.startswith("/static/"):
            parts = route.split("/")[2:]
            if len(parts) != 1:
                self._send(400, "bad static path")
                return
            candidate = parts[0]
            if "/" in candidate or "\\" in candidate or candidate.startswith("."):
                self._send(400, "bad static path")
                return
            file_path = STATIC_ROOT / candidate
            if not file_path.is_file():
                self._send(404, "not found")
                return
            content = file_path.read_bytes()
            ctype, _ = mimetypes.guess_type(str(file_path))
            if ctype is None:
                ctype = "application/octet-stream"
            self._send(200, content, ctype)
            return

        self._send(404, "not found")

    def do_POST(self):
        self.send_response(405)
        self.send_header("Allow", "GET")
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()

    def do_PUT(self):
        self.do_POST()

    def do_DELETE(self):
        self.do_POST()

    def do_PATCH(self):
        self.do_POST()

    def log_message(self, format: str, *args: object) -> None:
        return None


def _build_server(handler_class: type[_DashboardHandler], host: str, port: int, state: StateHandle):
    handler_class.state = state
    _ThreadingHTTPServer.allow_reuse_address = True

    requested_port = port
    while True:
        try:
            return _ThreadingHTTPServer((host, requested_port), handler_class), requested_port
        except OSError as exc:
            if requested_port == 8765 and port == 8765:
                requested_port = 0
                continue
            raise


def create_server(
    *,
    repo: pathlib.Path | None = None,
    state: pathlib.Path | None = None,
    personal: pathlib.Path | None = None,
    host: str = "127.0.0.1",
    port: int = 0,
) -> tuple[socketserver.ThreadingHTTPServer, int]:
    actual = _resolve_state(repo=repo, state=state, personal=personal)
    server, selected = _build_server(_DashboardHandler, host, port, actual)
    return server, selected


def run_server(
    *,
    repo: pathlib.Path | None = None,
    state: pathlib.Path | None = None,
    personal: pathlib.Path | None = None,
    host: str = "127.0.0.1",
    port: int = 0,
) -> None:
    httpd, selected = create_server(repo=repo, state=state, personal=personal, host=host, port=port)
    print(f"[alc-dashboard] listening on http://{host}:{selected}/")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=pathlib.Path)
    parser.add_argument("--state", "--state-dir", "--state_dir", dest="state", type=pathlib.Path)
    parser.add_argument("--personal", "--personal-dir", type=pathlib.Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        httpd, selected = create_server(
            repo=args.repo,
            state=args.state,
            personal=args.personal,
            host=args.host,
            port=args.port,
        )
        print(f"[alc-dashboard] listening on http://{args.host}:{selected}/")
        httpd.serve_forever()
    except KeyboardInterrupt:
        return 0
    except Exception as error:
        print(str(error))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
