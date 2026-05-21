import pytest

from scout.agent.llm import Response
from tests.fakes.llm import FakeLLMClient


def test_pops_in_order():
    c = FakeLLMClient([Response(text="a"), Response(text="b")])
    assert c.call([], [], "m").text == "a"
    assert c.call([], [], "m").text == "b"


def test_exhaustion_raises():
    c = FakeLLMClient([Response(text="a")])
    c.call([], [], "m")
    with pytest.raises(AssertionError):
        c.call([], [], "m")
