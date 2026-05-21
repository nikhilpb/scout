from pathlib import Path

import pytest

from scout.paths import DataPaths, DataPathsError


def test_flag_overrides_env(tmp_path, monkeypatch):
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.setenv("SCOUT_DATA_DIR", str(tmp_path))
    dp = DataPaths.resolve(str(other))
    assert dp.root == other.resolve()


def test_env_used_when_no_flag(tmp_path, monkeypatch):
    monkeypatch.setenv("SCOUT_DATA_DIR", str(tmp_path))
    dp = DataPaths.resolve(None)
    assert dp.root == tmp_path.resolve()


def test_subdirs_derived_from_root(tmp_path, monkeypatch):
    monkeypatch.setenv("SCOUT_DATA_DIR", str(tmp_path))
    dp = DataPaths.resolve(None)
    assert dp.topics_dir == tmp_path.resolve() / "topics"
    assert dp.output_dir == tmp_path.resolve() / "output"
    assert dp.state_dir == tmp_path.resolve() / "state"
    assert dp.logs_dir == tmp_path.resolve() / "logs"
    assert dp.config_path == tmp_path.resolve() / "scout.toml"


def test_error_when_neither_set(monkeypatch):
    monkeypatch.delenv("SCOUT_DATA_DIR", raising=False)
    with pytest.raises(DataPathsError) as exc:
        DataPaths.resolve(None)
    msg = str(exc.value)
    assert "SCOUT_DATA_DIR" in msg
    assert "--data-dir" in msg


def test_error_when_path_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("SCOUT_DATA_DIR", raising=False)
    missing = tmp_path / "does-not-exist"
    with pytest.raises(DataPathsError) as exc:
        DataPaths.resolve(str(missing))
    assert "does not exist" in str(exc.value)


def test_error_when_path_is_file(tmp_path, monkeypatch):
    monkeypatch.delenv("SCOUT_DATA_DIR", raising=False)
    f = tmp_path / "afile"
    f.write_text("x")
    with pytest.raises(DataPathsError) as exc:
        DataPaths.resolve(str(f))
    assert "not a directory" in str(exc.value)


def test_empty_string_flag_treated_as_unset(tmp_path, monkeypatch):
    monkeypatch.setenv("SCOUT_DATA_DIR", str(tmp_path))
    dp = DataPaths.resolve("")
    assert dp.root == tmp_path.resolve()


def test_dataclass_is_frozen(tmp_path, monkeypatch):
    monkeypatch.setenv("SCOUT_DATA_DIR", str(tmp_path))
    dp = DataPaths.resolve(None)
    with pytest.raises(Exception):
        dp.root = Path("/elsewhere")  # type: ignore[misc]


def test_resolve_expands_user(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    target = tmp_path / "scout-data"
    target.mkdir()
    monkeypatch.delenv("SCOUT_DATA_DIR", raising=False)
    dp = DataPaths.resolve("~/scout-data")
    assert dp.root == target.resolve()
