import textwrap

import pytest

from scout.config import ConfigError, GlobalConfig, load_global_config


def test_loads_from_toml(tmp_path):
    p = tmp_path / "scout.toml"
    p.write_text(textwrap.dedent("""
        [defaults]
        runner = "builtin"
        model = "anthropic/claude-sonnet-4-6"
        timeout_seconds = 300

        [scheduler]
        max_concurrent_workers = 3

        [git]
        author_name = "Scout"
        author_email = "scout@localhost"
        remote = "origin"
        branch = "main"
    """))
    cfg = load_global_config(p)
    assert isinstance(cfg, GlobalConfig)
    assert cfg.defaults.runner == "builtin"
    assert cfg.scheduler.max_concurrent_workers == 3
    assert cfg.git.branch == "main"


def test_missing_file_returns_defaults(tmp_path):
    cfg = load_global_config(tmp_path / "does-not-exist.toml")
    assert cfg.defaults.runner == "builtin"
    assert cfg.defaults.timeout_seconds == 300
    assert cfg.scheduler.max_concurrent_workers == 3


def test_malformed_toml_raises(tmp_path):
    p = tmp_path / "scout.toml"
    p.write_text("this is not = valid = toml [")
    with pytest.raises(ConfigError):
        load_global_config(p)
