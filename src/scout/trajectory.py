"""Append-only writer for agent run trajectories.

One run = one trajectory = one ``trajectories/<slug>/<run-id>.jsonl`` file in the
``scout.trajectory/1`` schema (see ``docs/trajectory-schema.md`` and
``docs/trajectory.schema.json``). The file is a ``run`` header line, a stream of
``message`` / ``tool_call`` / ``tool_result`` / ``artifact`` records, and a
terminal ``result`` line. Every line is flushed as it is written, so a crashed
run still leaves a valid partial trajectory.

This replaces the old ``RunLog`` (``logs/<slug>/<ts>.jsonl``); ``summary()``
keeps the same shape the digest frontmatter consumes, so the cutover is
mechanical for callers that only needed aggregate metrics.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

SCHEMA_ID = "scout.trajectory/1"

# Tool results larger than this are written to the run's ``*.blobs/`` sidecar and
# referenced by ``blob_ref`` instead of being inlined into the JSONL line (schema
# §3 / decision 5). Keeps lines small and the file fast to parse.
INLINE_LIMIT = 8192

# Crockford base32 (no I, L, O, U) — the ULID alphabet.
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _b32(value: int, length: int) -> str:
    out = []
    for _ in range(length):
        out.append(_CROCKFORD[value & 0x1F])
        value >>= 5
    return "".join(reversed(out))


def new_ulid(now: Optional[datetime] = None) -> str:
    """A ULID: 48-bit millisecond timestamp + 80 random bits, 26 Crockford chars.

    Lexicographically sortable by time (so a directory listing stays
    chronological) while staying unique across concurrent runs.
    """
    moment = now or datetime.now(timezone.utc)
    ms = int(moment.timestamp() * 1000) & ((1 << 48) - 1)
    rand = int.from_bytes(os.urandom(10), "big")
    return _b32(ms, 10) + _b32(rand, 16)


def read_records(path: Path) -> list[dict]:
    """Tolerantly parse a trajectory JSONL file into dict records.

    Skips blank lines, malformed JSON, and any line that isn't a JSON object, so
    a partial/corrupt/hand-edited file never crashes a reader. Shared by the
    dashboard and ``scout doctor``.
    """
    records: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict):
            records.append(rec)
    return records


def provider_of(model: Optional[str], runner: str) -> str:
    """Best-effort GenAI provider name from a model string / runner.

    ``"anthropic/claude-..."`` -> ``"anthropic"``, ``"gemini/..."`` ->
    ``"gemini"``; a bare model under the claude-code runner is Anthropic.
    """
    if model and "/" in model:
        return model.split("/", 1)[0]
    if runner == "claude-code":
        return "anthropic"
    return "unknown"


class TrajectoryWriter:
    def __init__(
        self, slug: str, trajectories_dir: Path, now: Optional[datetime] = None
    ):
        self.slug = slug
        self.trajectories_dir = trajectories_dir
        self.now = now or datetime.now(timezone.utc)
        self.run_id = new_ulid(self.now)
        self.path: Optional[Path] = None
        self._fh = None
        self._seq = 0
        self._last_id: Optional[str] = None
        self._has_result = False
        self._tool_counter: Counter[str] = Counter()
        self._tokens = {"input": 0, "output": 0}
        self._cost = 0.0

    @property
    def has_result(self) -> bool:
        """Whether a terminal ``result`` record has been written for this run."""
        return self._has_result

    def __enter__(self) -> "TrajectoryWriter":
        d = self.trajectories_dir / self.slug
        d.mkdir(parents=True, exist_ok=True)
        self.path = d / f"{self.run_id}.jsonl"
        self._fh = self.path.open("w")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if self._fh is not None:
                self._fh.flush()
                self._fh.close()
        finally:
            self._fh = None
        return None  # don't suppress exceptions

    # --- low level -------------------------------------------------------
    def _emit(
        self,
        type_: str,
        *,
        id_: str,
        parent_id: Optional[str],
        ts: Optional[str] = None,
        **fields: Any,
    ) -> str:
        assert self._fh is not None, "TrajectoryWriter not opened"
        rec = {
            "type": type_,
            "id": id_,
            "parent_id": parent_id,
            "ts": ts or datetime.now(timezone.utc).isoformat(),
            "seq": self._seq,
        }
        rec.update(fields)
        self._fh.write(json.dumps(rec) + "\n")
        self._fh.flush()
        self._seq += 1
        self._last_id = id_
        return id_

    def _parent(self, parent_id: Optional[str]) -> Optional[str]:
        # Default to a linear chain off the last record; callers pass an explicit
        # parent_id to link a tool_call to its message or a result to its call.
        return parent_id if parent_id is not None else self._last_id

    def _offload(self, payload: Any) -> tuple[Any, Optional[str]]:
        """Move an over-sized payload to the ``*.blobs/`` sidecar.

        Returns ``(payload, None)`` when it serializes within ``INLINE_LIMIT``;
        otherwise writes the full JSON to ``<run-id>.blobs/<sha256>.json`` and
        returns a small ``({"truncated": True, "bytes": N}, blob_ref)`` stub.
        """
        text = json.dumps(payload, default=str)
        size = len(text.encode("utf-8"))
        if size <= INLINE_LIMIT or self.path is None:
            return payload, None
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        blobs_dir = self.path.parent / f"{self.run_id}.blobs"
        blobs_dir.mkdir(parents=True, exist_ok=True)
        (blobs_dir / f"{digest}.json").write_text(text, encoding="utf-8")
        return {"truncated": True, "bytes": size}, f"{self.run_id}.blobs/{digest}.json"

    @staticmethod
    def _drop_none(fields: dict) -> dict:
        return {k: v for k, v in fields.items() if v is not None}

    # --- records ---------------------------------------------------------
    def header(self, **fields: Any) -> str:
        """Write the ``run`` header (first line). Returns the run id."""
        body = {"schema": SCHEMA_ID, "run_id": self.run_id, **self._drop_none(fields)}
        return self._emit(
            "run", id_=self.run_id, parent_id=None, ts=self.now.isoformat(), **body
        )

    def message(
        self,
        role: str,
        content: Any,
        *,
        parent_id: Optional[str] = None,
        model: Optional[str] = None,
        stop_reason: Optional[str] = None,
        usage: Optional[dict] = None,
    ) -> str:
        fields = self._drop_none(
            {"model": model, "stop_reason": stop_reason, "usage": usage}
        )
        return self._emit(
            "message",
            id_=new_ulid(),
            parent_id=self._parent(parent_id),
            role=role,
            content=content,
            **fields,
        )

    def tool_call(
        self,
        *,
        call_id: str,
        name: str,
        arguments: dict,
        parent_id: Optional[str] = None,
        kind: Optional[str] = None,
        server: Optional[str] = None,
    ) -> str:
        self._tool_counter[name] += 1
        fields = self._drop_none({"kind": kind, "server": server})
        return self._emit(
            "tool_call",
            id_=new_ulid(),
            parent_id=self._parent(parent_id),
            call_id=call_id,
            name=name,
            arguments=arguments,
            **fields,
        )

    def tool_result(
        self,
        *,
        call_id: str,
        status: str,
        result: dict,
        parent_id: Optional[str] = None,
        error: Optional[dict] = None,
        duration_ms: Optional[int] = None,
        sources: Optional[list] = None,
        blob_ref: Optional[str] = None,
    ) -> str:
        # Divert an over-sized result to the blobs sidecar unless the caller
        # already supplied a blob_ref (i.e. handled offloading itself).
        if blob_ref is None:
            result, blob_ref = self._offload(result)
        fields = self._drop_none(
            {
                "error": error,
                "duration_ms": duration_ms,
                "sources": sources,
                "blob_ref": blob_ref,
            }
        )
        return self._emit(
            "tool_result",
            id_=new_ulid(),
            parent_id=self._parent(parent_id),
            call_id=call_id,
            status=status,
            result=result,
            **fields,
        )

    def artifact(
        self,
        *,
        kind: str,
        path: str,
        media_type: str,
        parent_id: Optional[str] = None,
        size_bytes: Optional[int] = None,
        sha256: Optional[str] = None,
        summary: Optional[str] = None,
    ) -> str:
        fields = self._drop_none(
            {"bytes": size_bytes, "sha256": sha256, "summary": summary}
        )
        return self._emit(
            "artifact",
            id_=new_ulid(),
            parent_id=self._parent(parent_id),
            kind=kind,
            path=path,
            media_type=media_type,
            **fields,
        )

    def result(
        self,
        *,
        status: str,
        duration_seconds: float,
        parent_id: Optional[str] = None,
        reason: Optional[str] = None,
        error: Optional[dict] = None,
        usage: Optional[dict] = None,
        tool_calls: Optional[dict] = None,
        num_turns: Optional[int] = None,
        permission_denials: Optional[list] = None,
        artifacts: Optional[list] = None,
    ) -> str:
        if usage is None:
            usage = self.usage_summary()
        if tool_calls is None:
            tool_calls = dict(self._tool_counter)
        fields = self._drop_none(
            {
                "reason": reason,
                "error": error,
                "num_turns": num_turns,
                "permission_denials": permission_denials,
                "artifacts": artifacts,
            }
        )
        self._has_result = True
        return self._emit(
            "result",
            id_=new_ulid(),
            parent_id=self._parent(parent_id),
            status=status,
            duration_seconds=duration_seconds,
            usage=usage,
            tool_calls=tool_calls,
            **fields,
        )

    # --- aggregation -----------------------------------------------------
    def note_usage(
        self,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_usd: float = 0.0,
    ) -> None:
        """Accumulate token/cost totals for ``summary()`` (frontmatter)."""
        self._tokens["input"] += int(input_tokens or 0)
        self._tokens["output"] += int(output_tokens or 0)
        self._cost += float(cost_usd or 0.0)

    def usage_summary(self) -> dict:
        return {
            "input_tokens": self._tokens["input"],
            "output_tokens": self._tokens["output"],
            "total_tokens": self._tokens["input"] + self._tokens["output"],
            "cost_usd": self._cost,
        }

    def summary(self) -> dict:
        """Frontmatter-compatible aggregate (same shape the old RunLog had)."""
        return {
            "tool_calls": dict(self._tool_counter),
            "tokens": dict(self._tokens),
            "cost_usd": self._cost,
        }
