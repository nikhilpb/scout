from scout.feedback import append_block, find_latest, parse_blocks

TEXT = """\
# Digest

Some body.

<!-- scout-feedback
rating: 4
notes: Liked it.
-->

More body.

<!-- scout-feedback
not: even: valid
-->
"""


def test_parse_extracts_valid_and_skips_invalid(caplog):
    blocks, errors = parse_blocks(TEXT)
    assert len(blocks) == 1
    assert blocks[0]["rating"] == 4
    assert errors == 1


def test_append_block(tmp_path):
    f = tmp_path / "x.md"
    f.write_text("body")
    append_block(f, {"rating": 5, "notes": "great"})
    out = f.read_text()
    assert out.startswith("body")
    assert "scout-feedback" in out
    assert "rating: 5" in out


def test_find_latest(tmp_path):
    d = tmp_path / "ai"
    d.mkdir()
    (d / "2026-05-18.md").write_text("a")
    (d / "2026-05-20.md").write_text("b")
    latest = find_latest("ai", tmp_path)
    assert latest.name == "2026-05-20.md"
