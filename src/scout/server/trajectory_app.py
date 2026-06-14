"""FastAPI dashboard for browsing agent run trajectories.

Server-rendered pages: an index of recent runs across topics, a per-topic run
list, and a per-run timeline that walks the trajectory record-by-record
(messages, reasoning, tool calls/results, artifacts, final metrics). Read-only —
it renders ``trajectories/<slug>/<run-id>.jsonl`` via ``scout.server.trajectories``.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.templating import Jinja2Templates

from scout.paths import DataPaths
from scout.server import trajectories as tj

_PKG_DIR = Path(__file__).parent


def _pretty_json(value, limit: int = 4000) -> str:
    try:
        text = json.dumps(value, indent=2, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(value)
    if len(text) > limit:
        text = text[:limit] + "\n… (truncated)"
    return text


def create_trajectory_app(data: DataPaths) -> FastAPI:
    app = FastAPI(title="Scout Trajectories", docs_url=None, redoc_url=None, openapi_url=None)
    templates = Jinja2Templates(directory=_PKG_DIR / "templates")
    templates.env.filters["pretty_json"] = _pretty_json

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.get("/")
    def index(request: Request):
        topics = tj.list_topics(data)
        return templates.TemplateResponse(
            request,
            "traj_index.html",
            {"topics": topics, "recent": tj.recent_runs(topics)},
        )

    @app.get("/t/{slug}")
    def topic(request: Request, slug: str):
        runs = tj.list_runs(data, slug)
        if not runs:
            raise HTTPException(status_code=404, detail="unknown topic")
        return templates.TemplateResponse(
            request,
            "traj_topic.html",
            {"slug": slug, "title": runs[0].title or slug, "runs": runs},
        )

    @app.get("/r/{slug}/{run_id}")
    def run(request: Request, slug: str, run_id: str):
        doc = tj.load_trajectory(data, slug, run_id)
        if doc is None:
            raise HTTPException(status_code=404, detail="unknown run")
        return templates.TemplateResponse(
            request,
            "traj_detail.html",
            {"doc": doc, "summary": doc.summary},
        )

    @app.get("/api/r/{slug}/{run_id}")
    def run_json(slug: str, run_id: str):
        doc = tj.load_trajectory(data, slug, run_id)
        if doc is None:
            raise HTTPException(status_code=404, detail="unknown run")
        return {"summary": doc.summary, "records": doc.records}

    return app
