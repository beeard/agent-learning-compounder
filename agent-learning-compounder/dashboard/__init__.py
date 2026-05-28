"""FastAPI dashboard for agent-learning state.

Optional. Requires fastapi + uvicorn. Serves the pre-built React/Vite/shadcn
dashboard at `/` with live data injected, and a small JSON action API at
`/api/*` for dashboard-driven actions (re-run distill, promote gate, mute
domain).

`bin/serve_dashboard` is the launcher; it enforces loopback-only binding.
"""

from __future__ import annotations

import os
import pathlib
import sys
from typing import Any

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import HTMLResponse, Response
    from pydantic import BaseModel, Field
    _FASTAPI_AVAILABLE = True

    class PromoteRequest(BaseModel):
        key: str = Field(..., description="Stable key 'domain::gate_category'.")
        domain: str
        gate_category: str

    class MuteRequest(BaseModel):
        domain: str
        reason: str | None = None

    class UnmuteRequest(BaseModel):
        domain: str

    class UnpromoteRequest(BaseModel):
        key: str
except ImportError:
    _FASTAPI_AVAILABLE = False
    PromoteRequest = MuteRequest = UnmuteRequest = UnpromoteRequest = None  # type: ignore


HERE = pathlib.Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent
BUNDLE_PATH = SKILL_ROOT / "dashboard" / "web" / "dist" / "index.html"
AUTO_DISTILL = SKILL_ROOT / "bin" / "auto_distill_session"


# ---------- request schemas ----------


# ---------- helpers ----------


def _resolve_personal(personal: pathlib.Path) -> pathlib.Path:
    personal = personal.expanduser().resolve()
    personal.mkdir(parents=True, exist_ok=True)
    (personal / "reports" / "agent-learning").mkdir(parents=True, exist_ok=True)
    return personal


def _read_dashboard_html(personal: pathlib.Path, data: dict[str, Any] | None = None) -> str:
    """Inject live data into the built dashboard bundle on every request."""
    from render_dashboard import build_dashboard_data, inject, DashboardError  # type: ignore

    if not BUNDLE_PATH.is_file():
        raise DashboardError(
            f"dashboard bundle missing: {BUNDLE_PATH}\n"
            "  build it: cd dashboard/web && pnpm install && pnpm build"
        )
    if data is None:
        data = build_dashboard_data(personal, history_limit=180)
    bundle_text = BUNDLE_PATH.read_text(encoding="utf-8")
    return inject(bundle_text, data)


# ---------- app construction ----------


def build_app(personal: pathlib.Path | None = None, repo: pathlib.Path | None = None):
    """Construct the FastAPI dashboard app.

    `personal` is the agent-learning user-scope archive root. If not supplied,
    falls back to AGENT_LEARNING_USER (compat: AGENT_LEARNING_PERSONAL) env,
    then `<repo>/.agent-learning` when `repo` is provided, then
    `~/.agent-learning`.
    """
    if not _FASTAPI_AVAILABLE:
        raise ImportError("fastapi required for dashboard (pip install fastapi uvicorn)")

    # Resolve user-scope root.
    if personal is None:
        env = os.environ.get("AGENT_LEARNING_USER") or os.environ.get("AGENT_LEARNING_PERSONAL")
        if env:
            personal = pathlib.Path(env)
        elif repo is not None:
            candidate = repo / ".agent-learning"
            personal = candidate if candidate.exists() else pathlib.Path.home() / ".agent-learning"
        else:
            personal = pathlib.Path.home() / ".agent-learning"
    personal = _resolve_personal(personal)

    # Late import — we need bin/ on sys.path for render_dashboard.
    sys.path.insert(0, str(SKILL_ROOT / "bin"))
    from dashboard.actions import (  # noqa: E402
        get_action_job,
        list_action_jobs,
        mute_domain,
        promote_gate,
        run_distill,
        unmute_domain,
        unpromote_gate,
    )
    import dashboard_read_model  # noqa: E402
    from state_handle import StateHandle  # noqa: E402

    repo_for_state = repo.resolve() if repo is not None else None

    def _project_state() -> "StateHandle | None":
        if repo_for_state is None:
            return None
        try:
            return StateHandle.for_repo(repo_for_state)
        except Exception:
            return None

    def _build_dashboard_payload() -> dict:
        return dashboard_read_model.build_dashboard_payload(
            personal,
            state=_project_state(),
            history_limit=180,
        )

    app = FastAPI(title="agent-learning dashboard", version="0.2.0")

    @app.get("/", response_class=HTMLResponse)
    async def root() -> HTMLResponse:
        try:
            return HTMLResponse(_read_dashboard_html(personal, _build_dashboard_payload()))
        except Exception as error:
            return HTMLResponse(_fallback_html(str(error)), status_code=503)

    @app.get("/api/health")
    async def health() -> dict:
        return dashboard_read_model.build_dashboard_health(
            personal,
            version=app.version,
            bundle_path=BUNDLE_PATH,
            auto_distill_path=AUTO_DISTILL,
        )

    @app.get("/api/data")
    async def data() -> dict:
        return _build_dashboard_payload()

    @app.post("/api/actions/distill")
    async def trigger_distill() -> dict:
        result = run_distill(personal, script=AUTO_DISTILL)
        if result.get("status") == "missing":
            raise HTTPException(status_code=503, detail=result.get("message", "auto_distill_session script missing"))
        return result

    @app.get("/api/actions/jobs")
    async def list_jobs() -> dict:
        return list_action_jobs()

    @app.get("/api/actions/jobs/{job_id}")
    async def get_job(job_id: str) -> dict:
        job = get_action_job(job_id)
        if job.get("status") == "missing":
            raise HTTPException(status_code=404, detail="unknown job")
        return job

    @app.post("/api/actions/promote")
    async def post_promote(req: PromoteRequest) -> dict:
        return promote_gate(
            personal,
            key=req.key,
            domain=req.domain,
            gate_category=req.gate_category,
        )

    @app.post("/api/actions/unpromote")
    async def post_unpromote(req: UnpromoteRequest) -> dict:
        return unpromote_gate(personal, key=req.key)

    @app.post("/api/actions/mute")
    async def post_mute(req: MuteRequest) -> dict:
        return mute_domain(personal, domain=req.domain, reason=req.reason)

    @app.post("/api/actions/unmute")
    async def post_unmute(req: UnmuteRequest) -> dict:
        return unmute_domain(personal, domain=req.domain)

    @app.get("/api/actions/state")
    async def get_action_state() -> dict:
        return dashboard_read_model.build_actions_summary(personal)

    @app.get("/api/reports/latest", response_class=HTMLResponse)
    async def latest_report() -> Response:
        report = dashboard_read_model.build_latest_report_content(personal, format="html")
        if report["status"] != "available":
            raise HTTPException(status_code=404, detail=report["message"])
        return HTMLResponse(report["content"])

    @app.get("/api/reports/latest.md", response_class=Response)
    async def latest_report_md() -> Response:
        report = dashboard_read_model.build_latest_report_content(personal, format="markdown")
        if report["status"] != "available":
            raise HTTPException(status_code=404, detail=report["message"])
        return Response(content=report["content"], media_type=report["media_type"])

    return app


def _fallback_html(error: str) -> str:
    return f"""<!doctype html><html lang="en"><meta charset="utf-8"/>
<title>Agent learning · dashboard</title>
<style>body{{font:14px/1.5 system-ui;margin:48px auto;max-width:680px;color:#333}}
code{{background:#f3f3f3;padding:2px 6px;border-radius:4px}}
pre{{background:#fafafa;border:1px solid #eaeaea;padding:14px;border-radius:6px;overflow:auto}}</style>
<h1>Dashboard bundle missing</h1>
<p>The pre-built dashboard bundle isn't present yet. Build it once:</p>
<pre>cd ~/.claude/skills/agent-learning-compounder/dashboard/web
pnpm install
pnpm build</pre>
<p>Then reload this page.</p>
<details><summary>Error details</summary><pre>{error}</pre></details>
"""
