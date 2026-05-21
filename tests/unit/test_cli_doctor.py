import json
from datetime import datetime, timezone

from scout.cli import main


def test_doctor_reports(tmp_path, capsys, monkeypatch):
    now = datetime.now(timezone.utc)
    logs = tmp_path / "logs" / "ai"
    logs.mkdir(parents=True)
    f = logs / now.strftime("%Y-%m-%d-%H%M%S.jsonl")
    f.write_text(
        json.dumps({"ts": now.isoformat(), "event": "run_start"}) + "\n"
        + json.dumps({
            "ts": now.isoformat(), "event": "run_end",
            "status": "ok", "duration_seconds": 12.0, "cost_usd": 0.05,
        }) + "\n"
    )
    monkeypatch.chdir(tmp_path)
    assert main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "ai" in out
    assert "0.05" in out
