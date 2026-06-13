# Scout Agent Trajectory Schema (proposal v1)

Status: **proposal / RFC** · Author: research synthesis · Date: 2026-06-13

> This spec lives in the `scout` repo, alongside the runner code that will write
> trajectories. The trajectory **data files** themselves are written to the
> `scout-data` repo (under `trajectories/`, as described in §3).

This document proposes a standardized, file-based format for storing the full
**trajectory** of a Scout run — the complete record of what an agent did to
produce a digest: the prompts, model turns, reasoning, tool calls, tool
results, sources fetched, the output artifact, and the run metrics.

Today Scout persists *outcomes* (digest frontmatter, `state/`, and a thin
per-run event log under `logs/`) but not a replayable *trajectory*. This
proposal closes that gap with a schema that is (a) a natural superset of what
Scout already writes, (b) interoperable with the emerging industry standards,
and (c) cheap to produce from both the `builtin` and `claude-code` runners.

---

## 1. Why standardize, and what the field does

A "trajectory" (also called a *transcript*, *run trace*, or *interaction
history*) is the ordered sequence of events an agent went through for one task.
Storing them well unlocks: debugging failed runs, auditing which sources a
digest came from, computing cost/quality metrics, building eval sets, replaying
or resuming runs, and fine-tuning / RL down the line.

I surveyed how prominent agent frameworks store trajectories. Two things are
strikingly consistent across all of them:

1. **A two-level model**: a *run/trace envelope* (metadata about the whole run)
   plus an *ordered sequence of typed steps/events* (messages, model calls,
   tool calls, tool results).
2. **Append-only, line-delimited JSON (JSONL) on disk** is the dominant storage
   shape for the raw record, because it is crash-safe, streamable, and
   trivially greppable.

### Survey of prominent frameworks

| Framework | Storage shape | Envelope identifiers | Step/event model | Notable fields |
|---|---|---|---|---|
| **OpenTelemetry GenAI semconv** (the cross-vendor standard) | Spans + events (OTLP) | `gen_ai.conversation.id`, `gen_ai.agent.id`/`name` | span ops `create_agent`, `invoke_agent`, `execute_tool`, `chat` | `gen_ai.operation.name`, `gen_ai.provider.name`, `gen_ai.request.model`, `gen_ai.usage.input_tokens`/`output_tokens`, `gen_ai.tool.name`/`call.id`; input/output captured as structured **`gen_ai.input.messages` / `gen_ai.output.messages`** following a messages JSON schema |
| **OpenAI Agents SDK** | Trace → Spans, exported as dicts | `trace_id` (`trace_<32hex>`), `group_id` (≈ conversation), `workflow_name` | typed `span_data`: `AgentSpanData`, `GenerationSpanData`, `FunctionSpanData`, `ResponseSpanData`, `HandoffSpanData`, `GuardrailSpanData` | span has `trace_id`/`span_id`/`parent_id`/`started_at`/`ended_at`/`error`; generation span stores `input`, `output`, `model`, `usage` |
| **LangGraph** | Append-only **checkpoints** per super-step | `thread_id`, `checkpoint_id` (UUID/step), `parent_checkpoint_id` | serialized graph **state** snapshot (incl. message history) + metadata | metadata holds node name, timestamp, tags; never overwrites prior state (enables time-travel/resume) |
| **Claude Code** (Scout's `claude-code` runner) | **JSONL**, one event per line, under `~/.claude/projects/<proj>/<session>.jsonl` | `sessionId`, `uuid`, `parentUuid` (tree link), `requestId` | records typed by `type` (`user`/`assistant`/`system`/`summary`); `message.content[]` blocks: `text`, `thinking`, `tool_use{id,name,input}`, `tool_result{tool_use_id,content}` | `message.usage` with `input_tokens`, `output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`; `cwd`, `gitBranch`, `version`, `isSidechain` |
| **ATIF** (Agent Trajectory Interchange Format, Harbor) — a purpose-built trajectory spec | Single JSON doc (also serializable as lines) | `schema_version`, `session_id`, `trajectory_id`, `subagent_trajectories` | `steps[]` with `source` (`user`/`agent`/`system`), `message`, `reasoning_content`, `tool_calls[]`, `observation.results[]`, `metrics` | per-step `metrics`: `prompt_tokens`, `completion_tokens`, `cached_tokens`, `cost_usd`; `tool_call{tool_call_id, function_name, arguments}`; `observation.result{source_call_id, content}`; `final_metrics` aggregate |
| **Hermes / SWE-agent-style trajectory dumps** | JSONL, one self-contained object per line | per-task id, `model`, `completed` | `conversations` / messages + tool stats | designed to be loaded by any JSON-lines reader for SFT/RL |

Takeaways that drive this proposal:

- **Use JSONL as the canonical on-disk form.** It matches Scout's existing
  `logs/`, matches Claude Code natively, is crash-safe (a killed run still
  leaves a valid partial trajectory), and streams.
- **Keep an explicit, typed event vocabulary**: `run` header, `message`,
  `tool_call`, `tool_result`, `artifact`, `feedback`, `result`. This is the
  intersection of ATIF steps, OTel spans, and Claude Code records.
- **Link records with `id` / `parent_id`** (Claude Code's `uuid`/`parentUuid`,
  OTel's `parent_id`, LangGraph's `parent_checkpoint_id`) and link tool calls to
  their results with a `call_id` (OTel `gen_ai.tool.call.id`, ATIF
  `source_call_id`, Anthropic `tool_use_id`).
- **Name fields so they map cleanly onto OTel `gen_ai.*`** — so a Scout
  trajectory can be exported to any OTel-compatible observability backend later
  without re-modeling. A mapping table is given in §6.

Sources:
[OTel GenAI agent spans](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-agent-spans/),
[OTel GenAI semconv](https://opentelemetry.io/docs/specs/semconv/gen-ai/),
[OTel GenAI events](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-events/),
[OpenAI Agents SDK — span data](https://openai.github.io/openai-agents-python/ref/tracing/span_data/),
[OpenAI Agents SDK — tracing](https://openai.github.io/openai-agents-python/tracing/),
[LangGraph persistence](https://langchain-ai.github.io/langgraph/concepts/persistence/),
[ATIF trajectory format (Harbor)](https://www.harborframework.com/docs/agents/trajectory-format),
[Claude Code JSONL format](https://claude-dev.tools/docs/jsonl-format).

---

## 2. What Scout stores today, and the gaps

Per run, Scout currently writes:

- `output/<slug>/<date>.md` — the digest, with YAML frontmatter
  (`topic, date, runner, model, duration_seconds, tool_calls, tokens, cost_usd`)
  and human `<!-- scout-feedback -->` blocks appended (tracked in git).
- `logs/<slug>/<date-time>.jsonl` — thin per-run event log with `event` of
  `run_start`, `llm_turn`, `tool_call`, `subprocess_output`, `permission_denials`,
  `run_end` (**git-ignored**).
- `state/<slug>.json` — scheduler state: `last_run`, `last_status`, `last_error`,
  `last_duration_seconds`, `last_success_run` (**git-ignored**).

Concretely, an existing `claude-code` log line and the `run_end` summary:

```jsonl
{"ts": "2026-06-13T03:00:02.153222+00:00", "event": "run_start", "slug": "frontier-lab-updates-cc", "runner": "claude-code", "model": "claude-opus-4-8"}
{"ts": "2026-06-13T03:05:00.016695+00:00", "event": "llm_turn", "input_tokens": 645895, "output_tokens": 26784, "cost_usd": 1.49, "num_turns": 35}
{"ts": "2026-06-13T03:05:00.017698+00:00", "event": "run_end", "status": "ok", "duration_seconds": 297.86, "tool_calls": {"Glob": 1, "Read": 6, "WebFetch": 20, "WebSearch": 4, "Write": 3}, "tokens": {"input": 645895, "output": 26784}, "cost_usd": 1.49}
```

**Gaps versus a real trajectory** (these are exactly what the proposed schema adds):

1. **No message content** — prompts, assistant text, and reasoning are kept in
   memory and discarded. You cannot see *what the agent thought or said*.
2. **No tool arguments/results for `claude-code`** — only aggregate counts. The
   `builtin` runner does log per-call `args`/`result_bytes`, but not the
   returned content. You cannot see *which URLs were fetched or what came back*.
3. **The `claude-code` runner already throws away a full native trajectory.**
   It shells out to `claude -p --output-format stream-json` and keeps only the
   last ~1 KB of stdout (`subprocess_output.stdout_tail`). That tail already
   contains gold we discard: per-model usage (`modelUsage`), cache token
   breakdown (`cache_creation` / `cache_read_input_tokens`), `permission_denials`,
   `terminal_reason`, and a session `uuid`. The full stream is a ready-made,
   line-by-line trajectory.
4. **No source ledger** — no first-class list of sources retrieved (URL, title,
   status, bytes), even though source provenance is the whole point of a news agent.
5. **No record linkage** — events aren't linked by id/parent, so you can't
   reconstruct the call→result→turn tree.
6. **No cache-token or per-model breakdown** in the persisted summary (cache
   reads are folded into `input_tokens`).
7. **No structured error** on failure — only a string in `state/`.

---

## 3. Storage layout

One run = one trajectory = one JSONL file.

```
scout-data/
  trajectories/
    <topic-slug>/
      <run-id>.jsonl              # the trajectory (append-only, one record per line)
      <run-id>.blobs/             # optional sidecar for large tool outputs / fetched pages
        <sha256>.txt              # referenced by `blob_ref` from a tool_result
  output/<slug>/<date>.md         # unchanged — the digest artifact
  state/<slug>.json               # unchanged — scheduler state
  topics/<slug>.yaml              # unchanged — topic config
```

- **`run-id`** is a **ULID** (Crockford base32, 26 chars, e.g.
  `01JXFEYK0A8Q9R2M3N4P5T6V7W`). ULIDs are lexicographically time-sortable, so a
  directory listing still orders runs chronologically, while guaranteeing
  uniqueness for concurrent runs. The run's wall-clock start is recorded in the
  `run` header's `ts` / `run_window`, not in the filename.
- **This supersedes `logs/`.** The current `logs/` schema is a strict subset of
  the trajectory schema (see §5 migration), so the change is additive.
- **Large content goes to the `*.blobs/` sidecar**, content-addressed by sha256,
  and referenced from the record via `blob_ref`. This keeps lines small while
  preserving full fetched pages for provenance. Small results (≤ a configurable
  threshold, e.g. 8 KB) are inlined.
- **Retention / git policy**: `trajectories/` is **committed to git** (full
  trajectories tracked, unlike git-ignored `logs/`), so every digest carries its
  complete, reviewable provenance in the repo. Tradeoff accepted: the repo grows
  per run and may hold fetched article text and prompt content — keep secrets out
  of prompts, and prune old runs if size becomes a problem. See §7.

---

## 4. Record schema

Every line is one JSON object (a "record"). Records share a small **common
envelope**; the `type` field discriminates the body. A trajectory file is:

```
run            ← exactly one, first line (the header)
( message | tool_call | tool_result | artifact | feedback )*   ← the body, in order
result         ← exactly one, last line (terminal summary)
```

A crashed run may be missing its trailing `result`; consumers MUST treat such a
file as a valid partial trajectory.

### 4.1 Common envelope (every record)

| Field | Type | Req | Meaning |
|---|---|---|---|
| `type` | string enum | yes | `run`/`message`/`tool_call`/`tool_result`/`artifact`/`feedback`/`result` |
| `id` | string | yes | Unique id for this record (UUID or ULID). |
| `parent_id` | string\|null | yes | Logical parent record `id` (tree linkage). `null` for the `run` header. |
| `ts` | string (RFC 3339, UTC) | yes | When the record was emitted. |
| `seq` | integer | yes | Monotonic 0-based index within the run; the tiebreaker when `ts` collide. |

> Note: today's `claude-code` log derives tool calls from a post-hoc summary, so
> their timestamps are identical; `seq` makes ordering deterministic regardless.

### 4.2 `run` — header (first line)

Snapshot of everything known at start. Maps to OTel `invoke_agent` + the topic config.

| Field | Type | Maps to | Meaning |
|---|---|---|---|
| `schema` | string | — | Schema id+version, `"scout.trajectory/1"`. |
| `run_id` | string | `gen_ai.conversation.id` | Equals the file's `<run-id>`. |
| `topic` | string | `gen_ai.agent.name` | Topic slug. |
| `title` | string | — | Human topic title. |
| `runner` | string | framework name | `builtin`/`claude-code`/`codex`. |
| `runner_version` | string | — | e.g. `claude-code 2.1.170`. |
| `scout_version` | string | — | Scout version that produced the run. |
| `provider` | string | `gen_ai.provider.name` | `anthropic`/`google`/… |
| `model` | string | `gen_ai.request.model` | Requested model. |
| `effort` | string\|null | — | Reasoning effort (e.g. `xhigh`). |
| `trigger` | string enum | — | `schedule`/`manual`/`backfill`. |
| `run_window` | object\|null | — | `{since, until}` — the `last_success_run`→`now` window Scout injects. |
| `config` | object | — | Snapshot of the topic config used: `sources[]`, `limits`, `tools`, `prompt` ref/hash. |
| `host` | object | OTel resource | `{hostname, cwd, git_branch}`. |
| `parent_run_id` | string\|null | — | Parent trajectory's `run_id` for sub-agent/nested runs (else `null`). |

### 4.3 `message` — a conversational turn

Maps to OTel `gen_ai.input.messages`/`output.messages`, Claude Code message
records, and ATIF `step.message`/`reasoning_content`.

| Field | Type | Req | Meaning |
|---|---|---|---|
| `role` | enum | yes | `system`/`user`/`assistant`/`tool`. |
| `content` | array of **content parts** \| string | yes | The message body. |
| `model` | string\|null | no | Model that produced an `assistant` message. |
| `stop_reason` | string\|null | no | `end_turn`/`tool_use`/`max_tokens`/… |
| `usage` | object\|null | no | Token usage for this turn (see §4.7). |

**Content parts** (each `{ "type": …, … }`), aligned with Anthropic blocks / OTel / ATIF:

- `{"type":"text","text": "..."}`
- `{"type":"reasoning","text": "..."}` — thinking / `reasoning_content`.
- `{"type":"tool_use","call_id":"toolu_…","name":"WebFetch","input":{…}}` — a tool request emitted inline by the model.
- `{"type":"tool_result","call_id":"toolu_…","status":"ok","content":…,"blob_ref":null}` — inline tool result.
- `{"type":"media","media_type":"image/png","blob_ref":"…","url":null}` — non-text content by reference.

> Tool activity MAY be represented either inline as `tool_use`/`tool_result`
> content parts (Claude-Code style) **or** as standalone `tool_call`/`tool_result`
> records (§4.4–4.5). Standalone records are preferred when arguments/results are
> large or need their own metrics; the two forms are linked by the same `call_id`.

### 4.4 `tool_call` — a discrete tool invocation

Maps to OTel `execute_tool` span and ATIF `tool_call`.

| Field | Type | Req | Maps to | Meaning |
|---|---|---|---|---|
| `call_id` | string | yes | `gen_ai.tool.call.id` | Links to the matching `tool_result`. |
| `name` | string | yes | `gen_ai.tool.name` | Tool name (e.g. `WebFetch`, `web_search`). |
| `kind` | string\|null | no | `gen_ai.tool.type` | Category: `search`/`fetch`/`read`/`write`/`mcp`/… |
| `arguments` | object | yes | — | Full call arguments (e.g. `{"url": "..."}`). **Gap #2 closer.** |
| `server` | string\|null | no | `server.address` | MCP/remote server, if any. |

### 4.5 `tool_result` — a tool's return

| Field | Type | Req | Meaning |
|---|---|---|---|
| `call_id` | string | yes | The `tool_call.call_id` this answers. |
| `status` | enum | yes | `ok`/`error`. |
| `error` | object\|null | no | `{type, message}` when `status="error"`. |
| `duration_ms` | integer\|null | no | Tool wall-clock. |
| `result` | object | yes | Normalized result; small content inlined. |
| `blob_ref` | string\|null | no | Path under `<run-id>.blobs/` holding the full content when large. |
| `sources` | array\|null | no | For fetch/search tools: `[{url, title, status, bytes, fetched_at}]`. **Gap #4 closer.** |

`result` is tool-shaped but SHOULD include `{content?, bytes?, truncated?}` so a
generic viewer can render it.

### 4.6 `artifact` — an output produced

| Field | Type | Req | Meaning |
|---|---|---|---|
| `kind` | enum | yes | `digest`/`file`/`note`. |
| `path` | string | yes | Path **relative to the data root** (e.g. `output/<slug>/<date>.md`). |
| `media_type` | string | yes | e.g. `text/markdown`. |
| `bytes` | integer | no | Size. |
| `sha256` | string | no | Content hash (ties the trajectory to the exact digest). |
| `summary` | string\|null | no | Title / first heading. |

### 4.7 `result` — terminal summary (last line)

Maps to OTel `invoke_agent` span end + today's `run_end`.

| Field | Type | Req | Meaning |
|---|---|---|---|
| `status` | enum | yes | `ok`/`failed`/`timeout`/`no_output`. |
| `reason` | string\|null | no | Short failure reason (today's `last_error`). |
| `error` | object\|null | no | `{type, message, trace_ref}` — **Gap #7 closer.** |
| `duration_seconds` | number | yes | Wall-clock. |
| `usage` | object | yes | Aggregate token usage (below). |
| `tool_calls` | object | yes | `{toolName: count}` (back-compatible with today). |
| `num_turns` | integer\|null | no | Model turns. |
| `permission_denials` | array | no | Denied tool/permission events. |
| `artifacts` | array of string | no | Paths of artifacts produced. |

**`usage` object** (shared by `message.usage` and `result.usage`) — superset of
OTel `gen_ai.usage.*` and the Claude Code `modelUsage` we currently discard:

```json
{
  "input_tokens": 645895,
  "output_tokens": 26784,
  "cache_read_input_tokens": 383412,        // Gap #6 closer
  "cache_creation_input_tokens": 49080,
  "total_tokens": 672679,
  "cost_usd": 1.4922,
  "by_model": {                              // per-model split (claude-code modelUsage)
    "claude-opus-4-8":   {"input_tokens": 2025,   "output_tokens": 21214, "cache_read_input_tokens": 383412, "cost_usd": 1.2230},
    "claude-haiku-4-5":  {"input_tokens": 211378, "output_tokens": 5570,  "cache_read_input_tokens": 0,      "cost_usd": 0.2692}
  }
}
```

A machine-checkable JSON Schema for all record types is in
[`trajectory.schema.json`](./trajectory.schema.json); a full worked example is in
[`examples/frontier-lab-updates-cc.trajectory.jsonl`](./examples/frontier-lab-updates-cc.trajectory.jsonl).

---

## 5. Migration from today's `logs/`

The current log format is a strict subset; mapping is mechanical:

| Today (`logs/…/*.jsonl`) | Trajectory record |
|---|---|
| `event:"run_start"` (`slug, runner, model`) | `type:"run"` header (+ config/window from topic + state). |
| `event:"llm_turn"` (`turn, input_tokens, output_tokens, cost_usd, duration_ms`) | `type:"message"` (role `assistant`) with `usage`, or fold into `result.usage`. |
| `event:"tool_call"` (`tool, args, ok, error, duration_ms, result_bytes`) | `type:"tool_call"` + `type:"tool_result"` (builtin already has args + result_bytes). |
| `event:"subprocess_output"` (`stdout_tail` = Claude Code summary) | parse `modelUsage`/`cache_*`/`permission_denials`/`uuid` into `result.usage` + `result.permission_denials`. |
| `event:"run_end"` | `type:"result"`. |

Recommended rollout:

1. **Land the schema** (this doc + JSON Schema + example) — no code yet.
2. **`builtin` runner**: it already emits per-turn and per-tool detail; upgrade
   its `RunLog` to the trajectory record shape and add message/reasoning content
   (cheapest, highest-fidelity win).
3. **`claude-code` runner**: stop discarding the stream. Tee
   `claude -p --output-format stream-json` to `trajectories/<slug>/<run-id>.jsonl`
   and translate each Claude Code record (`uuid`/`parentUuid`/`message.content[]`)
   into Scout records. This alone closes gaps #1–#3, #6 with almost no new logic.
4. Write a one-off converter for historical `logs/` → `trajectories/` for the
   subset that's recoverable.
5. Point `scout serve` (the PWA) at trajectories to render a per-digest "how this
   was made" view.

---

## 6. Interop mapping (Scout ↔ OTel ↔ ATIF ↔ Claude Code)

So a Scout trajectory can be exported to any of these without re-modeling:

| Scout | OTel GenAI semconv | ATIF | Claude Code JSONL |
|---|---|---|---|
| `run` record | `invoke_agent` span | `Trajectory` + `agent` | session header fields |
| `run_id` | `gen_ai.conversation.id` | `session_id` | `sessionId` |
| `id` / `parent_id` | span `span_id` / `parent_id` | (implicit step order) | `uuid` / `parentUuid` |
| `model` | `gen_ai.request.model` | `agent.model_name` | `message.model` |
| `provider` | `gen_ai.provider.name` | — | (implicit) |
| `message` | `gen_ai.input/output.messages` | `step.message` | `type:user/assistant` |
| `content.reasoning` | reasoning content | `reasoning_content` | `thinking` block |
| `tool_call` | `execute_tool` span | `tool_call` | `tool_use` block |
| `tool_call.call_id` | `gen_ai.tool.call.id` | `tool_call_id` | `tool_use.id` |
| `tool_call.name` | `gen_ai.tool.name` | `function_name` | `tool_use.name` |
| `tool_result` | tool span result | `observation.result` | `tool_result` block |
| `usage.input_tokens` | `gen_ai.usage.input_tokens` | `prompt_tokens` | `usage.input_tokens` |
| `usage.output_tokens` | `gen_ai.usage.output_tokens` | `completion_tokens` | `usage.output_tokens` |
| `usage.cache_read_input_tokens` | (provider attr) | `cached_tokens` | `usage.cache_read_input_tokens` |
| `result.status` | span status | `final_metrics` | `terminal_reason` |

---

## 7. Resolved decisions

Settled 2026-06-13:

1. **Git tracking & retention — commit everything.** `trajectories/` is tracked
   in git so every digest keeps its full, reviewable provenance in the repo.
   Tradeoff accepted: the repo grows per run and may hold fetched content/prompts
   — keep secrets out of prompts and prune old runs if size becomes a problem.
2. **`run-id` scheme — ULID** (Crockford base32, 26 chars). Time-sortable so a
   directory listing stays chronological; unique under concurrent runs.
3. **Reasoning capture — inline full.** Extended-thinking / reasoning is stored
   directly as `reasoning` content parts in the `message` record (not blobbed,
   not dropped).
4. **`logs/` cutover — hard-cut.** Replace `logs/` with `trajectories/` in one
   step; the new format is a superset and `logs/` is git-ignored, so nothing
   committed is lost. No dual-write.

Still defaulted (revisit during implementation if needed):

5. **Inline-vs-blob threshold** for large tool outputs: **8 KB** (results above
   this go to the `*.blobs/` sidecar; blobs are committed too, per decision 1).
6. **Digest back-reference — adopted.** Digest frontmatter gains
   `trajectory: trajectories/<slug>/<run-id>.jsonl` so each digest links to its
   trajectory.
