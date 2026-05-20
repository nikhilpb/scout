from __future__ import annotations

import subprocess
import time
from datetime import datetime
from pathlib import Path

from scout.config import LoadedTopic
from scout.output import DigestRecord, compose_digest
from scout.runlog import RunLog
from scout.runner import Limits, Paths, RunResult

PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "prompts"


class CodexRunner:
    def execute(
        self,
        topic: LoadedTopic,
        paths: Paths,
        limits: Limits,
        *,
        run_log: RunLog,
        now: datetime,
    ) -> RunResult:
        prompt = self._build_prompt(topic, now, paths)
        paths.output_dir.mkdir(parents=True, exist_ok=True)
        run_log.event("run_start", slug=topic.slug, runner="codex", model="unknown")
        start = time.monotonic()
        try:
            proc = subprocess.run(
                ["codex", "exec", "--quiet", prompt],
                cwd=paths.output_dir,
                capture_output=True, text=True,
                timeout=limits.timeout_seconds,
            )
            run_log.event(
                "subprocess_output",
                stdout=proc.stdout[-2000:], stderr=proc.stderr[-2000:],
                returncode=proc.returncode,
            )
        except subprocess.TimeoutExpired:
            duration = time.monotonic() - start
            run_log.event(
                "run_end", status="failed", reason="timeout",
                duration_seconds=duration, tool_calls="unknown",
                tokens="unknown", cost_usd="unknown",
            )
            return RunResult("failed", "timeout", None, duration, {})
        duration = time.monotonic() - start

        out_path = paths.output_dir / topic.slug / f"{now.strftime('%Y-%m-%d')}.md"
        if not out_path.exists():
            run_log.event(
                "run_end", status="failed", reason="no_digest",
                duration_seconds=duration, tool_calls="unknown",
                tokens="unknown", cost_usd="unknown",
            )
            return RunResult("failed", "no_digest", None, duration, {})

        body = out_path.read_text()
        rec = DigestRecord(
            topic=topic.slug, date=now.strftime("%Y-%m-%d"),
            runner="codex", model="unknown",
            duration_seconds=round(duration, 2),
            tool_calls="unknown", tokens="unknown", cost_usd="unknown",
        )
        out_path.write_text(compose_digest(rec, body))
        run_log.event(
            "run_end", status="ok", duration_seconds=duration,
            tool_calls="unknown", tokens="unknown", cost_usd="unknown",
        )
        return RunResult("ok", None, out_path, duration, {})

    def _build_prompt(self, topic: LoadedTopic, now, paths: Paths) -> str:
        cfg = topic.config
        template_path = PROMPTS_DIR / f"{cfg.prompt.template}.md" if cfg.prompt.template else None
        template = (
            cfg.prompt.inline if cfg.prompt.inline
            else (template_path.read_text() if template_path else "")
        )
        rel = f"{topic.slug}/{now.strftime('%Y-%m-%d')}.md"
        return (
            f"Topic: {cfg.title}\nDescription: {cfg.description}\n\n"
            "Sources (seeds, not exhaustive):\n"
            + "\n".join(self._source_lines(cfg.sources))
            + f"\n\nFormat:\n{template}\n\n"
            f"Write the final digest body (no frontmatter) to `{rel}` then stop."
        )

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
