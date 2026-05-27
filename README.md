# Scout

> A personal news agent that runs on a schedule, gathers what's new on the
> topics you care about, and writes a markdown digest you can read anywhere.

Scout is a small, self-hosted tool. You declare topics in YAML. A cron entry
ticks every 15 minutes. When a topic is due, an LLM agent loop fetches feeds,
searches the web, fetches pages, optionally drives a headless browser, and
writes a markdown digest to your **data repo**, which gets committed and
pushed so the digest is available on any device.

No web UI, no notifications, no SaaS dependency beyond your model provider.

## Two repos: code and data

Scout deliberately splits into two git repositories:

- **Code repo** (this one) — the Python project and the shipped prompt
  templates. Versioned with code releases.
- **Data repo** — your topics, your live `scout.toml`, your committed
  digests, and your per-machine state and logs. You create this once,
  per deployment, and point Scout at it via `$SCOUT_DATA_DIR` (or `--data-dir`).

Conventionally the data repo lives at `~/git/scout-data` and tracks the
hostname-agnostic things (topics, digests, config) on its own GitHub remote.
Per-machine things (`state/`, `logs/`) are gitignored inside it.

Why split? It lets the code travel separately from any one deployment's data,
keeps generated artifacts out of the Python source tree, and means topic
edits and digest commits are isolated from code changes. See
[`docs/setup.md`](./docs/setup.md) for the bootstrap recipe.

---

## Table of contents

- [How it works](#how-it-works)
- [Quick start](#quick-start)
- [Configuring topics](#configuring-topics)
- [Runners](#runners)
- [Tools (builtin runner)](#tools-builtin-runner)
- [Output format](#output-format)
- [Giving feedback on a digest](#giving-feedback-on-a-digest)
- [CLI reference](#cli-reference)
- [Deployment (cron + git)](#deployment-cron--git)
- [Configuration reference](#configuration-reference)
- [Repository layout](#repository-layout)
- [Development and testing](#development-and-testing)
- [Design notes](#design-notes)

---

## How it works

```
                                    ┌──────────────────────────────────────┐
                                    │            HOST                      │
                                    │                                      │
┌─────────────────┐   every 15 min  │  ┌─────────────┐                     │
│  cron on host   │ ──────────────▶ │  │ scout tick  │                     │
└─────────────────┘                 │  │ (code repo) │                     │
                                    │  └──────┬──────┘                     │
                                    │         │ uv run scout run --topic X │
                                    │         │ --data-dir $SCOUT_DATA_DIR │
                                    │         ▼                            │
                                    │  ┌─────────────┐                     │
                                    │  │ scout run   │  reads topics/,     │
                                    │  │  (worker)   │  scout.toml         │
                                    │  └──────┬──────┘                     │
                                    │         │                            │
                                    │   ┌─────┴─────┬──────────┐           │
                                    │   ▼           ▼          ▼           │
                                    │ builtin   claude-code  codex         │
                                    │ ReAct loop  subproc    subproc       │
                                    │  + tools                             │
                                    └─────────┬────────────────────────────┘
                                              │ writes
                                              ▼
                              ┌──────────────────────────────────┐
                              │   DATA REPO ($SCOUT_DATA_DIR)    │
                              │                                  │
                              │   topics/<slug>.yaml             │
                              │   output/<slug>/<date>.md  ◀──── digest written here
                              │   state/<slug>.json   (gitignored)
                              │   logs/<slug>/*.jsonl (gitignored)
                              │   scout.toml                     │
                              └─────────┬────────────────────────┘
                                        │ git commit + push
                                        ▼
                                ┌────────────────┐
                                │  data git      │   (GitHub, etc.)
                                │  remote        │
                                └────────────────┘
```

The orchestrator (`scout tick`) is stateless: it reads `state/<slug>.json`
inside the data repo for each topic, computes `next_due` with `croniter`, and
spawns a subprocess per due topic. Each worker passes `--data-dir` to its
child so the whole tick uses one consistent data root. Per-topic file locks
make concurrent runs of the same topic safe; a global cap (default 3) limits
total in-flight workers.

The default `builtin` runner is a thin, provider-agnostic ReAct loop on top
of [LiteLLM](https://docs.litellm.ai/) — model strings like
`anthropic/claude-sonnet-4-6`, `openai/gpt-4o`, `gemini/gemini-2.5-flash` all
work. Two alternative runners shell out to the `claude` (Claude Code) or
`codex` CLIs if you'd rather rely on those.

---

## Quick start

### Prerequisites

- Python 3.12+
- [`uv`](https://docs.astral.sh/uv/) (the project uses `uv` for env + run)
- A model provider API key for whichever model you set in your topic (e.g.
  `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`).
- A `BRAVE_SEARCH_API_KEY` if you want the `web_search` tool to function.
- (Optional) `playwright install chromium` if any topic uses `browser_use`.

### 1. Install the code repo

```bash
git clone https://github.com/<you>/scout.git ~/git/scout
cd ~/git/scout
uv sync
```

Put provider credentials in `~/git/scout/.env` (gitignored):

```bash
ANTHROPIC_API_KEY=sk-ant-...
BRAVE_SEARCH_API_KEY=...
```

### 2. Bootstrap the data repo

```bash
mkdir -p ~/git/scout-data/{topics,output,state,logs}
cd ~/git/scout-data
git init -b main
cp ~/git/scout/scout.toml.example ./scout.toml
printf "state/\nlogs/\n" > .gitignore
git add .
git commit -m "scout-data: initial layout"

# Optional: push to your own GitHub remote so digests sync across machines.
# git remote add origin git@github.com:<you>/scout-data.git
# git push -u origin main
```

### 3. Point Scout at the data repo

```bash
export SCOUT_DATA_DIR=~/git/scout-data
```

Add that line to your shell rc so it's set for every session and for cron.
Alternatively, pass `--data-dir ~/git/scout-data` on every invocation.

### 4. Define a topic

Create `~/git/scout-data/topics/ai-research.yaml`:

```yaml
title: "AI research"
description: >
  Frontier AI research and engineering — new model releases, capability
  evals, training/inference techniques, alignment work. Not product news.
cadence: "0 7 * * *"            # 07:00 UTC every day
model: anthropic/claude-sonnet-4-6
prompt:
  template: briefing
sources:
  - { type: rss,    url: https://example.com/feed.xml }
  - { type: web,    url: https://example.com/blog }
  - { type: search, query: "frontier AI research this week" }
```

### 5. Validate and dry-run

```bash
cd ~/git/scout
uv run scout validate                          # schema-check all topics
uv run scout topics                            # status table
uv run scout run --topic ai-research --force --dry-run
```

`--force` bypasses the cadence check. `--dry-run` skips the git commit/push
so you can inspect `~/git/scout-data/output/ai-research/<today>.md` before
wiring up cron.

### 6. Wire up cron

```cron
*/15 * * * * SCOUT_DATA_DIR=/home/you/git/scout-data cd /home/you/git/scout && uv run scout tick >> /home/you/git/scout-data/logs/tick.log 2>&1
```

`cd` into the code repo so `uv run` finds the project; pass the data root as
an env var so children inherit it. That's it — Scout now produces digests on
the cadence you declared and pushes them to your data-repo remote.

---

## Configuring topics

One YAML file per topic in `$SCOUT_DATA_DIR/topics/`. The filename stem is
the slug (used as the directory name in `output/` and as the key in state).

| Field           | Required | Notes |
|-----------------|----------|-------|
| `title`         | yes      | Human label, used in the digest. |
| `description`   | yes      | Semantic context passed to the agent. The agent uses this to decide what's on-topic. |
| `cadence`       | yes      | 5-field cron expression. `next_due = croniter(cadence).get_next(last_run)`. |
| `runner`        | no       | `builtin` (default), `claude-code`, or `codex`. |
| `model`         | builtin only | LiteLLM model string. Required for `builtin`; ignored (with warning) for CLI runners. |
| `prompt`        | yes      | Exactly one of `template:` (file stem under `prompts/` in the code repo) or `inline:` (literal body with `{{vars}}`). |
| `sources`       | no       | Seed list of `{type: rss|web|search, url|query}`. **Not exhaustive** — the agent is free to discover more. |
| `tools`         | builtin only | Allowlist subset of supported tools. Defaults to everything except `browser_use`. |
| `limits.timeout_seconds` | no | Wall-clock budget for a single run. Falls back to `scout.toml`. |

### Validation rules

Filename must match `^[a-z0-9][a-z0-9-]*\.yaml$`. Validation also enforces:

- `cadence` parses as a valid 5-field cron expression.
- `runner ∈ {builtin, claude-code, codex}`.
- `model` is required when `runner: builtin`.
- Exactly one of `prompt.template` / `prompt.inline`.
- `prompt.template` (when set) must exist as a file in the code repo's `prompts/`.
- `tools` (when set) must be a subset of the builtin runner's tool registry.
- `limits.timeout_seconds` (when set) must be a positive integer.

`scout validate` runs all of this and exits non-zero on any failure.

### Shipped prompt templates

Templates ship with the code repo, in `prompts/`. They're not duplicated into
the data repo — topics reference them by stem.

| Template     | Shape |
|--------------|-------|
| `headlines`  | Flat list of items, each = bold headline + 1–2 sentence summary + source link. |
| `briefing`   | A few paragraphs synthesizing the period, with inline citations. |
| `sectioned`  | "Top stories" with paragraphs, then an "Everything else" bullet tail. |

Variables substituted before the LLM call: `{{title}}`, `{{description}}`,
`{{sources}}`, `{{cadence_window}}` (e.g. "since yesterday"), `{{history_paths}}`.

---

## Runners

| Runner       | Where the loop runs | LLM observability | When to use |
|--------------|--------------------|--------------------|-------------|
| `builtin`    | In-process. Scout owns the ReAct loop and calls LiteLLM directly. | Full: per-turn tokens, cost, tool calls, durations. | Default. Recommended. |
| `claude-code`| Subprocess to the `claude` CLI. | Opaque. Fields recorded as `unknown` in frontmatter. | You've already invested in Claude Code's tool ecosystem and want to reuse it. |
| `codex`      | Subprocess to the `codex` CLI. | Opaque. Same as above. | Same idea, for the Codex CLI. |

For the CLI runners, the `tools` and `model` fields in a topic are ignored
(with a warning); those runners use their CLI's own tools and authentication.

---

## Tools (builtin runner)

The builtin runner exposes five tools to the model. The model decides when to
call them; Scout returns results as tool-role messages. Tool errors come back
as `{"error": "..."}` and are recoverable — the model can retry or move on.

| Tool           | Input                                          | Output                                          | Default? |
|----------------|------------------------------------------------|-------------------------------------------------|----------|
| `web_search`   | `query`, `num_results` (default 5)             | List of `{title, url, snippet}`. Brave Search.  | yes |
| `fetch_url`    | `url`, `mode: auto|html|rss` (default auto)    | Extracted text (≤200 KB). HTML via trafilatura, RSS via feedparser. | yes |
| `read_history` | `n` (default 5)                                | Concatenated markdown of the last `n` digests for this topic. | yes |
| `write_digest` | `markdown_body`                                | Confirmation + written path. **Calling this is how the agent signals "done."** | yes |
| `browser_use`  | `url`, `wait_for_selector` (optional)          | Rendered DOM text (≤200 KB). Playwright + headless Chromium. | **opt-in** |

`browser_use` is opt-in because Playwright is heavy and needs
`playwright install chromium`. A topic must list it explicitly under `tools:`
to enable it.

---

## Output format

Each successful run writes a file to
`$SCOUT_DATA_DIR/output/<slug>/<YYYY-MM-DD>.md`. The runner writes the file;
the agent writes only the body. The runner prepends YAML frontmatter:

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

For `claude-code` and `codex` runners, fields Scout cannot introspect appear
as the literal string `unknown`.

**Same-day collisions.** If the file already exists (multi-run-per-day topic
or a `--force` re-run), the runner writes `<YYYY-MM-DD>-<HHMMSS>.md` instead.
Existing digests are never overwritten.

**Empty digests are still committed.** "Nothing notable happened" is useful
signal that Scout ran.

---

## Giving feedback on a digest

You give feedback by editing a digest file directly. Drop an HTML-comment
block anywhere in the body:

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

Commit and push **inside the data repo**. Scout never modifies an existing
digest, so your edits are always safe.

In v1, feedback is **captured but not auto-incorporated** — the agent doesn't
yet read prior feedback when planning the next run. The format is documented
so it's ready for v2.

Convenience commands:

- `scout feedback add --topic X [--date Y] [--rating N] [--notes "..."]` —
  append a feedback block to the specified digest without opening an editor.
- `scout feedback list [--topic X]` — extract and print all feedback blocks
  across digests.

---

## CLI reference

All commands accept a global `--data-dir <path>` flag, which overrides
`$SCOUT_DATA_DIR`. If neither is set, Scout exits with
`scout: no data directory configured: set $SCOUT_DATA_DIR or pass --data-dir`.

| Command                                       | Purpose |
|-----------------------------------------------|---------|
| `scout tick`                                  | Orchestrator. Run from cron every 15 min. |
| `scout run --topic X [--force] [--dry-run]`   | Run one topic now. `--force` bypasses the due check; `--dry-run` skips commit/push. |
| `scout topics`                                | Status table: `slug | cadence | last_run | last_status | next_due`. |
| `scout validate`                              | Schema-check every topic config; nonzero exit on any failure. |
| `scout doctor`                                | Health summary over the last 7 days: ok/fail counts and total cost per topic. |
| `scout feedback add ...`                      | Append a feedback block to a digest. |
| `scout feedback list ...`                     | Report feedback blocks across digests. |

All commands take `--help`.

---

## Deployment (cron + git)

Scout is designed for a long-lived Linux host. Recommended setup:

1. **Clone and sync the code repo.** `git clone …; cd scout; uv sync`.
2. **Bootstrap the data repo** (see [Quick start §2](#2-bootstrap-the-data-repo)).
3. **Provider creds.** In `.env` at the code repo root (gitignored).
4. **Optional: Playwright.** Only if any topic uses `browser_use`:
   `uv run playwright install chromium`.
5. **Git push credentials for the data repo.** Whatever the host already
   provides — an SSH key or an HTTPS credential helper / PAT in the data
   repo's remote URL. Scout calls `git push` inside the data repo; it does
   not manage credentials itself. The code repo is never touched by Scout
   at runtime.
6. **Cron.**
   ```cron
   */15 * * * * SCOUT_DATA_DIR=/home/you/git/scout-data cd /home/you/git/scout && uv run scout tick >> /home/you/git/scout-data/logs/tick.log 2>&1
   ```
7. **Verify.** Watch `$SCOUT_DATA_DIR/logs/tick.log` after the first tick;
   `scout topics` and `scout doctor` show health.

### What's tracked where

**Code repo** (this one) — versioned with code releases:

| Tracked                                | Not tracked              |
|----------------------------------------|--------------------------|
| `src/`, `pyproject.toml`, `uv.lock`    | `.venv/`, `__pycache__/` |
| `prompts/*.md`                         | `.env` (secrets)         |
| `scout.toml.example`                   |                          |
| `spec.md`, `AGENTS.md`, `docs/`        |                          |

**Data repo** (at `$SCOUT_DATA_DIR`) — your deployment's data:

| Tracked                                | Not tracked                       |
|----------------------------------------|-----------------------------------|
| `topics/*.yaml`                        | `state/` (per-machine, per-topic) |
| `output/**/*.md`                       | `logs/` (per-machine)             |
| `scout.toml`                           |                                   |

Scout commits and pushes only files under `$SCOUT_DATA_DIR/output/`. Topic
YAMLs and `scout.toml` you edit and commit yourself.

### Git publish flow (inside the data repo)

After `write_digest` succeeds, the runner:

1. Acquires the repo-level lock `state/.publish.lock`.
2. `git -C $SCOUT_DATA_DIR add output/<slug>/<file>.md`.
3. `git -C $SCOUT_DATA_DIR commit -m "digest(<slug>): <YYYY-MM-DD>" --author "<name> <<email>>"`.
4. `git -C $SCOUT_DATA_DIR push`. On failure, one `git pull --rebase` then
   retry the push.
5. If still failing: log the error and accept the local commit. The next
   successful run reconciles.

One commit per successful run. Failed runs produce no commit.

---

## Configuration reference

### Global defaults — `scout.toml` (in the data repo)

The shipped `scout.toml.example` (in the code repo) is the template; on
bootstrap you copy it into the data repo and edit your live values there.
Topic YAMLs override these per-key.

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

### Per-topic state — `state/<slug>.json` (in the data repo, gitignored)

```json
{
  "last_run": "2026-05-20T07:00:11Z",
  "last_status": "ok",
  "last_error": null,
  "last_duration_seconds": 38.2
}
```

`last_status ∈ {"ok", "failed"}`. Skipped runs (lock contention) do **not**
update state — they're a process exit, not a stored outcome. Failed runs do
not auto-retry; they wait for the next cadence slot (or `--force`).

State is intentionally per-machine and gitignored: two hosts running the
same data repo each maintain their own cadence cursors and don't fight each
other on locks.

### Logs

- **Per-run JSONL** at `$SCOUT_DATA_DIR/logs/<slug>/<YYYY-MM-DD-HHMMSS>.jsonl`.
  One event per line: `run_start`, `llm_turn`, `tool_call`, `tool_error`,
  `write_digest`, `run_end`. For CLI runners, captured subprocess output
  appears as `subprocess_output` events.
- **Tick log** at `$SCOUT_DATA_DIR/logs/tick.log`. One summary line per tick.
  Cron appends stdout/stderr here.

Both are gitignored in the data repo.

---

## Repository layout

### Code repo

```
scout/
├── pyproject.toml              # uv project
├── scout.toml.example          # template; copied into the data repo on setup
├── spec.md                     # original design spec (now partially stale; see Design notes)
├── AGENTS.md                   # one-line project description (symlinked as CLAUDE.md)
├── docs/
│   └── setup.md                # bootstrap recipe for code + data repos
├── src/scout/
│   ├── cli.py                  # tick | run | topics | validate | doctor | feedback
│   ├── paths.py                # DataPaths value object + resolve()
│   ├── orchestrator.py         # `scout tick`: due-set + worker pool
│   ├── worker.py               # `scout run --topic`: lock, dispatch, publish
│   ├── scheduler.py            # croniter-based is-due logic
│   ├── runner.py               # Runner protocol, factory
│   ├── runners/
│   │   ├── builtin.py          # in-process agent loop
│   │   ├── claude_code.py      # subprocess wrapper for `claude`
│   │   └── codex.py            # subprocess wrapper for `codex`
│   ├── agent/                  # used by the builtin runner
│   │   ├── loop.py             # the ReAct loop
│   │   ├── llm.py              # LiteLLM client
│   │   └── tools/              # web_search, fetch_url, browser, read_history, write_digest
│   ├── config.py               # topic + global config schemas (pydantic)
│   ├── state.py                # last-run state read/write + locks
│   ├── runlog.py               # per-run JSONL emitter
│   ├── output.py               # frontmatter assembly + digest write
│   ├── git_publish.py          # commit + push inside the data repo
│   ├── feedback.py             # inline-feedback parser & CLI helpers
│   └── doctor.py               # 7-day health summary
├── prompts/                    # shipped templates (headlines, briefing, sectioned)
└── tests/                      # unit, integration, fixtures, fakes
```

### Data repo (at `$SCOUT_DATA_DIR`)

```
scout-data/
├── scout.toml                  # live config (global defaults, git identity, etc.)
├── topics/                     # user-edited, one YAML per topic
│   └── ai-research.yaml
├── output/                     # committed; <slug>/<YYYY-MM-DD>.md
├── state/                      # gitignored (per-machine)
├── logs/                       # gitignored (per-machine)
└── .gitignore                  # state/, logs/
```

### Module boundaries (code repo)

Deliberately tight:

- `paths` is the only module that resolves the data-dir from CLI / env.
  Everything downstream takes a `DataPaths` value object.
- `scheduler` knows nothing about agents or LLMs — pure config + state + time math.
- `runner` decides which implementation handles a topic; doesn't run agent code itself.
- `runners/builtin` owns the in-process loop; internals live in `agent/`.
- `runners/claude_code` and `runners/codex` are thin subprocess wrappers.
- `agent/loop` talks only to `agent/llm` and the tool registry; provider-agnostic.
- Each `agent/tools/*.py` is exactly one tool.
- `git_publish` is the only module that touches git, and only inside the data repo.
- `feedback` reads digest markdown only; never modifies it.

---

## Development and testing

```bash
uv sync --all-extras
uv run pytest                      # unit + integration; no live LLM, no browser
uv run pytest -m browser           # integration tests that need Playwright
uv run pytest -m smoke             # real-LLM smoke tests; needs GOOGLE_API_KEY
uv run ruff check .
```

Tests build their own ephemeral `DataPaths` over `tmp_path` — they don't
require a real data repo to be present.

CI (`.github/workflows/ci.yml`) runs `ruff check` and
`pytest -m 'not browser and not smoke'` on every push and PR.

### Test tiers

- **Unit** (`tests/unit/`) — fast, deterministic. Config parsing, scheduler,
  state, tool schemas, feedback parser, frontmatter assembly, data-dir
  resolution.
- **Integration** (`tests/integration/`) — fixture-backed end-to-end. Agent
  loop with `FakeLLMClient`, network tools against recorded HTTP, full
  `scout run` wiring against a temp data repo + temp bare git remote.
- **Browser** (`@pytest.mark.browser`) — Playwright tests; skipped by
  default.
- **Smoke** (`@pytest.mark.smoke`) — real-LLM, real-tools end-to-end. Manual.

There are **no digest-quality evals in v1**. Quality is judged by reading
the output.

---

## Design notes

A few choices that may look surprising on first read:

- **Code and data are separate repos.** It lets the code travel separately
  from any one deployment's data, keeps generated artifacts out of the
  Python source tree, and makes topic-edit / digest commits independent of
  code changes. State and logs are per-machine and stay gitignored inside
  the data repo, so multiple hosts can share the same data remote without
  fighting each other.
- **Sources are seeds, not an allowlist.** The agent is free to discover
  more via `web_search` and `fetch_url`. The seed list anchors the topic and
  gives the agent a starting point.
- **No content-hash / seen-URL dedupe store.** Deduplication is delegated
  to the LLM via the `read_history` tool. The agent reads recent prior
  digests and uses semantic judgment to avoid repetition. State stays
  trivial; the agent handles "same story, different headline" without
  brittle URL matching.
- **No cost cap.** Wall-clock timeout is the only hard limit. Cost is
  logged, not enforced.
- **No live notifications.** `scout topics` and `scout doctor` cover the
  health-check use case. A daily summary email is a small addition later
  if silent failures become a problem.
- **Asymmetric observability.** The `builtin` runner logs LLM turns, tool
  calls, tokens, and cost in full. CLI runners are opaque subprocesses;
  those fields appear as `unknown` in frontmatter and logs. This is the
  accepted cost of pluggable external runners.
- **No auto-incorporation of feedback in v1.** Feedback is captured in a
  documented format and surfaces naturally via `read_history` — v2 can
  wire in auto-incorporation with no new plumbing.

> **Note on `spec.md`.** The original design spec was written for the v1
> implementation, before the code/data repo split. The boundaries, agent
> loop, tool surface, and runners it describes are still accurate; the
> repo-layout, paths, and bootstrap sections in §2.2 and §3.2 have been
> updated, but the rest of `spec.md` has not been kept in lockstep. When
> the two disagree, this README and the code are the source of truth.
