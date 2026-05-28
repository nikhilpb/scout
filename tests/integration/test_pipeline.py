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
