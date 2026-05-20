import threading
import time
from datetime import datetime, timezone

from scout.state import TopicState, acquire_lock, read_state, write_state_atomic


def test_read_missing_returns_none(tmp_path):
    assert read_state("ai-research", tmp_path) is None


def test_write_then_read_roundtrip(tmp_path):
    s = TopicState(
        last_run=datetime(2026, 5, 20, 7, 0, 0, tzinfo=timezone.utc),
        last_status="ok",
        last_error=None,
        last_duration_seconds=38.2,
    )
    write_state_atomic("ai-research", tmp_path, s)
    out = read_state("ai-research", tmp_path)
    assert out == s


def test_corrupted_file_returns_none(tmp_path, caplog):
    (tmp_path / "ai-research.json").write_text("not json {")
    assert read_state("ai-research", tmp_path) is None
    assert any("corrupt" in r.message.lower() for r in caplog.records)


def test_atomicity_via_tmp(tmp_path):
    s = TopicState(
        last_run=datetime(2026, 5, 20, tzinfo=timezone.utc),
        last_status="ok",
        last_error=None,
        last_duration_seconds=1.0,
    )
    write_state_atomic("x", tmp_path, s)
    assert not list(tmp_path.glob("*.tmp"))


def test_lock_exclusive(tmp_path):
    acquired = []
    done = threading.Event()

    def worker():
        with acquire_lock("x", tmp_path) as got:
            acquired.append(got)
            if got:
                done.wait(timeout=1.0)

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start()
    time.sleep(0.05)  # give t1 time to grab the lock
    t2.start()
    t2.join(timeout=1.0)
    done.set()
    t1.join(timeout=1.0)
    assert sorted(acquired) == [False, True]
