import textwrap

from scout.cli import main


def test_validate_all_good(tmp_path, capsys, monkeypatch):
    (tmp_path / "topics").mkdir()
    (tmp_path / "topics" / "a.yaml").write_text(textwrap.dedent("""
        title: A
        description: d
        cadence: "0 * * * *"
        model: m
        prompt: {template: briefing}
    """))
    monkeypatch.chdir(tmp_path)
    assert main(["validate"]) == 0


def test_validate_one_bad(tmp_path, capsys, monkeypatch):
    (tmp_path / "topics").mkdir()
    (tmp_path / "topics" / "bad.yaml").write_text("not: valid")
    monkeypatch.chdir(tmp_path)
    assert main(["validate"]) != 0
    err = capsys.readouterr().err
    assert "bad.yaml" in err
