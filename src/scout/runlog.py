from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class RunLog:
    def __init__(self, slug: str, logs_dir: Path, now: Optional[datetime] = None):
        self.slug = slug
        self.logs_dir = logs_dir
        self.now = now or datetime.now(timezone.utc)
        self._tool_counter: Counter[str] = Counter()
        self._tokens = {"input": 0, "output": 0}
        self._cost = 0.0
        self._fh = None
        self.path: Optional[Path] = None

    def __enter__(self) -> "RunLog":
        d = self.logs_dir / self.slug
        d.mkdir(parents=True, exist_ok=True)
        self.path = d / self.now.strftime("%Y-%m-%d-%H%M%S.jsonl")
        self._fh = self.path.open("w")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if self._fh is not None:
                self._fh.flush()
                self._fh.close()
        finally:
            self._fh = None
        # don't suppress exceptions
        return None

    def event(self, name: str, **fields) -> None:
        assert self._fh is not None, "RunLog not opened"
        rec = {"ts": datetime.now(timezone.utc).isoformat(), "event": name, **fields}
        self._fh.write(json.dumps(rec) + "\n")
        if name == "tool_call":
            self._tool_counter[fields.get("tool", "?")] += 1
        elif name == "llm_turn":
            self._tokens["input"] += fields.get("input_tokens", 0)
            self._tokens["output"] += fields.get("output_tokens", 0)
            self._cost += float(fields.get("cost_usd", 0.0))

    def summary(self) -> dict:
        return {
            "tool_calls": dict(self._tool_counter),
            "tokens": dict(self._tokens),
            "cost_usd": self._cost,
        }
