# Scout — Design Spec

A personal news agent that produces scheduled, per-topic markdown digests by gathering content from RSS feeds, the open web, and web search, then summarizing through an LLM agent loop. Output is committed to a git repo for cross-device access. Designed to run on a long-lived Linux host.

## 1. Goals and scope

**In scope for v1:**

- Per-topic markdown digests on configurable cadences (cron expressions).
- Sources: RSS/Atom feeds, arbitrary web pages, and web search. Sources declared on a topic are **seeds**, not an exhaustive list — the agent is free to discover and use additional sources at its discretion via the available tools.
- LLM acts as a full agent with tool use, driven by a Scout-owned, provider-agnostic loop (LiteLLM-backed) or one of two external CLI runners (`claude-code`, `codex`).
- Output written to `output/<slug>/<date>.md`, committed and pushed to the project's GitHub remote.
- Inline feedback capture for future use (no auto-incorporation in v1).
- Triggered by a single cron entry hitting `scout tick` every 15 minutes.

**Explicit non-goals for v1:**

- Social-platform ingestion (X, Reddit, HN, YouTube).
- Live notifications (no email, push, Slack).
- Auto-incorporation of user feedback into prompts.
- Digest-quality evals (LLM-as-judge, human grading).
- Web UI of any kind.
- Token / cost hard caps (cost is logged, not enforced — wall-clock is the only hard limit).
- Quality tests of the external CLI runners.

## 2. Architecture

### 2.1 Process model

A single cron entry on the host:

```
*/15 * * * * cd /path/to/scout && uv run scout tick
```

`scout tick` is the orchestrator. Per invocation it:

1. Loads every `topics/*.yaml`.
2. For each topic, reads `state/<slug>.json` and computes `next_due` from `last_run + cadence` (via `croniter`).
3. Selects topics where `now >= next_due` (or `last_run` is missing → due immediately).
4. Spawns each due topic as an isolated subprocess: `uv run scout run --topic <slug>`. Concurrent, capped at a global default (3 simultaneous workers).
5. Exits when all workers complete.

`scout run --topic <slug>` is the per-topic worker:

1. Acquires file lock `state/<slug>.lock` via `fcntl.flock`. If already held → exit cleanly with status `skipped (locked)`.
2. Dispatches to the configured runner.
3. On success: updates state, commits and pushes the output file.
4. On failure: updates state with error info; no commit.
5. Releases the lock.

`scout run` can also be invoked manually (e.g., for testing a topic outside its cadence — pair with `--force` to bypass the due-check).

### 2.2 Repo layout

Scout lives in two repositories: a **code repo** (this one) holds the Python project; a **data repo** (separate, located at `$SCOUT_DATA_DIR`) holds the user-edited configs, the live `scout.toml`, the committed digests, and the per-machine state and logs.

Code repo:

```
scout/
├── pyproject.toml              # uv project
├── uv.lock
├── scout.toml.example          # template; copied into the data repo on setup
├── spec.md
├── AGENTS.md
├── src/scout/
│   ├── __init__.py
│   ├── cli.py                  # scout tick | run | topics | validate | doctor | feedback
│   ├── paths.py                # DataPaths value object + resolve()
│   ├── scheduler.py            # is-due logic, croniter integration
│   ├── runner.py               # Runner protocol, factory, dispatch
│   ├── runners/
│   │   ├── builtin.py          # in-process agent loop entrypoint
│   │   ├── claude_code.py      # subprocess wrapper around `claude -p`
│   │   └── codex.py            # subprocess wrapper around codex CLI
│   ├── agent/                  # used by the builtin runner
│   │   ├── loop.py             # the ReAct loop
│   │   ├── llm.py              # LiteLLM client
│   │   └── tools/
│   │       ├── web_search.py
│   │       ├── fetch_url.py
│   │       ├── browser.py
│   │       ├── read_history.py
│   │       └── write_digest.py
│   ├── config.py               # topic + global config schemas (pydantic)
│   ├── state.py                # last-run state read/write
│   ├── git_publish.py          # commit + push inside the data repo
│   └── feedback.py             # inline-feedback parser & CLI helpers
├── prompts/                    # shipped templates (versioned with the code)
│   ├── headlines.md
│   ├── briefing.md
│   └── sectioned.md
├── docs/
│   └── setup.md                # bootstrapping the data repo + cron
└── tests/
```

Data repo (located at `$SCOUT_DATA_DIR`, conventionally `~/git/scout-data`):

```
scout-data/
├── scout.toml                  # live config (global defaults, git identity, etc.)
├── topics/                     # user-edited, one YAML per topic
│   └── ai-research.yaml
├── output/                     # committed; <slug>/<YYYY-MM-DD>.md
├── state/                      # gitignored (per-machine)
├── logs/                       # gitignored
└── .gitignore                  # state/, logs/
```

Scout resolves the data repo at runtime in this order: `--data-dir <path>` flag, then `$SCOUT_DATA_DIR`, then error. There is no fallback to the current working directory.

### 2.3 Boundaries

- `scheduler` knows nothing about agents or LLMs; pure config + state + time math.
- `runner` decides which implementation handles a given topic; doesn't run agent code itself.
- `runners/builtin` owns the in-process loop; its internals live in `agent/`.
- `runners/claude_code` and `runners/codex` are thin subprocess wrappers; no agent code.
- `agent/loop` talks only to `agent/llm` and the tool registry; provider-agnostic.
- Each `agent/tools/*.py` implements exactly one tool with a tested interface.
- `git_publish` is the only module that touches git.
- `feedback` reads digest markdown only; never modifies it.

## 3. Topic config schema

One YAML file per topic in `topics/`. Filename stem is the slug (lowercase, kebab-case, ASCII). Loaded and validated via pydantic.

```yaml
# topics/ai-research.yaml — filename determines the slug

title: "AI research"                # required; human label

description: >                      # required; semantic context fed to the agent
  Frontier AI research and engineering — new model releases, capability
  evals, training/inference techniques, alignment work. Not product news.

cadence: "0 7 * * *"                # required; cron expression. Tick fires
                                    # if now >= next_due, where next_due is
                                    # croniter(cadence).get_next(last_run).

sources:                            # optional; SEEDS, not an exhaustive list.
  - type: rss                       # The agent uses these as starting points
    url: https://example.com/feed.xml  # and is free to discover additional
  - type: web                       # sources via web_search / fetch_url /
    url: https://example.com/blog   # browser_use (following links from seeds,
  - type: search                    # related search terms, etc.).
    query: "frontier AI research this week"

runner: builtin                     # builtin | claude-code | codex; default builtin

model: anthropic/claude-sonnet-4-6  # LiteLLM model string; required for builtin,
                                    # ignored (with warning) for CLI runners.

prompt:                             # exactly one of these:
  template: briefing                #   references prompts/briefing.md
  # OR
  inline: |
    Custom prompt body, with substitutions: {{description}}, {{sources}},
    {{cadence_window}}, {{history_paths}}.

limits:                             # optional; falls back to scout.toml
  timeout_seconds: 300

tools:                              # optional allowlist; builtin runner only.
  - web_search                      #   Default = full supported set MINUS
  - fetch_url                       #   browser_use (which is opt-in due to
  - read_history                    #   its heaviness). Ignored with a warning
  - write_digest                    #   for claude-code / codex runners.
```

### 3.1 Validation rules

- Filename must match `^[a-z0-9][a-z0-9-]*\.yaml$`. No dots in the stem.
- `title`, `description`, `cadence` are required.
- `cadence` parses as a valid 5-field cron expression.
- `runner` ∈ `{builtin, claude-code, codex}`; default `builtin`.
- `model` is required when `runner: builtin`. Warned-and-ignored for CLI runners.
- `prompt`: exactly one of `template` or `inline` must be present.
- `prompt.template` (when present) must exist as a file in `prompts/`.
- `tools` is honored only when `runner: builtin`. For CLI runners (`claude-code`, `codex`), `tools` is ignored with a load-time warning — those runners use their own CLI's tool set, which Scout doesn't control. When honored, `tools` must be a subset of the builtin runner's supported set (see §4.3).
- `limits.timeout_seconds` (when present) must be a positive integer.

### 3.2 Global defaults — `scout.toml`

Lives in the data repo at `$SCOUT_DATA_DIR/scout.toml`. The code repo ships a `scout.toml.example` template; setup copies it into the data repo.

```toml
[defaults]
runner = "builtin"
model  = "anthropic/claude-sonnet-4-6"
timeout_seconds = 300

[scheduler]
max_concurrent_workers = 3

[git]
author_name  = "Scout"
author_email = "scout@localhost"
remote = "origin"
branch = "main"

[llm]
# LiteLLM credentials read from env vars by convention;
# this section is reserved for future overrides.
```

Topics override these per-key.

### 3.3 Shipped prompt templates

- `prompts/headlines.md` — list of items, each = headline + 1-2 sentence summary + source link.
- `prompts/briefing.md` — mini-article synthesizing the period, with inline citations.
- `prompts/sectioned.md` — top stories with paragraphs, then a one-liner tail.

Template substitution variables (rendered by the runner before calling the LLM): `{{title}}`, `{{description}}`, `{{sources}}`, `{{cadence_window}}` (human string like "since yesterday"), `{{history_paths}}` (paths to prior digests for the topic).

## 4. The builtin agent loop and tools

Applies only to `runner: builtin`. The `claude-code` and `codex` runners delegate the loop entirely to their respective CLIs and use those CLIs' built-in tools.

### 4.1 The loop

```
1. Build system prompt (Section 4.4) and initial user message.
2. Start a monotonic wall-clock timer.
3. Loop:
   a. Call LiteLLM with full message history + tools schema.
   b. If response has tool calls: dispatch each via the tool registry,
      append results as tool-role messages.
   c. If write_digest was called this turn: exit OK.
   d. If wall-clock exceeded timeout_seconds: abort, exit failed.
   e. Continue.
4. If loop ends without write_digest ever being called: exit failed.
```

### 4.2 LLM client

`agent/llm.py` is a thin wrapper around `litellm.completion(...)`. Single function:

```python
def call(messages, tools, model) -> Response
```

Per-turn token usage and cost are read from the response (`response.usage`, `litellm.completion_cost(response)`) and recorded in the per-run log.

### 4.3 Tool registry

A dict `{name -> ToolImpl}`. Each `ToolImpl` declares:

- JSON-Schema of inputs (consumed by the model in the tools array).
- Python handler.
- `runner_compat: set[str]` — which runners support it. All five v1 tools are supported by the builtin runner. (The CLI runners use their CLI's own tools and ignore this registry.)
- `default_enabled: bool` — whether this tool is included when a topic config omits the `tools` allowlist. All v1 tools are `default_enabled=True` **except** `browser_use`, which is opt-in: a topic must list it explicitly in `tools` to use it (because Playwright is heavyweight and requires `playwright install`).

The five v1 tools (builtin runner):

| Tool | Input | Output | Notes |
|------|-------|--------|-------|
| `web_search` | `query: str`, `num_results: int = 5` | list of `{title, url, snippet}` | Brave Search API. Per-query result cache within a run. |
| `fetch_url` | `url: str`, `mode: "auto"\|"html"\|"rss" = "auto"` | extracted text, ≤200 KB | `httpx` + `trafilatura` for HTML; `feedparser` for RSS; `auto` infers from Content-Type. |
| `browser_use` | `url: str`, `wait_for_selector: str = None` | rendered DOM text, ≤200 KB | Playwright + headless Chromium. Heavier; usable only when a topic explicitly allowlists it. |
| `read_history` | `n: int = 5` | concatenated markdown of last `n` digests for this topic | Reads `output/<slug>/*.md` newest-first. No LLM-side cost. |
| `write_digest` | `markdown_body: str` | confirmation + written path | Writes `output/<slug>/<YYYY-MM-DD>.md` (UTC date). Last-call-wins if invoked more than once. Calling this is how the agent signals "done." |

Tool-level errors (network failure, parse failure, 4xx) are returned to the model as `{"error": "..."}` — recoverable; the model can retry or move on. Only catastrophic conditions (lock unobtainable, output dir unwritable) abort the run.

### 4.4 System prompt skeleton

Built per-run from the topic config:

```
You are Scout's agent for the topic "{title}".

Description: {description}

You produce a single markdown digest of what's new for this topic since
the last run. Use the tools to gather sources, then call write_digest
exactly once to finish.

Sources (seeds — starting points, not an exhaustive list; you should
also use web_search, fetch_url, and browser_use to discover additional
relevant sources):
{sources_block}

Last run: {last_run_iso} ({elapsed_human} ago).
Wall-clock budget: {timeout_seconds}s.

Format requirements:
{rendered_prompt_template_or_inline}

Avoid repeating items already covered in prior digests; call read_history
if you need to check.
```

The initial user message contains the rendered prompt template body, with substitutions applied.

## 5. State, scheduling, and deduplication

### 5.1 Per-topic state file

`state/<slug>.json`, gitignored. Written atomically (write to `*.tmp`, then rename):

```json
{
  "last_run": "2026-05-20T07:00:11Z",
  "last_status": "ok",
  "last_error": null,
  "last_duration_seconds": 38.2
}
```

`last_status ∈ {"ok", "failed"}`. `last_error` is non-null only when `last_status == "failed"`. Skipped runs (lock contention) exit without touching state, so `"skipped"` is a process exit message — not a stored state value.

### 5.2 Scheduling logic

For each topic:

```
next_due = croniter(cadence, last_run or epoch).get_next(datetime)
if now >= next_due:
    topic is due
```

A topic with no prior `last_run` is due immediately.

### 5.3 State transitions per run

1. Acquire `state/<slug>.lock` (else exit `skipped`, do not update state).
2. Run the agent loop (Section 4).
3. **Always** set `last_run = now` (success or failure). Failed runs do not retry immediately — they wait for the next cadence slot. Manual retry: `scout run --topic X --force`.
4. Persist `last_status`, `last_error`, `last_duration_seconds`.
5. Release the lock.

### 5.4 Deduplication

There is no content-hash store and no seen-URL set. Deduplication is delegated to the LLM via the `read_history` tool: the agent reads recent prior digests for the topic and avoids repeating items. This is intentional — it lets the agent use semantic judgment (same story, different headline) instead of brittle URL matching, and keeps state trivial.

### 5.5 Concurrency

- One worker per topic at a time, enforced by the per-topic file lock.
- Global concurrency cap from `scout.toml`'s `scheduler.max_concurrent_workers` (default 3); enforced by `scout tick`.
- Cross-topic git operations are serialized by a repo-level lock (Section 6.2).

## 6. Output format and git workflow

### 6.1 Digest file format

The runner writes the file. The agent writes only the body via `write_digest(markdown_body)`. The runner prepends YAML frontmatter:

```markdown
---
topic: ai-research
date: 2026-05-20
runner: builtin
model: anthropic/claude-sonnet-4-6
duration_seconds: 38.2
tool_calls: {web_search: 3, fetch_url: 12, read_history: 1}
tokens: {input: 45000, output: 3200}
cost_usd: 0.18
---

[agent's markdown body, verbatim]
```

For `runner ∈ {claude-code, codex}`, fields the runner cannot introspect are recorded as the literal string `unknown`:

```yaml
runner: claude-code
model: unknown
duration_seconds: 47.1
tool_calls: unknown
tokens: unknown
cost_usd: unknown
```

### 6.2 Git publish flow

After `write_digest` succeeds, before the runner returns:

```
1. Acquire repo-level lock: state/.publish.lock (flock).
2. git add output/<slug>/<file>.md
3. git commit -m "digest(<slug>): <YYYY-MM-DD>" \
       --author "<author_name> <<author_email>>"
4. git push <remote> <branch>
   - on failure: git pull --rebase <remote> <branch>; git push <remote> <branch> (one retry)
   - on still-failure: log the error and accept the local commit;
     next successful run reconciles.
5. Release the lock.
```

One commit per successful run. Empty-content digests (the agent decided nothing notable happened) are still committed — they're useful signal that Scout ran.

Failed runs (timeout, no `write_digest` call) produce no commit and no push.

### 6.3 Same-day collisions

`write_digest` writes `output/<slug>/<YYYY-MM-DD>.md`. If that file already exists (topic configured for multiple runs per day, or a `--force` manual rerun), the runner instead writes `output/<slug>/<YYYY-MM-DD>-<HHMMSS>.md` (UTC). No overwrites, ever.

### 6.4 Committed vs gitignored

| Committed | Gitignored |
|-----------|------------|
| `src/`, `pyproject.toml`, `uv.lock` | `.venv/`, `__pycache__/` |
| `topics/*.yaml` | `state/` (per-topic JSON, locks) |
| `prompts/*.md` | `logs/` (per-run JSONL, tick log) |
| `scout.toml` | `.env` (secrets) |
| `output/**/*.md` | |
| `spec.md`, `AGENTS.md` | |

### 6.5 Auth

Push authentication is whatever the host already provides (SSH key, or an HTTPS credential helper / PAT in the remote URL). Scout does not manage push credentials; it just invokes `git push`. Credential setup is a deployment concern.

## 7. Error handling and observability

### 7.1 Failure modes

| Failure | Where | Behavior |
|---|---|---|
| Tool call errors (network, parse, 4xx, 404) | inside agent loop | Return `{"error": "..."}` to the model. Recoverable. |
| LiteLLM rate-limit / transient error | LLM call | Exponential backoff: up to 3 attempts, base delay 2s. |
| LiteLLM auth / model-not-found / non-transient 4xx | LLM call | No retry. Fail the run. |
| Wall-clock timeout | loop | Abort. `last_status="failed"`, `last_error="timeout after Xs"`. No commit. |
| Loop ends without `write_digest` | loop | Fail. `last_error="no digest produced"`. No commit. |
| `git push` failure | publish | One `pull --rebase` retry, then accept local commit; next run reconciles. |
| State file missing or corrupted | tick startup | Log warning; treat as no prior run; topic is due. |
| Lock contention | run startup | Exit `skipped (locked)`. Not a failure. State is **not** updated. |
| Topic config invalid | tick startup | Log error; skip that topic; continue with the rest. `scout validate` catches these proactively. |

### 7.2 Logging

**Per-run JSONL** at `logs/<slug>/<YYYY-MM-DD-HHMMSS>.jsonl`. One event per line:

```jsonl
{"ts":"...","event":"run_start","slug":"ai-research","runner":"builtin","model":"..."}
{"ts":"...","event":"llm_turn","turn":1,"input_tokens":1200,"output_tokens":50,"cost_usd":0.004}
{"ts":"...","event":"tool_call","tool":"web_search","args":{...},"duration_ms":320,"result_bytes":1200}
{"ts":"...","event":"tool_error","tool":"fetch_url","error":"timeout","args":{...}}
{"ts":"...","event":"write_digest","path":"output/.../2026-05-20.md","bytes":4200}
{"ts":"...","event":"run_end","status":"ok","duration_seconds":38.2,"total_cost_usd":0.18}
```

For CLI runners, captured stdout/stderr from the subprocess is emitted as `subprocess_output` events.

**Tick log** at `logs/tick.log` (gitignored). One line per tick summarizing topics evaluated, spawned, skipped, and failed. Cron captures stdout/stderr from `scout tick` and appends here.

### 7.3 No live notifications in v1

No email, push, or chat alerts. Two CLI commands cover the health-check use case:

- `scout topics` — table: `slug | cadence | last_run | last_status | next_due | last_cost_usd`.
- `scout doctor` — health summary: success/failure counts per topic over the last 7 days, most recent error per topic if any, total spend over the period. Plain text.

If silent failures become a problem in practice, a daily summary email is a small addition later — not v1.

### 7.4 Observability asymmetry across runners

The builtin runner logs LLM turns, tool calls, tokens, and cost in full. The `claude-code` and `codex` runners are opaque subprocesses; for those, frontmatter and per-run logs record `unknown` for fields Scout can't observe. This asymmetry is accepted as the cost of pluggable external runners.

## 8. Testing strategy

### 8.1 Tier 1 — Unit (fast, deterministic, every commit)

- `config.py` — valid configs load, invalid configs raise with clear messages, slug derived from filename, every documented field has at least one positive and one negative case.
- `scheduler.py` — croniter-based is-due logic with a frozen clock. Edge cases: first run, just-missed slot, multiple topics due simultaneously.
- `state.py` — read/write/missing/corrupted; atomicity (temp + rename).
- `git_publish.py` — against a temp git repo with a temp bare `origin`. Happy path, push-fail-then-rebase, repo lock contention.
- `feedback.py` — parse well-formed blocks, ignore malformed blocks with a warning.
- Tool input-schema validation — each tool's JSON-Schema matches its handler signature (introspection test).
- Frontmatter assembly — given a fixed run record, produces stable bytes.

### 8.2 Tier 2 — Integration (slower, fixture-backed, CI)

- Agent loop end-to-end with a `FakeLLMClient` returning a scripted sequence (some turns with tool calls, ending with `write_digest`). Asserts tool dispatch order and final output file existence.
- Each network tool against recorded HTTP fixtures (`pytest-httpserver` or VCR-style cassettes): `web_search`, `fetch_url` (HTML + RSS branches).
- `browser_use` — gated behind `@pytest.mark.browser`. Runs Playwright against a locally served page. Skipped in default CI.
- `scout run --topic smoke` end-to-end with a fixture topic + fake LLM + fixture-backed tools. Validates the whole runner wiring.

### 8.3 Tier 3 — Smoke (manual)

- `scout run --topic X --dry-run` — exercises the real LLM and real tools end-to-end but **skips git commit/push**. Output lands in `output/` for inspection. Used to validate a topic config before enabling its cron.

### 8.4 Non-goals

- No digest-quality evals (LLM-as-judge, human grading). Quality is judged by reading the output.
- No quality tests of `claude-code` or `codex` runners beyond verifying the subprocess is invoked with the right arguments.
- No load or soak tests.

### 8.5 Test layout

```
tests/
├── unit/
│   ├── test_config.py
│   ├── test_scheduler.py
│   ├── test_state.py
│   ├── test_git_publish.py
│   ├── test_feedback.py
│   └── test_tool_schemas.py
├── integration/
│   ├── test_agent_loop.py
│   ├── test_tools.py
│   ├── test_runner_builtin.py
│   └── test_browser.py          # @mark.browser
├── fakes/
│   ├── llm.py                    # FakeLLMClient
│   └── brave.py
├── fixtures/
│   ├── topics/                   # valid + invalid YAML samples
│   ├── http/                     # cassettes
│   └── llm/                      # scripted responses
└── conftest.py
```

Test runner: `uv run pytest`. CI: GitHub Actions, runs unit + integration by default; browser tier on demand. No live LLM calls in CI.

## 9. Feedback capture (v1: capture only)

The user gives feedback by editing the digest file directly and adding an HTML-comment block:

```markdown
<!-- scout-feedback
rating: 4
notes: |
  Liked the structure. Missed the Llama 3.5 release on the 18th —
  please catch that source next time. Stop including SemiAnalysis
  paywalled summaries.
tags: [missed, paywall]
missed:
  - https://example.com/llama-3-5-announcement
-->
```

The marker `scout-feedback` opens the block; the body is free-form YAML. **All fields are optional and uninterpreted in v1.** A loose schema is documented for the user's convenience:

- `rating: 1-5` — scalar signal.
- `notes:` — free text.
- `tags: [...]` — categorical signal (e.g., `missed`, `paywall`, `off-topic`).
- `missed: [...]` — items the agent should have caught (URL or short description).

### 9.1 Workflow

1. User `git pull`s on Mac.
2. Opens any digest in an editor.
3. Adds a feedback block anywhere in the body.
4. `git commit && git push`.

Scout never modifies an existing digest, so user edits are safe.

### 9.2 CLI helpers

- `scout feedback add --topic X [--date Y] [--rating N] [--notes "..."]` — appends a feedback block to the specified digest without opening an editor. `--date` defaults to the most recent digest for the topic.
- `scout feedback list [--topic X] [--since 30d]` — extracts and prints all feedback blocks across digests as a flat report. Malformed blocks are skipped with a warning.

### 9.3 Why inline

- One file per digest to read and annotate — no juggling sidecar files.
- Naturally carried by `read_history` — when v2 adds auto-incorporation, the agent already sees feedback in context with no new plumbing.
- Git diff shows feedback being added — clean audit trail.

### 9.4 Non-goals for v1

- No automatic incorporation into next-run prompts (deferred to v2).
- No analytics or rollups.
- No web UI for feedback entry.

## 10. CLI surface (summary)

| Command | Purpose |
|---|---|
| `scout tick` | Orchestrator; run from cron every 15 min. |
| `scout run --topic X [--force] [--dry-run]` | Run one topic now. `--force` bypasses the due check; `--dry-run` skips commit/push. |
| `scout topics` | Status table across all topics. |
| `scout validate` | Schema-check every topic config; nonzero exit on any failure. |
| `scout doctor` | Health summary over the last 7 days. |
| `scout feedback add ...` | Append a feedback block to a digest. |
| `scout feedback list ...` | Report feedback blocks across digests. |

## 11. Dependencies (anticipated)

- `litellm` — model provider abstraction.
- `httpx` — HTTP client.
- `trafilatura` — HTML article extraction.
- `feedparser` — RSS/Atom parsing.
- `playwright` — headless browser (optional; only if any topic uses `browser_use`).
- `croniter` — cron expression parsing.
- `pydantic` — config schema.
- `pyyaml` — YAML loading.
- `pytest`, `pytest-httpserver` — testing.

Secrets (LiteLLM provider keys, Brave Search API key) are read from environment variables. A `.env` file at the repo root is supported and gitignored.

## 12. Deployment notes (informational, not part of Scout itself)

- Target: any Linux host with `git`, `uv`, and outbound network. The `claude-code` runner additionally requires the Claude Code CLI installed and authenticated; the `codex` runner requires the Codex CLI similarly.
- Install: `git clone`, `uv sync`, then `uv run playwright install chromium` if any topic uses `browser_use`.
- Cron: one line, `*/15 * * * * cd /path/to/scout && uv run scout tick >> logs/tick.log 2>&1`.
- Git push credentials: SSH key or HTTPS PAT, set up out-of-band.
- Provider API keys: in `.env` (gitignored).
