from pathlib import Path

from scout.paths import DataPaths
from scout.server.digests import (
    latest_digests,
    list_digests,
    list_topics,
    load_digest,
    split_frontmatter,
)

DIGEST = """\
---
topic: ai-news
date: '2026-06-08'
runner: builtin
model: gemini/gemini-3.5-flash
duration_seconds: 214.16
tokens: {input: 1000, output: 200}
cost_usd: 0.82
---

# AI News — June 8, 2026

_A short TL;DR with a [link](https://example.com) inside._

## Section

- **Item** — details. — [source](https://example.com)

<!-- scout-feedback
rating: 4
notes: solid digest
-->
"""


def make_data(tmp_path: Path) -> DataPaths:
    for d in ("topics", "output", "state", "logs"):
        (tmp_path / d).mkdir()
    return DataPaths.resolve(str(tmp_path))


def write_digest(data: DataPaths, slug: str, name: str, text: str = DIGEST) -> Path:
    d = data.output_dir / slug
    d.mkdir(exist_ok=True)
    p = d / f"{name}.md"
    p.write_text(text)
    return p


def test_split_frontmatter():
    meta, body = split_frontmatter(DIGEST)
    assert meta["runner"] == "builtin"
    assert body.startswith("# AI News")


def test_split_frontmatter_absent():
    meta, body = split_frontmatter("# Just a body\n")
    assert meta == {}
    assert body == "# Just a body\n"


def test_list_digests_sorted_desc(tmp_path):
    data = make_data(tmp_path)
    write_digest(data, "ai-news", "2026-06-07")
    write_digest(data, "ai-news", "2026-06-08")
    write_digest(data, "ai-news", "2026-06-08-142312")
    names = [m.name for m in list_digests(data, "ai-news")]
    assert names == ["2026-06-08-142312", "2026-06-08", "2026-06-07"]


def test_digest_meta_title_teaser_date(tmp_path):
    data = make_data(tmp_path)
    write_digest(data, "ai-news", "2026-06-08")
    (m,) = list_digests(data, "ai-news")
    assert m.title == "AI News — June 8, 2026"
    assert m.teaser == "A short TL;DR with a link inside."
    assert m.date == "2026-06-08"
    assert m.pretty_date == "June 8, 2026"
    assert m.id == "ai-news/2026-06-08"


def test_list_topics_reads_yaml_and_disabled(tmp_path):
    data = make_data(tmp_path)
    write_digest(data, "ai-news", "2026-06-08")
    write_digest(data, "old-topic", "2026-01-01")
    (data.topics_dir / "ai-news.yaml").write_text("title: AI News\ndescription: Daily AI.\n")
    (data.topics_dir / "old-topic.yaml.disabled").write_text("title: Old Topic\n")
    # An output file directly under output/ (e.g. index.md) is not a topic.
    (data.output_dir / "index.md").write_text("# index\n")

    topics = {t.slug: t for t in list_topics(data)}
    assert set(topics) == {"ai-news", "old-topic"}
    assert topics["ai-news"].title == "AI News"
    assert topics["ai-news"].description == "Daily AI."
    assert not topics["ai-news"].disabled
    assert topics["old-topic"].title == "Old Topic"
    assert topics["old-topic"].disabled


def test_list_topics_fallback_title(tmp_path):
    data = make_data(tmp_path)
    write_digest(data, "ai-news", "2026-06-08")
    (t,) = list_topics(data)
    assert t.title == "Ai news"


def test_latest_digests_merges_across_topics(tmp_path):
    data = make_data(tmp_path)
    write_digest(data, "a-topic", "2026-06-07")
    write_digest(data, "b-topic", "2026-06-08")
    write_digest(data, "a-topic", "2026-06-09")
    feed = latest_digests(list_topics(data))
    assert [m.id for m in feed] == [
        "a-topic/2026-06-09",
        "b-topic/2026-06-08",
        "a-topic/2026-06-07",
    ]
    assert [m.id for m in latest_digests(list_topics(data), limit=1)] == ["a-topic/2026-06-09"]


def test_load_digest_renders_and_strips(tmp_path):
    data = make_data(tmp_path)
    write_digest(data, "ai-news", "2026-06-08")
    digest = load_digest(data, "ai-news", "2026-06-08")
    assert digest is not None
    assert "<h1>" in digest.html
    assert '<a href="https://example.com">' in digest.html
    assert "<strong>Item</strong>" in digest.html
    # Frontmatter and feedback blocks must not leak into the rendered body.
    assert "duration_seconds" not in digest.html
    assert "scout-feedback" not in digest.html
    assert digest.frontmatter["model"] == "gemini/gemini-3.5-flash"
    assert digest.feedback == [{"rating": 4, "notes": "solid digest"}]


def test_load_digest_rejects_traversal(tmp_path):
    data = make_data(tmp_path)
    write_digest(data, "ai-news", "2026-06-08")
    (tmp_path / "secret.md").write_text("secret")
    assert load_digest(data, "ai-news", "../secret") is None
    assert load_digest(data, "..", "secret") is None
    assert load_digest(data, "ai-news", "nope") is None
