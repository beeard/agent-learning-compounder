"""Operator dashboard for agent-learning state.

Optional. Requires fastapi, jinja2 (and uvicorn for the launcher).
Imports of the FastAPI app are guarded so the package directory is
importable even without the optional deps.
"""
from __future__ import annotations

import json
from pathlib import Path

try:
    from fastapi import FastAPI, Request
    from fastapi.responses import HTMLResponse
    from fastapi.staticfiles import StaticFiles
    from fastapi.templating import Jinja2Templates
    _FASTAPI_AVAILABLE = True
except ImportError:
    _FASTAPI_AVAILABLE = False

HERE = Path(__file__).resolve().parent


def _resolve_state(repo: Path):
    payload = json.loads((repo / ".agent-learning.json").read_text(encoding="utf-8"))
    state_repos = repo / ".agent-learning" / "repos"
    queue = next(state_repos.rglob("improvement-queue.jsonl"), None)
    probes = next(state_repos.rglob("probes.json"), None)
    events = next(state_repos.rglob("hook-events.jsonl"), None)
    return {
        "gates_md": Path(payload["latest_approved_gates"]),
        "skill_context_md": Path(payload["latest_skill_context"]),
        "queue": queue,
        "probes": probes,
        "events": events,
    }


def build_app(repo: Path):
    """Construct the FastAPI app. Requires fastapi + jinja2."""
    if not _FASTAPI_AVAILABLE:
        raise ImportError("fastapi + jinja2 required for dashboard")

    app = FastAPI(title="agent-learning-compounder dashboard")
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    templates = Jinja2Templates(directory=str(HERE / "templates"))
    state = _resolve_state(repo)

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        return templates.TemplateResponse("index.html", {
            "request": request, "repo": str(repo),
        })

    @app.get("/_gates", response_class=HTMLResponse)
    async def gates(request: Request):
        gates_text = state["gates_md"].read_text(encoding="utf-8") if state["gates_md"].is_file() else ""
        return templates.TemplateResponse("_gates.html", {
            "request": request, "gates_md": gates_text,
        })

    @app.get("/_queue", response_class=HTMLResponse)
    async def queue(request: Request):
        rows = []
        if state["queue"] and state["queue"].is_file():
            rows = [json.loads(ln) for ln in state["queue"].read_text(encoding="utf-8").splitlines() if ln]
        return templates.TemplateResponse("_queue.html", {
            "request": request, "rows": rows,
        })

    @app.get("/_probes", response_class=HTMLResponse)
    async def probes(request: Request):
        data = {}
        if state["probes"] and state["probes"].is_file():
            data = json.loads(state["probes"].read_text(encoding="utf-8"))
        return templates.TemplateResponse("_probes.html", {
            "request": request, "probes": data,
        })

    return app
