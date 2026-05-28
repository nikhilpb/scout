from pathlib import Path

from scout import orchestrator
from scout.paths import DataPaths


def _make_paths(root: Path, output_dir: Path) -> DataPaths:
    return DataPaths(
        root=root,
        topics_dir=root / "topics",
        output_dir=output_dir,
        state_dir=root / "state",
        logs_dir=root / "logs",
        config_path=root / "scout.toml",
    )


def test_spawn_run_forwards_data_and_output_dir(tmp_path, monkeypatch):
    root = tmp_path / "data"
    out = tmp_path / "custom-out"
    data = _make_paths(root, out)

    captured = {}

    class _Proc:
        returncode = 0

    def fake_run(cmd, *args, **kwargs):
        captured["cmd"] = cmd
        return _Proc()

    monkeypatch.setattr(orchestrator.subprocess, "run", fake_run)

    rc = orchestrator._spawn_run("ai-news", data)
    assert rc == 0

    cmd = captured["cmd"]
    assert "--data-dir" in cmd
    assert cmd[cmd.index("--data-dir") + 1] == str(root)
    assert "--output-dir" in cmd
    assert cmd[cmd.index("--output-dir") + 1] == str(out)
    # output-dir must precede the `run` subcommand (it's a top-level flag)
    assert cmd.index("--output-dir") < cmd.index("run")
