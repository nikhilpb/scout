from datetime import datetime, timezone

from scout.config import TopicConfig
from scout.scheduler import is_due, select_due
from scout.state import TopicState

UTC = timezone.utc


def cfg(cadence="0 * * * *"):
    return TopicConfig(
        title="t", description="d", cadence=cadence, model="m",
        prompt={"template": "briefing"},
    )


def state(last_run):
    return TopicState(
        last_run=last_run, last_status="ok",
        last_error=None, last_duration_seconds=1.0,
    )


def test_no_state_is_due():
    assert is_due(cfg(), None, datetime(2026, 5, 20, 12, tzinfo=UTC)) is True


def test_just_ran_not_due():
    now = datetime(2026, 5, 20, 12, 5, tzinfo=UTC)
    st = state(now)
    assert is_due(cfg(), st, now) is False


def test_hour_later_is_due():
    st = state(datetime(2026, 5, 20, 12, 0, tzinfo=UTC))
    now = datetime(2026, 5, 20, 13, 1, tzinfo=UTC)
    assert is_due(cfg(), st, now) is True


def test_daily_cadence_just_before_slot():
    st = state(datetime(2026, 5, 20, 7, 0, tzinfo=UTC))
    now = datetime(2026, 5, 21, 6, 59, tzinfo=UTC)
    assert is_due(cfg("0 7 * * *"), st, now) is False
    now2 = datetime(2026, 5, 21, 7, 0, tzinfo=UTC)
    assert is_due(cfg("0 7 * * *"), st, now2) is True


def test_select_due_filters():
    topics = {"a": cfg("0 * * * *"), "b": cfg("0 7 * * *")}
    states = {
        "a": state(datetime(2026, 5, 20, 11, 0, tzinfo=UTC)),
        "b": state(datetime(2026, 5, 20, 7, 0, tzinfo=UTC)),
    }
    now = datetime(2026, 5, 20, 12, 30, tzinfo=UTC)
    due = select_due(topics, states, now)
    assert due == {"a"}
