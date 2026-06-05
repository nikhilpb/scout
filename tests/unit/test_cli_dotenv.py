import os

from scout.cli import _load_env_files, main


def test_loads_env_from_data_dir(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    (tmp_path / ".env").write_text("GEMINI_API_KEY=from-data-dir\n")
    _load_env_files(str(tmp_path))
    assert os.environ["GEMINI_API_KEY"] == "from-data-dir"


def test_loads_env_from_data_dir_via_env_var(tmp_path, monkeypatch):
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    (tmp_path / ".env").write_text("BRAVE_SEARCH_API_KEY=brave-key\n")
    monkeypatch.setenv("SCOUT_DATA_DIR", str(tmp_path))
    _load_env_files(None)
    assert os.environ["BRAVE_SEARCH_API_KEY"] == "brave-key"


def test_real_env_takes_precedence(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "from-real-env")
    (tmp_path / ".env").write_text("GEMINI_API_KEY=from-dotenv\n")
    _load_env_files(str(tmp_path))
    assert os.environ["GEMINI_API_KEY"] == "from-real-env"


def test_data_dir_wins_over_cwd(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    data_dir = tmp_path / "data"
    cwd = tmp_path / "cwd"
    data_dir.mkdir()
    cwd.mkdir()
    (data_dir / ".env").write_text("GEMINI_API_KEY=from-data-dir\n")
    (cwd / ".env").write_text("GEMINI_API_KEY=from-cwd\n")
    monkeypatch.chdir(cwd)
    _load_env_files(str(data_dir))
    assert os.environ["GEMINI_API_KEY"] == "from-data-dir"


def test_missing_env_file_is_noop(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    _load_env_files(str(tmp_path))
    assert "GEMINI_API_KEY" not in os.environ


def test_main_loads_env_before_command(tmp_path, monkeypatch):
    # `validate` exercises the full main() path including env loading.
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    (tmp_path / "topics").mkdir()
    (tmp_path / ".env").write_text("GEMINI_API_KEY=loaded-by-main\n")
    monkeypatch.setenv("SCOUT_DATA_DIR", str(tmp_path))
    assert main(["validate"]) == 0
    assert os.environ["GEMINI_API_KEY"] == "loaded-by-main"
