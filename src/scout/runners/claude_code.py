from __future__ import annotations

import hashlib
import json
import subprocess
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Optional

from scout.config import LoadedTopic
from scout.output import DigestRecord, compose_digest, first_heading
from scout.runner import Limits, Paths, RunResult, apply_time_window, subprocess_error
from scout.trajectory import TrajectoryWriter

PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "prompts"

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
        traj: TrajectoryWriter,
        now: datetime,
        last_run: Optional[datetime] = None,
    ) -> RunResult:
        cfg = topic.config
        model = cfg.model or None
        prompt = self._build_prompt(topic, now, last_run)
        # Pre-create the topic's output folder so Write always has a target and
        # Glob has a directory to list when reviewing prior digests.
        (paths.output_dir / topic.slug).mkdir(parents=True, exist_ok=True)

        cmd = [
            "claude", "-p", prompt,
            "--output-format", "stream-json", "--verbose",
            "--strict-mcp-config",  # ignore the host's MCP servers — keep the run focused
            # No `--tools` restriction: let the agent use the full Claude Code
            # built-in tool set (WebSearch/WebFetch/Read/Glob/Write plus Bash,
            # Task, the multi-agent Workflow tool, etc.). A headless `claude -p`
            # run can't answer permission prompts, so bypass them — otherwise any
            # tool that isn't pre-approved would be auto-denied and the agent
            # would stall instead of being able to call it.
            "--permission-mode", "bypassPermissions",
        ]
        if model:
            cmd += ["--model", model]
        if cfg.effort:
            cmd += ["--effort", cfg.effort]

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
            # is debuggable and partial activity still lands in the trajectory.
            partial = self._as_text(exc.stdout)
            metrics = self._parse_stream(partial)
            self._emit_records(traj, partial)
            self._note(traj, metrics)
            return self._fail(traj, "timeout", duration, metrics=metrics,
                              stderr=self._as_text(exc.stderr))
        duration = time.monotonic() - start

        metrics = self._parse_stream(proc.stdout)
        # Translate the stream into trajectory records (assistant messages, tool
        # calls/results) and aggregate tokens/cost, so the trajectory and the
        # digest frontmatter carry the same metrics the builtin runner does.
        self._emit_records(traj, proc.stdout)
        self._note(traj, metrics)

        summary = traj.summary()

        # Prefer the CLI's own success signal (the result event) over the raw exit
        # code: a benign non-zero exit after a run that the CLI itself reported as
        # successful should not throw away a digest it already wrote. Only fall back
        # to the exit code when there is no result event to trust.
        if metrics["is_error"]:
            reason = metrics["error_subtype"] or "cli_error"
            return self._fail(traj, reason, duration, metrics=metrics,
                              stderr=proc.stderr, returncode=proc.returncode)
        if metrics["result"] is None and proc.returncode != 0:
            return self._fail(traj, f"exit_{proc.returncode}", duration, metrics=metrics,
                              stderr=proc.stderr, returncode=proc.returncode)

        out_path = paths.output_dir / topic.slug / f"{now.strftime('%Y-%m-%d')}.md"
        if not out_path.exists():
            return self._fail(traj, "no_digest", duration, metrics=metrics,
                              stderr=proc.stderr, returncode=proc.returncode)

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
        composed = compose_digest(rec, body)
        out_path.write_text(composed)
        rel = paths.rel(out_path)
        usage = self._rich_usage(metrics)
        traj.artifact(
            kind="digest", path=rel, media_type="text/markdown",
            size_bytes=len(composed.encode("utf-8")),
            sha256=hashlib.sha256(composed.encode("utf-8")).hexdigest(),
            summary=first_heading(body),
        )
        traj.result(
            status="ok", duration_seconds=duration, usage=usage,
            tool_calls=summary["tool_calls"], num_turns=metrics["num_turns"],
            permission_denials=metrics["permission_denials"] or None,
            artifacts=[rel],
        )
        return RunResult(
            "ok", None, out_path, duration, summary,
            usage=usage, num_turns=metrics["num_turns"],
            permission_denials=metrics["permission_denials"] or [],
        )

    @staticmethod
    def _note(traj: TrajectoryWriter, metrics: dict) -> None:
        """Roll the parsed aggregate tokens/cost into the trajectory summary."""
        if metrics["result"] is not None:
            traj.note_usage(
                input_tokens=metrics["tokens"]["input"],
                output_tokens=metrics["tokens"]["output"],
                cost_usd=metrics["cost_usd"],
            )

    def _emit_records(self, traj: TrajectoryWriter, stdout: str) -> None:
        """Translate a Claude Code ``stream-json`` transcript into records.

        Assistant events become ``message`` records (text + reasoning + tool_use
        content parts) plus one ``tool_call`` per new tool_use id; user events'
        ``tool_result`` blocks become ``tool_result`` records. Malformed lines are
        skipped so a partial/stubbed stream degrades gracefully.
        """
        seen_tool_ids: set[str] = set()
        call_recs: dict[str, str] = {}
        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(ev, dict):
                continue
            msg = ev.get("message")
            if not isinstance(msg, dict):
                continue
            content = msg.get("content")
            if ev.get("type") == "assistant":
                parts, tool_uses = self._content_parts(content)
                msg_id = (
                    traj.message(
                        "assistant", parts,
                        model=msg.get("model"),
                        stop_reason=msg.get("stop_reason"),
                        usage=self._msg_usage(msg.get("usage")),
                    )
                    if parts
                    else None
                )
                for tu in tool_uses:
                    tid = tu.get("id")
                    if tid is not None and tid in seen_tool_ids:
                        continue
                    if tid is not None:
                        seen_tool_ids.add(tid)
                    rec = traj.tool_call(
                        call_id=tid or "", name=tu.get("name", "?"),
                        arguments=tu.get("input") or {}, parent_id=msg_id,
                    )
                    if tid is not None:
                        call_recs[tid] = rec
            elif ev.get("type") == "user" and isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict) or block.get("type") != "tool_result":
                        continue
                    tuid = block.get("tool_use_id") or ""
                    traj.tool_result(
                        call_id=tuid,
                        status="error" if block.get("is_error") else "ok",
                        result={"content": block.get("content")},
                        parent_id=call_recs.get(tuid),
                    )

    @staticmethod
    def _content_parts(content) -> tuple[list[dict], list[dict]]:
        """Split a Claude message ``content`` into trajectory parts + tool_use blocks."""
        if isinstance(content, str):
            return ([{"type": "text", "text": content}] if content else []), []
        parts: list[dict] = []
        tool_uses: list[dict] = []
        for block in content or []:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text" and block.get("text"):
                parts.append({"type": "text", "text": block["text"]})
            elif btype == "thinking":
                parts.append({"type": "reasoning",
                              "text": block.get("thinking") or block.get("text") or ""})
            elif btype == "tool_use":
                parts.append({"type": "tool_use", "call_id": block.get("id") or "",
                              "name": block.get("name", "?"), "input": block.get("input") or {}})
                tool_uses.append(block)
        return parts, tool_uses

    @staticmethod
    def _msg_usage(usage) -> Optional[dict]:
        if not isinstance(usage, dict):
            return None
        out = {}
        for src, dst in (
            ("input_tokens", "input_tokens"),
            ("output_tokens", "output_tokens"),
            ("cache_read_input_tokens", "cache_read_input_tokens"),
            ("cache_creation_input_tokens", "cache_creation_input_tokens"),
        ):
            if usage.get(src) is not None:
                out[dst] = ClaudeCodeRunner._int(usage.get(src))
        return out or None

    @classmethod
    def _rich_usage(cls, metrics: Optional[dict]) -> dict:
        """Build a trajectory ``result.usage`` from the parsed result event.

        Reports cache-token breakdown and a per-model split (from the CLI's
        ``modelUsage``) that the aggregate frontmatter token count folds together.
        """
        result = metrics.get("result") if metrics else None
        if result is None:
            return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "cost_usd": 0.0}
        model_usage = {
            k: v for k, v in (result.get("modelUsage") or {}).items() if isinstance(v, dict)
        }
        inp = out = crd = cre = 0
        by_model: dict[str, dict] = {}
        for name, v in model_usage.items():
            i = cls._int(v.get("inputTokens"))
            o = cls._int(v.get("outputTokens"))
            rd = cls._int(v.get("cacheReadInputTokens"))
            cc = cls._int(v.get("cacheCreationInputTokens"))
            by_model[name] = {
                "input_tokens": i, "output_tokens": o,
                "cache_read_input_tokens": rd, "cache_creation_input_tokens": cc,
                "cost_usd": cls._num(v.get("costUSD")),
            }
            inp += i
            out += o
            crd += rd
            cre += cc
        if not model_usage:
            u = result.get("usage") or {}
            inp = cls._int(u.get("input_tokens"))
            out = cls._int(u.get("output_tokens"))
            crd = cls._int(u.get("cache_read_input_tokens"))
            cre = cls._int(u.get("cache_creation_input_tokens"))
        total_input = inp + crd + cre
        usage = {
            "input_tokens": total_input, "output_tokens": out,
            "cache_read_input_tokens": crd, "cache_creation_input_tokens": cre,
            "total_tokens": total_input + out,
            "cost_usd": cls._num(result.get("total_cost_usd")),
        }
        if by_model:
            usage["by_model"] = by_model
        return usage

    def _fail(
        self,
        traj: TrajectoryWriter,
        reason: str,
        duration: float,
        *,
        metrics: Optional[dict] = None,
        stderr: Optional[str] = None,
        returncode: Optional[int] = None,
    ) -> RunResult:
        usage = self._rich_usage(metrics) if metrics else None
        num_turns = metrics.get("num_turns") if metrics else None
        denials = (metrics.get("permission_denials") if metrics else None) or None
        traj.result(
            status="failed", reason=reason, duration_seconds=duration,
            usage=usage, num_turns=num_turns, permission_denials=denials,
            error=subprocess_error(reason, returncode, stderr),
        )
        return RunResult(
            "failed", reason, None, duration, traj.summary(),
            usage=usage or {}, num_turns=num_turns,
            permission_denials=(metrics.get("permission_denials") if metrics else []) or [],
        )

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

    def _build_prompt(
        self, topic: LoadedTopic, now: datetime, last_run: Optional[datetime] = None
    ) -> str:
        cfg = topic.config
        template = apply_time_window(
            self._load_body(cfg.prompt), now=now, last_run=last_run
        )
        rel = f"{topic.slug}/{now.strftime('%Y-%m-%d')}.md"
        return (
            f'You are Scout\'s research agent producing a markdown digest for the '
            f'topic "{cfg.title}".\n\n'
            f"Description: {cfg.description}\n\n"
            "You have the full Claude Code tool set available. The ones most "
            "useful for this task are WebSearch and WebFetch to discover and read "
            "sources, Read and Glob to inspect files, and Write to save the "
            "digest; reach for any other tool (e.g. Bash) when it genuinely "
            "helps.\n\n"
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
