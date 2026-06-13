import textwrap
from datetime import datetime, timezone

import pytest

from scout.state import read_state
from tests.conftest import read_trajectory
from tests.smoke.conftest import requires_google_key


@pytest.mark.smoke
@requires_google_key
def test_scout_run_against_gemini(tmp_path, monkeypatch):
    # minimal scout.toml so the worker resolves defaults
    (tmp_path / "scout.toml").write_text(
        textwrap.dedent("""
        [defaults]
        runner = "builtin"
        model = "gemini/gemini-2.5-flash"
        timeout_seconds = 60
    """)
    )
    (tmp_path / "topics").mkdir()
    (tmp_path / "topics" / "smoke.yaml").write_text(
        textwrap.dedent("""
        title: Smoke
        description: A smoke test topic.
        cadence: "0 * * * *"
        model: "gemini/gemini-2.5-flash"
        prompt:
          inline: |
            Produce a one-paragraph markdown digest stating exactly:
            'Smoke test ran successfully.' Then immediately call write_digest
            with that markdown body and stop.
        tools:
          - write_digest
    """)
    )
    monkeypatch.setenv("SCOUT_DATA_DIR", str(tmp_path))

    from scout.cli import main

    rc = main(["run", "--topic", "smoke", "--force"])
    assert rc == 0, f"scout run failed with rc={rc}"

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    p = tmp_path / "output" / "smoke" / f"{today}.md"
    assert p.exists()
    content = p.read_text()
    assert "runner: builtin" in content
    assert "model: gemini/gemini-2.5-flash" in content
    assert "write_digest: 1" in content

    st = read_state("smoke", tmp_path / "state")
    assert st is not None and st.last_status == "ok"

    traj_files = list((tmp_path / "trajectories" / "smoke").glob("*.jsonl"))
    assert len(traj_files) == 1
    recs = read_trajectory(traj_files[0])
    types = [r["type"] for r in recs]
    assert types[0] == "run"          # worker wrote the header
    assert "message" in types
    assert "artifact" in types
    assert types[-1] == "result" and recs[-1]["status"] == "ok"
