from __future__ import annotations

import hashlib
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from scout.agent.llm import LLMClient
from scout.agent.loop import run_loop
from scout.agent.tools import registry
from scout.agent.tools._types import RunContext
from scout.config import LoadedTopic
from scout.output import DigestRecord, compose_digest, first_heading
from scout.runner import Limits, Paths, RunResult, apply_time_window
from scout.trajectory import TrajectoryWriter

PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "prompts"


def default_llm_client() -> LLMClient:
    return LLMClient()


class BuiltinRunner:
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
        allowed = self._allowed_tools(cfg)
        sys_p, user_p = self._build_prompts(topic, now, last_run)
        client = default_llm_client()
        ctx = RunContext(
            slug=topic.slug,
            output_dir=paths.output_dir,
            now=now,
            traj=traj,
        )
        start = time.monotonic()
        result = run_loop(
            client=client,
            model=cfg.model,
            system_prompt=sys_p,
            user_prompt=user_p,
            ctx=ctx,
            allowed_tools=allowed,
            timeout_seconds=limits.timeout_seconds,
        )
        duration = time.monotonic() - start
        summary = traj.summary()
        if result.status != "ok" or result.output_path is None:
            traj.result(
                status=result.status, reason=result.reason,
                duration_seconds=duration, num_turns=result.turns,
            )
            return RunResult(
                status=result.status,
                reason=result.reason,
                output_path=None,
                duration_seconds=duration,
                summary=summary,
                usage=traj.usage_summary(),
                num_turns=result.turns,
            )
        out_path = Path(result.output_path)
        body = out_path.read_text()
        rec = DigestRecord(
            topic=topic.slug,
            date=now.strftime("%Y-%m-%d"),
            runner="builtin",
            model=cfg.model,
            duration_seconds=round(duration, 2),
            tool_calls=summary["tool_calls"],
            tokens=summary["tokens"],
            cost_usd=round(summary["cost_usd"], 4),
        )
        composed = compose_digest(rec, body)
        out_path.write_text(composed)
        rel = paths.rel(out_path)
        traj.artifact(
            kind="digest",
            path=rel,
            media_type="text/markdown",
            size_bytes=len(composed.encode("utf-8")),
            sha256=hashlib.sha256(composed.encode("utf-8")).hexdigest(),
            summary=first_heading(body),
        )
        traj.result(
            status="ok", duration_seconds=duration, num_turns=result.turns,
            artifacts=[rel],
        )
        return RunResult(
            status="ok",
            reason=None,
            output_path=out_path,
            duration_seconds=duration,
            summary=summary,
            usage=traj.usage_summary(),
            num_turns=result.turns,
        )

    def _allowed_tools(self, cfg) -> list[str]:
        reg = registry()
        if cfg.tools is not None:
            return cfg.tools
        return [name for name, t in reg.items() if t.default_enabled]

    def _build_prompts(
        self, topic: LoadedTopic, now: datetime, last_run: Optional[datetime] = None
    ) -> tuple[str, str]:
        cfg = topic.config
        sources_block = self._render_sources(cfg.sources)
        system = (
            f'You are Scout\'s agent for the topic "{cfg.title}".\n\n'
            f"Description: {cfg.description}\n\n"
            "You produce a single markdown digest of what's new for this topic "
            "since the last run. Use the tools to gather sources, then call "
            "write_digest exactly once to finish.\n\n"
            "Sources (seeds — starting points, not an exhaustive list; you should "
            "also use web_search, fetch_url, and browser_use to discover additional "
            "relevant sources):\n"
            f"{sources_block}\n"
            "Avoid repeating items already covered in prior digests; call "
            "read_history if you need to check.\n"
        )
        template_body = self._load_prompt_body(cfg.prompt)
        user = apply_time_window(
            self._substitute(template_body, topic), now=now, last_run=last_run
        )
        return system, user

    def _render_sources(self, sources) -> str:
        if not sources:
            return "(none configured)"
        lines = []
        for s in sources:
            if s.type == "rss":
                lines.append(f"- rss: {s.url}")
            elif s.type == "web":
                lines.append(f"- web: {s.url}")
            else:
                lines.append(f"- search: {s.query}")
        return "\n".join(lines)

    def _load_prompt_body(self, prompt) -> str:
        if prompt.inline:
            return prompt.inline
        return (PROMPTS_DIR / f"{prompt.template}.md").read_text()

    def _substitute(self, body: str, topic: LoadedTopic) -> str:
        # Builtin-template-only tokens. {{cadence_window}} (plus {{now}}/{{last_run}})
        # is handled by the shared apply_time_window in _build_prompts, so it renders
        # the real run window for every runner instead of the old vague literal.
        cfg = topic.config
        return (
            body.replace("{{title}}", cfg.title)
            .replace("{{description}}", cfg.description)
            .replace("{{sources}}", self._render_sources(cfg.sources))
            .replace("{{history_paths}}", "(use read_history tool)")
        )
