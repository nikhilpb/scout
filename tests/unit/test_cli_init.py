from pathlib import Path

from scout.cli import main

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_init_creates_structure(tmp_path):
    root = tmp_path / "data"
    assert main(["init", str(root)]) == 0
    assert (root / "topics").is_dir()
    assert (root / "output").is_dir()
    assert (root / "state").is_dir()
    assert (root / "logs").is_dir()
    assert (root / "scout.toml").is_file()
    assert (root / ".gitignore").read_text() == "state/\nlogs/\n"
    assert (root / "topics" / ".gitkeep").is_file()
    assert (root / "output" / ".gitkeep").is_file()


def test_init_scout_toml_content(tmp_path):
    root = tmp_path / "data"
    main(["init", str(root)])
    text = (root / "scout.toml").read_text()
    assert "[defaults]" in text
    assert 'runner = "builtin"' in text


def test_init_does_not_create_git_repo(tmp_path):
    root = tmp_path / "data"
    main(["init", str(root)])
    assert not (root / ".git").exists()


def test_init_refuses_existing_data_repo(tmp_path):
    root = tmp_path / "data"
    assert main(["init", str(root)]) == 0
    (root / "scout.toml").write_text("CUSTOM")
    assert main(["init", str(root)]) == 2
    assert (root / "scout.toml").read_text() == "CUSTOM"


def test_init_uses_data_dir_flag(tmp_path):
    root = tmp_path / "data"
    assert main(["--data-dir", str(root), "init"]) == 0
    assert (root / "scout.toml").is_file()


def test_init_uses_env(tmp_path, monkeypatch):
    root = tmp_path / "data"
    monkeypatch.setenv("SCOUT_DATA_DIR", str(root))
    assert main(["init"]) == 0
    assert (root / "scout.toml").is_file()


def test_init_positional_beats_flag_and_env(tmp_path, monkeypatch):
    pos = tmp_path / "pos"
    monkeypatch.setenv("SCOUT_DATA_DIR", str(tmp_path / "env"))
    assert main(["--data-dir", str(tmp_path / "flag"), "init", str(pos)]) == 0
    assert (pos / "scout.toml").is_file()
    assert not (tmp_path / "flag").exists()
    assert not (tmp_path / "env").exists()


def test_init_errors_without_any_path(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("SCOUT_DATA_DIR", raising=False)
    assert main(["init"]) == 2
    err = capsys.readouterr().err
    assert "scout:" in err


def test_default_scout_toml_matches_example():
    from scout import bootstrap

    example = (REPO_ROOT / "scout.toml.example").read_text()
    assert bootstrap.DEFAULT_SCOUT_TOML == example
