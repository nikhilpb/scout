import jsonschema
import pytest

from scout.agent.tools import registry
from scout.config import BUILTIN_TOOLS


@pytest.mark.xfail(reason="registry filled in across Tasks 11–15")
def test_registry_covers_all_builtin_tools():
    reg = registry()
    assert set(reg.keys()) == BUILTIN_TOOLS


def test_each_tool_has_valid_jsonschema():
    reg = registry()
    for name, tool in reg.items():
        jsonschema.Draft202012Validator.check_schema(tool.input_schema)


def test_browser_use_not_default_enabled():
    reg = registry()
    if "browser_use" in reg:
        assert reg["browser_use"].default_enabled is False
        others = {n: t for n, t in reg.items() if n != "browser_use"}
        assert all(t.default_enabled for t in others.values())
