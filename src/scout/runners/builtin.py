from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from scout.agent.llm import LLMClient
from scout.agent.loop import run_loop
from scout.agent.tools import registry
from scout.agent.tools._types import RunContext
from scout.config import LoadedTopic
from scout.output import DigestRecord, compose_digest
from scout.runlog import RunLog
from scout.runner import Limits, Paths, RunResult

PROMPTS_DIR = Path("prompts")


def default_llm_client() -> LLMClient:
    return LLMClient()


class BuiltinRunner:
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
        allowed = self._allowed_tools(cfg)
        sys_p, user_p = self._build_prompts(topic, now)
        client = default_llm_client()
        ctx = RunContext(
            slug=topic.slug,
            output_dir=paths.output_dir,
            logs_dir=paths.logs_dir,
            now=now,
            runlog=run_log,
        )
        run_log.event("run_start", slug=topic.slug, runner="builtin", model=cfg.model)
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
        run_log.event(
            "run_end",
            status=result.status,
            reason=result.reason,
            duration_seconds=duration,
            **run_log.summary(),
        )
        if result.status != "ok" or result.output_path is None:
            return RunResult(
                status=result.status,
                reason=result.reason,
                output_path=None,
                duration_seconds=duration,
                summary=run_log.summary(),
            )
        out_path = Path(result.output_path)
        body = out_path.read_text()
        summary = run_log.summary()
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
        out_path.write_text(compose_digest(rec, body))
        return RunResult(
            status="ok",
            reason=None,
            output_path=out_path,
            duration_seconds=duration,
            summary=summary,
        )

    def _allowed_tools(self, cfg) -> list[str]:
        reg = registry()
        if cfg.tools is not None:
            return cfg.tools
        return [name for name, t in reg.items() if t.default_enabled]

    def _build_prompts(self, topic: LoadedTopic, now: datetime) -> tuple[str, str]:
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
        user = self._substitute(template_body, topic)
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
        cfg = topic.config
        return (
            body.replace("{{title}}", cfg.title)
            .replace("{{description}}", cfg.description)
            .replace("{{sources}}", self._render_sources(cfg.sources))
            .replace("{{cadence_window}}", "since the last run")
            .replace("{{history_paths}}", "(use read_history tool)")
        )
