import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scout.agent.llm import Response, ToolCall
from scout.runners import builtin as br
from scout.worker import run_topic
from tests.conftest import make_data_paths
from tests.fakes.llm import FakeLLMClient


@pytest.mark.integration
def test_full_pipeline(tmp_path, monkeypatch):
    # Data repo lives in tmp_path; code stays in the real source tree.
    data_root = tmp_path / "scout-data"
    data_root.mkdir()

    # Seed the data repo: topics dir + smoke topic fixture.
    (data_root / "topics").mkdir()
    shutil.copy(
        Path(__file__).parent.parent / "fixtures" / "topics" / "smoke.yaml",
        data_root / "topics" / "smoke.yaml",
    )

    # Script the LLM: a single call to write_digest
    script = [
        Response(
            text=None,
            tool_calls=[ToolCall(
                "1", "write_digest",
                {"markdown_body": "# Smoke\n\nHello."},
            )],
            input_tokens=10, output_tokens=2, cost_usd=0.001,
        ),
    ]
    fake = FakeLLMClient(script)
    monkeypatch.setattr(br, "default_llm_client", lambda: fake)

    data = make_data_paths(data_root)
    rc = run_topic("smoke", data=data, force=True)
    assert rc == 0

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    p = data.output_dir / "smoke" / f"{today}.md"
    assert p.exists()
    content = p.read_text()
    assert "# Smoke" in content
    assert content.startswith("---\n")

    from scout.state import read_state
    st = read_state("smoke", data.state_dir)
    assert st is not None
    assert st.last_status == "ok"
    # A successful run records itself as the last success (window upper bound).
    assert st.last_success_run is not None
    assert st.last_success_run == st.last_run


@pytest.mark.integration
def test_failed_run_preserves_success_window(tmp_path, monkeypatch):
    """A failed run advances last_run but must NOT advance last_success_run, and
    the window lower bound handed to the runner is the prior success — so a
    failure cannot silently drop the slice it owed."""
    from scout import worker as wk
    from scout.runner import RunResult
    from scout.state import TopicState, read_state, write_state_atomic

    data_root = tmp_path / "scout-data"
    (data_root / "topics").mkdir(parents=True)
    shutil.copy(
        Path(__file__).parent.parent / "fixtures" / "topics" / "smoke.yaml",
        data_root / "topics" / "smoke.yaml",
    )
    data = make_data_paths(data_root)

    prior_success = datetime(2026, 5, 20, 3, 0, tzinfo=timezone.utc)
    write_state_atomic("smoke", data.state_dir, TopicState(
        last_run=prior_success, last_status="ok", last_error=None,
        last_duration_seconds=1.0, last_success_run=prior_success,
    ))

    seen = {}

    class FailingRunner:
        def execute(self, topic, paths, limits, *, traj, now, last_run=None):
            seen["last_run"] = last_run
            return RunResult("failed", "boom", None, 0.1, {})

    monkeypatch.setattr(wk, "make_runner", lambda name: FailingRunner())

    rc = run_topic("smoke", data=data, force=True)
    assert rc == 1

    # The runner was scoped to the last *successful* run, not the failed attempt.
    assert seen["last_run"] == prior_success
    st = read_state("smoke", data.state_dir)
    assert st.last_status == "failed"
    assert st.last_run > prior_success          # attempt advanced
    assert st.last_success_run == prior_success  # success window preserved

    # The worker guarantees a terminal `result` even though FailingRunner never
    # wrote one, so the trajectory isn't left looking "running".
    from tests.conftest import only_trajectory
    recs = only_trajectory(data.trajectories_dir, "smoke")
    assert recs[0]["type"] == "run"
    assert recs[-1]["type"] == "result"
    assert recs[-1]["status"] == "failed"
    assert recs[-1]["reason"] == "boom"
