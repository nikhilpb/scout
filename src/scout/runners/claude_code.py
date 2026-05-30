from __future__ import annotations

import json
import subprocess
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from scout.config import LoadedTopic
from scout.output import DigestRecord, compose_digest
from scout.runlog import RunLog
from scout.runner import Limits, Paths, RunResult

PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "prompts"

# The only tools a digest run needs: WebSearch and WebFetch gather sources; Read
# and Glob let the agent inspect prior digests for de-duplication; Write saves the
# digest. This list is passed BOTH as `--tools` (which restricts the set of tools
# the model can see at all — so it can't reach Bash, Task, or the multi-agent
# Workflow tool and wander off) and as `--allowedTools` (which pre-approves them so
# they run without a permission prompt on a host whose default mode would
# otherwise ask). `--tools` is the load-bearing one: without it, a host configured
# with an "auto"/skip-prompt permission policy lets the agent call anything.
DIGEST_TOOLS = ["WebSearch", "WebFetch", "Read", "Glob", "Write"]

UNKNOWN = "unknown"


class ClaudeCodeRunner:
    """Runs a topic through the Claude Code CLI (`claude -p`).

    The CLI owns the agent loop and its own tool set; Scout drives it as a
    subprocess. Unlike a plain subprocess wrapper, this runner asks the CLI for
    ``stream-json`` output and parses it, so the digest frontmatter and run log
    carry real model / tool-call / token / cost metrics (rather than ``unknown``)
    whenever the CLI emits them.
    """

    def execute(
        self,
        topic: LoadedTopic,
        paths: Paths,
        limits: Limits,
        *,
        run_log: RunLog,
        now: datetime,
    ) -> RunResult:
        cfg = topic.config
        model = cfg.model or None
        prompt = self._build_prompt(topic, now)
        # Pre-create the topic's output folder so Write always has a target and
        # Glob has a directory to list when reviewing prior digests.
        (paths.output_dir / topic.slug).mkdir(parents=True, exist_ok=True)

        run_log.event(
            "run_start", slug=topic.slug, runner="claude-code", model=model or UNKNOWN
        )
        cmd = [
            "claude", "-p", prompt,
            "--output-format", "stream-json", "--verbose",
            "--strict-mcp-config",  # ignore the host's MCP servers — keep the run focused
            "--permission-mode", "default",
        ]
        if model:
            cmd += ["--model", model]
        # `--tools` bounds what the model can call; `--allowedTools` pre-approves
        # those same tools. `--allowedTools` is variadic and goes last so nothing
        # following it gets swallowed as a tool name.
        cmd += ["--tools", *DIGEST_TOOLS, "--allowedTools", *DIGEST_TOOLS]

        start = time.monotonic()
        try:
            proc = subprocess.run(
                cmd,
                cwd=paths.output_dir,
                capture_output=True,
                text=True,
                timeout=limits.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            duration = time.monotonic() - start
            # Salvage whatever the CLI streamed before we killed it, so a timeout
            # is debuggable and partial tool activity still lands in the run log.
            partial = self._as_text(exc.stdout)
            stderr = self._as_text(exc.stderr)
            metrics = self._parse_stream(partial)
            run_log.event(
                "subprocess_output", returncode=None, timed_out=True,
                stderr=stderr[-2000:], stdout_tail=partial[-1000:],
            )
            # Salvage cost/tokens too, not just tool calls — a CLI that streamed a
            # full result event before hanging still has real usage to record.
            self._replay_metrics(run_log, metrics)
            return self._fail(run_log, "timeout", duration, summary=run_log.summary())
        duration = time.monotonic() - start

        metrics = self._parse_stream(proc.stdout)
        run_log.event(
            "subprocess_output",
            returncode=proc.returncode,
            stderr=proc.stderr[-2000:],
            stdout_tail=proc.stdout[-1000:],
        )
        # Replay parsed activity into the run log so RunLog.summary() aggregates
        # tool calls, tokens, and cost exactly as it does for the builtin runner.
        self._replay_metrics(run_log, metrics)

        summary = run_log.summary()

        # Prefer the CLI's own success signal (the result event) over the raw exit
        # code: a benign non-zero exit after a run that the CLI itself reported as
        # successful should not throw away a digest it already wrote. Only fall back
        # to the exit code when there is no result event to trust.
        if metrics["is_error"]:
            reason = metrics["error_subtype"] or "cli_error"
            return self._fail(run_log, reason, duration, summary=summary)
        if metrics["result"] is None and proc.returncode != 0:
            return self._fail(run_log, f"exit_{proc.returncode}", duration, summary=summary)

        out_path = paths.output_dir / topic.slug / f"{now.strftime('%Y-%m-%d')}.md"
        if not out_path.exists():
            return self._fail(run_log, "no_digest", duration, summary=summary)

        body = out_path.read_text()
        resolved_model = metrics["model"] or model or UNKNOWN
        if metrics["result"] is not None:
            tool_calls: dict | str = summary["tool_calls"]
            tokens: dict | str = summary["tokens"]
            cost_usd: float | str = round(summary["cost_usd"], 4)
        else:
            # The CLI wrote a digest but emitted no parseable result (e.g. a stubbed
            # CLI, or a crash before the final event). We have no reliable view of
            # the run, so report every metric uniformly as `unknown` rather than
            # implying "zero tools / zero cost".
            tool_calls = tokens = cost_usd = UNKNOWN
        rec = DigestRecord(
            topic=topic.slug,
            date=now.strftime("%Y-%m-%d"),
            runner="claude-code",
            model=resolved_model,
            duration_seconds=round(duration, 2),
            tool_calls=tool_calls,
            tokens=tokens,
            cost_usd=cost_usd,
        )
        out_path.write_text(compose_digest(rec, body))
        run_log.event("run_end", status="ok", duration_seconds=duration, **summary)
        return RunResult("ok", None, out_path, duration, summary)

    def _replay_metrics(self, run_log: RunLog, metrics: dict) -> None:
        """Feed parsed stream activity into the run log.

        Re-emits one ``tool_call`` event per observed call and a single
        ``llm_turn`` carrying the aggregate tokens/cost, so ``RunLog.summary()``
        aggregates claude-code runs the same way it does builtin ones. Used by
        both the success path and the timeout-salvage path.
        """
        for name, count in metrics["tool_calls"].items():
            for _ in range(count):
                run_log.event("tool_call", tool=name)
        if metrics["result"] is not None:
            run_log.event(
                "llm_turn",
                input_tokens=metrics["tokens"]["input"],
                output_tokens=metrics["tokens"]["output"],
                cost_usd=metrics["cost_usd"],
                num_turns=metrics["num_turns"],
            )
        if metrics["permission_denials"]:
            run_log.event("permission_denials", denials=metrics["permission_denials"])

    def _fail(
        self,
        run_log: RunLog,
        reason: str,
        duration: float,
        *,
        summary: dict | None = None,
    ) -> RunResult:
        fields = summary if summary is not None else {
            "tool_calls": UNKNOWN, "tokens": UNKNOWN, "cost_usd": UNKNOWN,
        }
        run_log.event(
            "run_end", status="failed", reason=reason,
            duration_seconds=duration, **fields,
        )
        return RunResult("failed", reason, None, duration, summary or {})

    @staticmethod
    def _as_text(value) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode("utf-8", "replace")
        return value

    @staticmethod
    def _int(value) -> int:
        """Coerce a stream field to int, treating null/missing/garbage as 0.

        ``dict.get(key, 0)`` only returns the default when the key is absent — a
        present-but-``null`` JSON field returns ``None``, and ``int(None)`` raises.
        """
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _num(value) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def _parse_stream(self, stdout: str) -> dict:
        """Parse Claude Code ``stream-json`` output into a metrics dict.

        The stream is one JSON object per line: a ``system``/``init`` event (the
        resolved model), ``assistant`` events whose content may hold ``tool_use``
        blocks, and a final ``result`` event carrying cost, token usage, and
        ``modelUsage``. Anything unparseable is skipped so a partial or stubbed
        stream degrades gracefully.
        """
        tool_calls: Counter[str] = Counter()
        seen_tool_ids: set[str] = set()
        model: str | None = None
        result: dict | None = None

        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            etype = ev.get("type")
            if etype == "system" and ev.get("subtype") == "init":
                model = ev.get("model") or model
            elif etype == "assistant":
                for block in ev.get("message", {}).get("content", []):
                    if not isinstance(block, dict) or block.get("type") != "tool_use":
                        continue
                    tid = block.get("id")
                    if tid is not None and tid in seen_tool_ids:
                        continue
                    if tid is not None:
                        seen_tool_ids.add(tid)
                    tool_calls[block.get("name", "?")] += 1
            elif etype == "result":
                result = ev

        tokens = {"input": 0, "output": 0}
        cost_usd = 0.0
        num_turns = None
        is_error = False
        error_subtype = None
        permission_denials: list = []

        if result is not None:
            cost_usd = self._num(result.get("total_cost_usd"))
            num_turns = result.get("num_turns")
            is_error = bool(result.get("is_error"))
            subtype = result.get("subtype")
            if subtype and subtype != "success":
                error_subtype = subtype
            permission_denials = result.get("permission_denials") or []
            model_usage = result.get("modelUsage") or {}
            # Keep only well-formed per-model entries; a null/scalar value would
            # break both the token sum and the max(...) model pick below.
            model_usage = {
                k: v for k, v in model_usage.items() if isinstance(v, dict)
            }
            if model_usage:
                for usage in model_usage.values():
                    tokens["input"] += (
                        self._int(usage.get("inputTokens"))
                        + self._int(usage.get("cacheReadInputTokens"))
                        + self._int(usage.get("cacheCreationInputTokens"))
                    )
                    tokens["output"] += self._int(usage.get("outputTokens"))
                if model is None:
                    model = max(
                        model_usage.items(),
                        key=lambda kv: self._num(kv[1].get("costUSD")),
                    )[0]
            else:
                usage = result.get("usage") or {}
                tokens["input"] = (
                    self._int(usage.get("input_tokens"))
                    + self._int(usage.get("cache_creation_input_tokens"))
                    + self._int(usage.get("cache_read_input_tokens"))
                )
                tokens["output"] = self._int(usage.get("output_tokens"))

        return {
            "tool_calls": tool_calls,
            "model": model,
            "result": result,
            "tokens": tokens,
            "cost_usd": cost_usd,
            "num_turns": num_turns,
            "is_error": is_error,
            "error_subtype": error_subtype,
            "permission_denials": permission_denials,
        }

    def _build_prompt(self, topic: LoadedTopic, now: datetime) -> str:
        cfg = topic.config
        template = self._load_body(cfg.prompt)
        rel = f"{topic.slug}/{now.strftime('%Y-%m-%d')}.md"
        return (
            f'You are Scout\'s research agent producing a markdown digest for the '
            f'topic "{cfg.title}".\n\n'
            f"Description: {cfg.description}\n\n"
            "Tools available to you: WebSearch and WebFetch to discover and read "
            "sources; Read and Glob to inspect files; Write to save the digest. "
            "No other tools are available.\n\n"
            "Seed sources (starting points, not exhaustive — use WebSearch and "
            "WebFetch to find the most recent primary sources):\n"
            + "\n".join(self._source_lines(cfg.sources))
            + f"\n\nYour working directory already contains a `{topic.slug}/` "
            f"folder holding any prior digests for this topic. Use Glob "
            f"(`{topic.slug}/*.md`) and Read to review them first, and do not "
            "repeat items already covered.\n\n"
            f"Instructions for the digest content and format:\n{template}\n\n"
            f"When the digest is ready, use Write to save the markdown body — with "
            f"no YAML frontmatter, Scout adds that — to the file `{rel}` relative "
            "to your current working directory. Write the file exactly once and "
            "then stop. Do not print the digest to stdout."
        )

    def _load_body(self, prompt) -> str:
        if prompt.inline:
            return prompt.inline
        template_path = PROMPTS_DIR / f"{prompt.template}.md"
        return template_path.read_text()

    def _source_lines(self, sources) -> list[str]:
        out = []
        for s in sources:
            if s.type == "rss":
                out.append(f"- rss: {s.url}")
            elif s.type == "web":
                out.append(f"- web: {s.url}")
            else:
                out.append(f"- search: {s.query}")
        return out
