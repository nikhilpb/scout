"""Read-side model of the data repo's output/ tree for the web app.

Digests are ``output/<slug>/<name>.md`` files: YAML frontmatter, a markdown
body, and zero or more trailing ``<!-- scout-feedback -->`` blocks (see
scout.feedback). This module parses those pieces apart and renders the body
to HTML; it never writes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml
from markdown_it import MarkdownIt

from scout.feedback import BLOCK_RE, parse_blocks
from scout.paths import DataPaths

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
# No dots or slashes, so a validated name cannot traverse out of the topic dir.
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")

_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n?", re.DOTALL)
_H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")

# js-default: tables + strikethrough on, raw HTML escaped (html=False), which
# also keeps any feedback block that slipped through from being interpreted.
_md = MarkdownIt("js-default")


@dataclass(frozen=True)
class DigestMeta:
    topic: str
    name: str  # filename stem, e.g. "2026-06-08" or "2026-06-08-142312"
    date: str  # YYYY-MM-DD ("" when not derivable)
    pretty_date: str
    title: Optional[str]
    teaser: Optional[str]

    @property
    def id(self) -> str:
        return f"{self.topic}/{self.name}"


@dataclass(frozen=True)
class TopicInfo:
    slug: str
    title: str
    description: Optional[str]
    disabled: bool
    digests: list[DigestMeta]

    @property
    def latest(self) -> Optional[DigestMeta]:
        return self.digests[0] if self.digests else None


@dataclass(frozen=True)
class Digest:
    meta: DigestMeta
    frontmatter: dict
    html: str
    feedback: list[dict]


def split_frontmatter(text: str) -> tuple[dict, str]:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    body = text[m.end():].lstrip("\n")
    try:
        data = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return {}, body
    return (data if isinstance(data, dict) else {}), body


def strip_feedback(body: str) -> str:
    return BLOCK_RE.sub("", body).rstrip() + "\n"


def pretty_date(date_str: str) -> str:
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return date_str
    return f"{dt.strftime('%B')} {dt.day}, {dt.year}"


def _plain_text(line: str) -> str:
    line = _LINK_RE.sub(r"\1", line)
    return line.strip().strip("*_`").strip()


def _title_and_teaser(body: str) -> tuple[Optional[str], Optional[str]]:
    title_m = _H1_RE.search(body)
    title = _plain_text(title_m.group(1)) if title_m else None
    teaser = None
    rest = body[title_m.end():] if title_m else body
    for raw in rest.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        teaser = _plain_text(line)
        break
    if teaser and len(teaser) > 220:
        teaser = teaser[:219].rstrip() + "…"
    return title, teaser


def _digest_meta(slug: str, path: Path) -> DigestMeta:
    frontmatter, body = split_frontmatter(path.read_text(encoding="utf-8"))
    name = path.stem
    date = name[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", name) else str(frontmatter.get("date", ""))
    title, teaser = _title_and_teaser(strip_feedback(body))
    return DigestMeta(
        topic=slug,
        name=name,
        date=date,
        pretty_date=pretty_date(date),
        title=title,
        teaser=teaser,
    )


def topic_yaml_meta(topics_dir: Path, slug: str) -> tuple[Optional[str], Optional[str], bool]:
    """Best-effort (title, description, disabled) from topics/<slug>.yaml[.disabled].

    Reads the raw YAML rather than config.load_topic so that disabled or
    schema-invalid topics still get their human-readable names in the app.
    """
    for filename, disabled in ((f"{slug}.yaml", False), (f"{slug}.yaml.disabled", True)):
        path = topics_dir / filename
        if not path.is_file():
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (yaml.YAMLError, OSError):
            data = None
        if not isinstance(data, dict):
            data = {}
        title = data.get("title")
        description = data.get("description")
        return (
            title if isinstance(title, str) else None,
            description.strip() if isinstance(description, str) else None,
            disabled,
        )
    return None, None, False


def list_digests(data: DataPaths, slug: str) -> list[DigestMeta]:
    topic_dir = data.output_dir / slug
    if not SLUG_RE.match(slug) or not topic_dir.is_dir():
        return []
    metas = [_digest_meta(slug, p) for p in topic_dir.glob("*.md") if p.is_file()]
    return sorted(metas, key=lambda m: m.name, reverse=True)


def list_topics(data: DataPaths) -> list[TopicInfo]:
    if not data.output_dir.is_dir():
        return []
    topics = []
    for child in sorted(data.output_dir.iterdir()):
        if not child.is_dir() or not SLUG_RE.match(child.name):
            continue
        digests = list_digests(data, child.name)
        if not digests:
            continue
        title, description, disabled = topic_yaml_meta(data.topics_dir, child.name)
        topics.append(
            TopicInfo(
                slug=child.name,
                title=title or child.name.replace("-", " ").capitalize(),
                description=description,
                disabled=disabled,
                digests=digests,
            )
        )
    return topics


def latest_digests(topics: list[TopicInfo], limit: int = 40) -> list[DigestMeta]:
    merged = [m for t in topics for m in t.digests]
    merged.sort(key=lambda m: (m.date, m.name), reverse=True)
    return merged[:limit]


def digest_path(data: DataPaths, slug: str, name: str) -> Optional[Path]:
    if not SLUG_RE.match(slug) or not NAME_RE.match(name):
        return None
    path = data.output_dir / slug / f"{name}.md"
    return path if path.is_file() else None


def load_digest(data: DataPaths, slug: str, name: str) -> Optional[Digest]:
    path = digest_path(data, slug, name)
    if path is None:
        return None
    text = path.read_text(encoding="utf-8")
    frontmatter, body = split_frontmatter(text)
    feedback, _ = parse_blocks(body)
    return Digest(
        meta=_digest_meta(slug, path),
        frontmatter=frontmatter,
        html=_md.render(strip_feedback(body)),
        feedback=[b for b in feedback if isinstance(b, dict)],
    )
