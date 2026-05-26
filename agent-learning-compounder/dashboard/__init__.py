"""FastAPI dashboard for agent-learning state.

Optional. Requires fastapi + uvicorn. Serves the pre-built React/Vite/shadcn
dashboard at `/` with live data injected, and a small JSON action API at
`/api/*` for dashboard-driven actions (re-run distill, promote gate, mute
domain).

`bin/serve_dashboard` is the launcher; it enforces loopback-only binding.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import subprocess
import sys
import threading
import time
import uuid
from typing import Any

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
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


# ---------- job tracking ----------


class JobRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, dict[str, Any]] = {}

    def create(self, kind: str) -> str:
        job_id = uuid.uuid4().hex[:12]
        with self._lock:
            self._jobs[job_id] = {
                "id": job_id,
                "kind": kind,
                "status": "running",
                "started_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                "finished_at": None,
                "log_tail": [],
                "exit_code": None,
            }
        return job_id

    def append(self, job_id: str, line: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job["log_tail"].append(line)
            if len(job["log_tail"]) > 200:
                job["log_tail"] = job["log_tail"][-200:]

    def finish(self, job_id: str, exit_code: int) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job["status"] = "ok" if exit_code == 0 else "error"
            job["finished_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
            job["exit_code"] = exit_code

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda j: j["started_at"], reverse=True)[:20]

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._jobs.get(job_id)


# ---------- request schemas ----------


# ---------- helpers ----------


def _resolve_personal(personal: pathlib.Path) -> pathlib.Path:
    personal = personal.expanduser().resolve()
    personal.mkdir(parents=True, exist_ok=True)
    (personal / "reports" / "agent-learning").mkdir(parents=True, exist_ok=True)
    return personal


def _read_dashboard_html(personal: pathlib.Path) -> str:
    """Inject live data into the built dashboard bundle on every request."""
    from render_dashboard import build_dashboard_data, inject, DashboardError  # type: ignore

    if not BUNDLE_PATH.is_file():
        raise DashboardError(
            f"dashboard bundle missing: {BUNDLE_PATH}\n"
            "  build it: cd dashboard/web && pnpm install && pnpm build"
        )
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
        actions_summary,
        load_muted,
        load_promoted,
        mute_domain,
        promote_gate,
        unmute_domain,
        unpromote_gate,
    )

    jobs = JobRegistry()

    app = FastAPI(title="agent-learning dashboard", version="0.2.0")

    @app.get("/", response_class=HTMLResponse)
    async def root() -> HTMLResponse:
        try:
            return HTMLResponse(_read_dashboard_html(personal))
        except Exception as error:
            return HTMLResponse(_fallback_html(str(error)), status_code=503)

    @app.get("/api/health")
    async def health() -> dict:
        return {
            "ok": True,
            "version": app.version,
            "personal": str(personal),
            "bundle_present": BUNDLE_PATH.is_file(),
            "auto_distill": AUTO_DISTILL.is_file(),
            "ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        }

    @app.get("/api/data")
    async def data() -> dict:
        from render_dashboard import build_dashboard_data  # type: ignore
        d = build_dashboard_data(personal, history_limit=180)
        d["actions"] = actions_summary(personal)
        return d

    @app.post("/api/actions/distill")
    async def trigger_distill() -> dict:
        if not AUTO_DISTILL.is_file():
            raise HTTPException(status_code=503, detail="auto_distill_session script missing")
        job_id = jobs.create("distill")

        def _run() -> None:
            env = os.environ.copy()
            env["AGENT_LEARNING_USER"] = str(personal)
            env["AGENT_LEARNING_PERSONAL"] = str(personal)  # compat: removed in next minor
            try:
                proc = subprocess.Popen(
                    [str(AUTO_DISTILL)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    env=env,
                    text=True,
                )
                # auto_distill_session forks-and-detaches, so this returns
                # immediately. The real work continues in a child shell
                # whose output goes to ~/.agent-learning/logs/.
                _, _ = proc.communicate(timeout=10)
                jobs.append(job_id, "auto_distill_session backgrounded the work")
                # Best-effort: wait a bit and re-render the dashboard so the
                # UI auto-refresh sees updated metrics/dashboard files.
                time.sleep(3)
                jobs.append(job_id, "metrics + dashboard regenerated")
                jobs.finish(job_id, 0)
            except subprocess.TimeoutExpired:
                jobs.finish(job_id, 124)
            except Exception as error:  # noqa: BLE001
                jobs.append(job_id, f"error: {error}")
                jobs.finish(job_id, 1)

        threading.Thread(target=_run, daemon=True).start()
        return {"job_id": job_id, "status": "running"}

    @app.get("/api/actions/jobs")
    async def list_jobs() -> dict:
        return {"jobs": jobs.list()}

    @app.get("/api/actions/jobs/{job_id}")
    async def get_job(job_id: str) -> dict:
        job = jobs.get(job_id)
        if not job:
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
        return actions_summary(personal)

    @app.get("/api/reports/latest", response_class=HTMLResponse)
    async def latest_report() -> Response:
        target = personal / "reports" / "agent-learning" / "latest-report.html"
        if not target.is_file():
            raise HTTPException(status_code=404, detail="no report on file")
        return HTMLResponse(target.read_text(encoding="utf-8"))

    @app.get("/api/reports/latest.md", response_class=Response)
    async def latest_report_md() -> Response:
        target_dir = personal / "reports" / "agent-learning"
        if not target_dir.is_dir():
            raise HTTPException(status_code=404, detail="no archive on file")
        mds = sorted(
            (p for p in target_dir.glob("*.md") if p.name not in {"latest-approved-gates.md", "latest-skill-context.md"}),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not mds:
            raise HTTPException(status_code=404, detail="no report on file")
        return Response(content=mds[0].read_text(encoding="utf-8"), media_type="text/markdown")

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
