from __future__ import annotations

import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from scout.config import LoadedTopic
from scout.output import DigestRecord, compose_digest, first_heading
from scout.runner import Limits, Paths, RunResult, apply_time_window
from scout.trajectory import TrajectoryWriter

PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "prompts"


class CodexRunner:
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
        prompt = self._build_prompt(topic, now, paths, last_run)
        paths.output_dir.mkdir(parents=True, exist_ok=True)
        start = time.monotonic()
        try:
            proc = subprocess.run(
                ["codex", "exec", "--quiet", prompt],
                cwd=paths.output_dir,
                capture_output=True, text=True,
                timeout=limits.timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            duration = time.monotonic() - start
            traj.result(status="failed", reason="timeout", duration_seconds=duration)
            return RunResult("failed", "timeout", None, duration, {})
        duration = time.monotonic() - start
        # The codex CLI exposes no structured stream, so the trajectory carries the
        # tail of its output as a single assistant message plus the run envelope.
        traj.message("assistant", proc.stdout[-2000:] or "(no output)",
                     stop_reason=f"exit_{proc.returncode}")

        out_path = paths.output_dir / topic.slug / f"{now.strftime('%Y-%m-%d')}.md"
        if not out_path.exists():
            traj.result(status="failed", reason="no_digest", duration_seconds=duration)
            return RunResult("failed", "no_digest", None, duration, {})

        body = out_path.read_text()
        rec = DigestRecord(
            topic=topic.slug, date=now.strftime("%Y-%m-%d"),
            runner="codex", model="unknown",
            duration_seconds=round(duration, 2),
            tool_calls="unknown", tokens="unknown", cost_usd="unknown",
        )
        composed = compose_digest(rec, body)
        out_path.write_text(composed)
        rel = self._rel(out_path, paths)
        traj.artifact(kind="digest", path=rel, media_type="text/markdown",
                      size_bytes=len(composed.encode("utf-8")), summary=first_heading(body))
        traj.result(status="ok", duration_seconds=duration, artifacts=[rel])
        return RunResult("ok", None, out_path, duration, {})

    @staticmethod
    def _rel(path: Path, paths: Paths) -> str:
        try:
            return str(path.relative_to(paths.output_dir.parent))
        except ValueError:
            return str(path)

    def _build_prompt(
        self,
        topic: LoadedTopic,
        now: datetime,
        paths: Paths,
        last_run: Optional[datetime] = None,
    ) -> str:
        cfg = topic.config
        template_path = PROMPTS_DIR / f"{cfg.prompt.template}.md" if cfg.prompt.template else None
        template = apply_time_window(
            cfg.prompt.inline if cfg.prompt.inline
            else (template_path.read_text() if template_path else ""),
            now=now, last_run=last_run,
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
