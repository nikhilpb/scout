"""FastAPI app serving the scout data repo as an installable PWA.

Server-rendered Jinja2 pages (latest feed, topics, digest) plus one JSON
endpoint for submitting digest feedback through scout.feedback's
``<!-- scout-feedback -->`` blocks — the same store `scout feedback` uses.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, model_validator

from scout.feedback import append_block
from scout.paths import DataPaths
from scout.server import digests

_PKG_DIR = Path(__file__).parent


class FeedbackIn(BaseModel):
    topic: str
    name: str
    rating: Optional[int] = Field(default=None, ge=1, le=5)
    notes: Optional[str] = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def rating_or_notes(self) -> "FeedbackIn":
        if self.rating is None and not (self.notes and self.notes.strip()):
            raise ValueError("provide a rating, notes, or both")
        return self


def create_app(data: DataPaths) -> FastAPI:
    app = FastAPI(title="Scout", docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", StaticFiles(directory=_PKG_DIR / "static"), name="static")
    templates = Jinja2Templates(directory=_PKG_DIR / "templates")

    @app.get("/")
    def home(request: Request):
        topics = digests.list_topics(data)
        titles = {t.slug: t.title for t in topics}
        return templates.TemplateResponse(
            request,
            "home.html",
            {
                "nav": "latest",
                "feed": digests.latest_digests(topics),
                "topic_titles": titles,
            },
        )

    @app.get("/topics")
    def topics_page(request: Request):
        topics = digests.list_topics(data)
        digest_index = {t.slug: [m.id for m in t.digests] for t in topics}
        return templates.TemplateResponse(
            request,
            "topics.html",
            {
                "nav": "topics",
                "topics": topics,
                "digest_index": json.dumps(digest_index),
            },
        )

    @app.get("/t/{slug}")
    def topic_page(request: Request, slug: str):
        items = digests.list_digests(data, slug)
        if not items:
            raise HTTPException(status_code=404, detail="unknown topic")
        topics = digests.list_topics(data)
        topic = next(t for t in topics if t.slug == slug)
        return templates.TemplateResponse(
            request,
            "topic.html",
            {"nav": "topics", "topic": topic},
        )

    @app.get("/t/{slug}/{name}")
    def digest_page(request: Request, slug: str, name: str):
        digest = digests.load_digest(data, slug, name)
        if digest is None:
            raise HTTPException(status_code=404, detail="unknown digest")
        title, _, _ = digests.topic_yaml_meta(data.topics_dir, slug)
        return templates.TemplateResponse(
            request,
            "digest.html",
            {
                "nav": "topics",
                "digest": digest,
                "topic_title": title or slug.replace("-", " ").capitalize(),
            },
        )

    @app.post("/api/feedback")
    def add_feedback(body: FeedbackIn):
        path = digests.digest_path(data, body.topic, body.name)
        if path is None:
            raise HTTPException(status_code=404, detail="unknown digest")
        payload: dict = {}
        if body.rating is not None:
            payload["rating"] = body.rating
        if body.notes and body.notes.strip():
            payload["notes"] = body.notes.strip()
        payload["at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        payload["source"] = "web"
        append_block(path, payload)
        return {"ok": True, "feedback": payload}

    @app.get("/manifest.webmanifest")
    def manifest():
        return FileResponse(
            _PKG_DIR / "static" / "manifest.webmanifest",
            media_type="application/manifest+json",
        )

    # Served from the root so the service worker's scope covers the whole app.
    @app.get("/sw.js")
    def service_worker():
        return FileResponse(_PKG_DIR / "static" / "sw.js", media_type="text/javascript")

    @app.get("/favicon.svg")
    def favicon():
        return FileResponse(
            _PKG_DIR / "static" / "icons" / "favicon.svg", media_type="image/svg+xml"
        )

    return app
