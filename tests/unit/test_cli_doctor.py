import json
from datetime import datetime, timezone

from scout.cli import main


def test_doctor_reports(tmp_path, capsys, monkeypatch):
    now = datetime.now(timezone.utc)
    traj = tmp_path / "trajectories" / "ai"
    traj.mkdir(parents=True)
    f = traj / "01HXTRAJECTORYDOCTOR00000.jsonl"
    f.write_text(
        json.dumps({
            "type": "run", "id": "r", "parent_id": None, "ts": now.isoformat(),
            "seq": 0, "schema": "scout.trajectory/1", "run_id": "r",
            "topic": "ai", "runner": "builtin", "model": "m",
        }) + "\n"
        + json.dumps({
            "type": "result", "id": "x", "parent_id": "r", "ts": now.isoformat(),
            "seq": 1, "status": "ok", "duration_seconds": 12.0,
            "usage": {"cost_usd": 0.05}, "tool_calls": {},
        }) + "\n"
    )
    monkeypatch.setenv("SCOUT_DATA_DIR", str(tmp_path))
    assert main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "ai" in out
    assert "0.05" in out
