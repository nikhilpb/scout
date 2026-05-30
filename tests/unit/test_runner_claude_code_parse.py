import json

from scout.runners.claude_code import ClaudeCodeRunner


def _stream(*events: dict) -> str:
    return "\n".join(json.dumps(e) for e in events) + "\n"


def test_parse_stream_full_metrics():
    stdout = _stream(
        {"type": "system", "subtype": "init", "model": "claude-sonnet-4-6"},
        {"type": "assistant", "message": {"content": [
            {"type": "text", "text": "thinking out loud"},
            {"type": "tool_use", "id": "a", "name": "WebSearch", "input": {}}]}},
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "b", "name": "WebFetch", "input": {}}]}},
        {"type": "result", "subtype": "success", "is_error": False, "num_turns": 3,
         "total_cost_usd": 0.25,
         "modelUsage": {"claude-sonnet-4-6": {
             "inputTokens": 100, "outputTokens": 50,
             "cacheReadInputTokens": 900, "cacheCreationInputTokens": 10,
             "costUSD": 0.25}},
         "permission_denials": []},
    )
    m = ClaudeCodeRunner()._parse_stream(stdout)
    assert m["model"] == "claude-sonnet-4-6"
    assert m["tool_calls"] == {"WebSearch": 1, "WebFetch": 1}
    assert m["tokens"] == {"input": 1010, "output": 50}
    assert m["cost_usd"] == 0.25
    assert m["num_turns"] == 3
    assert m["is_error"] is False
    assert m["error_subtype"] is None


def test_parse_stream_dedupes_tool_use_ids():
    stdout = _stream(
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "dup", "name": "Read", "input": {}}]}},
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "dup", "name": "Read", "input": {}}]}},
        {"type": "result", "subtype": "success", "total_cost_usd": 0.0,
         "modelUsage": {}},
    )
    m = ClaudeCodeRunner()._parse_stream(stdout)
    assert m["tool_calls"] == {"Read": 1}


def test_parse_stream_error_result():
    stdout = _stream(
        {"type": "system", "subtype": "init", "model": "claude-sonnet-4-6"},
        {"type": "result", "subtype": "error_max_turns", "is_error": True,
         "total_cost_usd": 0.4, "modelUsage": {}, "permission_denials": []},
    )
    m = ClaudeCodeRunner()._parse_stream(stdout)
    assert m["is_error"] is True
    assert m["error_subtype"] == "error_max_turns"
    assert m["cost_usd"] == 0.4


def test_parse_stream_ignores_junk_lines():
    stdout = "not json\n" + _stream(
        {"type": "result", "subtype": "success", "total_cost_usd": 0.01,
         "usage": {"input_tokens": 5, "cache_read_input_tokens": 20, "output_tokens": 3}},
    ) + "trailing garbage\n"
    m = ClaudeCodeRunner()._parse_stream(stdout)
    # no modelUsage => fall back to top-level usage
    assert m["tokens"] == {"input": 25, "output": 3}
    assert m["cost_usd"] == 0.01


def test_parse_stream_empty():
    m = ClaudeCodeRunner()._parse_stream("")
    assert m["result"] is None
    assert m["tool_calls"] == {}
    assert m["model"] is None
    assert m["cost_usd"] == 0.0


def test_parse_stream_null_token_fields_do_not_crash():
    # A present-but-null token field must coerce to 0, not raise (int(None)).
    stdout = _stream(
        {"type": "system", "subtype": "init", "model": "claude-sonnet-4-6"},
        {"type": "result", "subtype": "success", "total_cost_usd": 0.5,
         "modelUsage": {"claude-sonnet-4-6": {
             "inputTokens": 100, "outputTokens": None,
             "cacheReadInputTokens": None, "cacheCreationInputTokens": 10,
             "costUSD": 0.5}}},
    )
    m = ClaudeCodeRunner()._parse_stream(stdout)
    assert m["tokens"] == {"input": 110, "output": 0}
    assert m["cost_usd"] == 0.5


def test_parse_stream_non_numeric_cost_does_not_crash():
    stdout = _stream(
        {"type": "result", "subtype": "success", "total_cost_usd": "N/A",
         "modelUsage": {}},
    )
    m = ClaudeCodeRunner()._parse_stream(stdout)
    assert m["cost_usd"] == 0.0


def test_parse_stream_skips_non_dict_model_usage_entry():
    # A null/scalar modelUsage value must not break token summing or model pick.
    stdout = _stream(
        {"type": "result", "subtype": "success", "total_cost_usd": 0.3,
         "modelUsage": {
             "claude-broken": None,
             "claude-sonnet-4-6": {"inputTokens": 50, "outputTokens": 5,
                                   "costUSD": 0.3}}},
    )
    m = ClaudeCodeRunner()._parse_stream(stdout)
    assert m["tokens"] == {"input": 50, "output": 5}
    # init had no model => picked from the well-formed entry, not the null one
    assert m["model"] == "claude-sonnet-4-6"
