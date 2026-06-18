# Scout

Scout is a personal news agent that turns web research into scheduled,
per-topic Markdown digests.

Scout is meant to run with two repositories:

- A **code repo** for this Python project.
- A **data repo**, conventionally next to it as `../scout-data`, for the live
  `scout.toml`, topic YAML files, generated digests, local state, and logs.

You define topics in the data repo, Scout decides when each topic is due, an
agent gathers material from configured seed sources and the open web, and the
result is written to the data repo's `output/` directory as Markdown with YAML
frontmatter.

## Contents

- [What Scout Does](#what-scout-does)
- [Repository Model](#repository-model)
- [How It Works](#how-it-works)
- [Requirements](#requirements)
- [Quick Start](#quick-start)
- [Topic Configuration](#topic-configuration)
- [Global Configuration](#global-configuration)
- [Runners](#runners)
- [Built-in Tools](#built-in-tools)
- [CLI Reference](#cli-reference)
- [Output, State, Logs, and Trajectories](#output-state-logs-and-trajectories)
- [Feedback Workflow](#feedback-workflow)
- [Web App (PWA)](#web-app-pwa)
- [Running on a Schedule](#running-on-a-schedule)
- [Development](#development)
- [Project Layout](#project-layout)
- [Troubleshooting](#troubleshooting)

## What Scout Does

Scout is for recurring information needs: AI research updates, company
monitoring, policy changes, market news, niche blogs, academic releases, or any
other topic where you want an agent to periodically collect and summarize what
changed.

Core behavior:

- Runs each topic on its own cron expression.
- Uses topic sources as research seeds, not as a closed list.
- Supports RSS/Atom feeds, web pages, web search queries, and optional rendered
  browser reads.
- Reads live topic config from the data repo's `topics/` directory.
- Produces Markdown digests in the data repo at
  `output/<topic>/<date>.md`.
- Adds run metadata as YAML frontmatter: topic, date, runner, model, duration,
  tool calls, token usage, and cost when available.
- Stores local run state in the data repo's `state/` directory and a full,
  committed per-run trajectory (JSONL) in its `trajectories/` directory.
- Provides CLI helpers for validation, status, health checks, and inline
  feedback capture.

Scout is intentionally a CLI-first project. There is no web UI, notification
system, or quality evaluation framework in v1.

## Repository Model

Scout separates code from runtime data.

Code repo:

```text
scout/
|-- pyproject.toml
|-- src/scout/
|-- prompts/
|-- tests/
`-- README.md
```

Data repo:

```text
scout-data/
|-- scout.toml
|-- topics/
|   `-- <slug>.yaml
|-- output/
|   `-- <slug>/<YYYY-MM-DD>.md
|-- trajectories/
|   `-- <slug>/<run-id>.jsonl
|-- state/
`-- logs/
```

Scout writes digests to the data repo's `output/` directory and a full
record of every run to `trajectories/` (committed — see [Trajectories](#trajectories)).
Its `state/` and `logs/` directories hold local runtime artifacts (scheduler
state and operational stdout such as the cron tick log).

In this checkout, the practical layout is:

```text
~/git/
|-- scout/
`-- scout-data/
```

When running Scout from source, keep the current working directory set to the
data repo and point `uv` at the code repo:

```bash
cd ../scout-data
uv --project ../scout run scout topics
```

That detail matters because Scout resolves `topics/`, `scout.toml`, `output/`,
`state/`, and `logs/` relative to the process working directory in the current
implementation.

## How It Works

The normal production entrypoint is run with the data repo as the working
directory:

```bash
cd /path/to/scout-data
uv --project /path/to/scout run scout tick
```

`scout tick`:

1. Loads every `topics/*.yaml` file from the data repo.
2. Reads `state/<slug>.json` in the data repo for each topic.
3. Uses the topic's cron expression to decide whether the topic is due.
4. Spawns due topics as isolated workers.
5. Runs multiple topics concurrently up to the configured global limit.

Each worker runs:

```bash
uv --project /path/to/scout run scout run --topic <slug>
```

For one topic, the worker:

1. Acquires `state/<slug>.lock` in the data repo so the same topic cannot run
   twice at once.
2. Dispatches to the configured runner.
3. Writes a digest under the data repo's `output/<slug>/`.
4. Updates the data repo's `state/<slug>.json` with success or failure.

For the default `builtin` runner, Scout owns the whole agent loop through
LiteLLM. The model can call Scout's tool registry, gather context, and finishes
by calling `write_digest`.

For `claude-code` and `codex` runners, Scout delegates the agent loop to the
external CLI and records opaque telemetry where the CLI does not expose token or
tool details.

## Requirements

Required:

- Python 3.12 or newer.
- `uv`.
- `git`.
- Network access for web research and LLM provider calls.
- Provider credentials for whichever LiteLLM model you configure.

Required for the default built-in web search tool:

- `BRAVE_SEARCH_API_KEY`.

Required only for optional features:

- Playwright Chromium, if a topic enables `browser_use`.
- The Claude Code CLI, if a topic uses `runner: claude-code`.
- The Codex CLI, if a topic uses `runner: codex`.

Scout reads credentials from environment variables at runtime. For example,
depending on your configured model, LiteLLM may need variables such as
`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, or `GEMINI_API_KEY`.

Keep secrets outside git. Scout loads a `.env` file automatically on startup,
looking first in the data dir (`--data-dir` / `SCOUT_DATA_DIR`) and then in the
current working directory. Real environment variables always win over `.env`
values, and the data dir's `.env` wins over the cwd's. The repo's `.gitignore`
already excludes `.env`, so credentials there stay out of git. You can still
export secrets directly in the shell, service manager, or cron environment
instead — those take precedence over any `.env` file.

For example, a `.env` in your data dir:

```dotenv
GEMINI_API_KEY=...
BRAVE_SEARCH_API_KEY=...
```

## Quick Start

From the code repo, install dependencies:

```bash
cd /path/to/scout
uv sync
```

For development dependencies too:

```bash
uv sync --all-extras
```

Create or clone the data repo next to it:

```bash
cd /path/to
git clone https://github.com/<you>/scout-data.git scout-data
```

For a new data repo, scaffold it with `scout init` (creates the directory
layout, `scout.toml`, and `.gitignore`):

```bash
uv --project /path/to/scout run scout init /path/to/scout-data
```

Optionally make it a git repo and push:

```bash
cd /path/to/scout-data
git init -b main
git add .
git commit -m "scout-data: initial layout"
# git remote add origin git@github.com:<you>/scout-data.git && git push -u origin main
```

Check the CLI while using the data repo as the working directory:

```bash
cd /path/to/scout-data
uv --project ../scout run scout --help
```

Create your first topic in the data repo:

```yaml
# topics/ai-research.yaml
title: AI research
description: >
  Frontier AI research and engineering: model releases, evaluations,
  training and inference techniques, alignment work, and important papers.
  Avoid general product announcements unless they change the technical picture.
cadence: "0 7 * * *"

sources:
  - type: rss
    url: https://example.com/feed.xml
  - type: web
    url: https://example.com/research
  - type: search
    query: frontier AI research this week

runner: builtin
model: anthropic/claude-sonnet-4-6

prompt:
  template: briefing
```

Validate topic config:

```bash
uv --project ../scout run scout validate
```

Run the topic once:

```bash
uv --project ../scout run scout run --topic ai-research --force
```

Inspect the result:

```bash
ls output/ai-research/
```

Check topic status:

```bash
uv --project ../scout run scout topics
```

Or let `tick` run all due topics:

```bash
uv --project ../scout run scout tick
```

Scout writes the digest and updates local topic state in the data repo.

## Topic Configuration

Topics live in the data repo's `topics/` directory. Each topic is one YAML
file. The file stem is the topic slug, so `topics/ai-research.yaml` creates
the slug `ai-research`.

Slugs must match:

```text
^[a-z0-9][a-z0-9-]*$
```

Use lowercase ASCII letters, numbers, and hyphens. Do not use dots in the stem.

### Full Topic Example

```yaml
title: AI research
description: >
  Frontier AI research and engineering: model releases, evaluations,
  training/inference techniques, alignment work, and important papers.

cadence: "0 7 * * *"

sources:
  - type: rss
    url: https://example.com/feed.xml
  - type: web
    url: https://example.com/blog
  - type: search
    query: frontier AI research this week

runner: builtin
model: anthropic/claude-sonnet-4-6

prompt:
  template: briefing

limits:
  timeout_seconds: 300

tools:
  - web_search
  - fetch_url
  - read_history
  - write_digest
```

### Required Fields

- `title`: Human-readable topic label.
- `description`: The semantic brief given to the agent. This is where you
  define what belongs in the topic and what should be ignored.
- `cadence`: A five-field cron expression. Scout computes the next due time
  from the last recorded run.
- `prompt`: Exactly one of `template` or `inline`.
- `model`: Required when `runner: builtin`. It is a LiteLLM model string, such
  as `anthropic/claude-sonnet-4-6`, `openai/...`, or `gemini/...`.

### Optional Fields

- `sources`: A list of seed sources. Seeds help the agent begin research, but
  the agent is allowed to search and follow additional sources.
- `runner`: One of `builtin`, `claude-code`, or `codex`. Defaults to
  `builtin`.
- `effort`: Reasoning effort for the `claude-code` runner, passed to
  `claude --effort`. One of `low`, `medium`, `high`, `xhigh`, or `max`. If
  omitted, the CLI uses its own default. Rejected for other runners.
- `limits.timeout_seconds`: Per-topic wall-clock timeout. If omitted, Scout
  uses the global timeout from `scout.toml`.
- `tools`: Built-in runner tool allowlist. If omitted, Scout enables every
  default tool except `browser_use`. This field is ignored for external CLI
  runners.

### Source Types

RSS or Atom feed:

```yaml
- type: rss
  url: https://example.com/feed.xml
```

Web page:

```yaml
- type: web
  url: https://example.com/blog
```

Search query:

```yaml
- type: search
  query: "site:example.com quarterly results"
```

### Prompt Templates

Scout ships three prompt templates in the code repo's `prompts/` directory:

- `briefing`: a short synthesized briefing with inline citations.
- `headlines`: a flat list of headline items with summaries and links.
- `sectioned`: top stories followed by a compact "everything else" section.

Reference a template by filename stem:

```yaml
prompt:
  template: briefing
```

Or use an inline prompt:

```yaml
prompt:
  inline: |
    Produce a concise digest with three sections:
    1. Most important developments
    2. Secondary updates
    3. Links worth reading
```

Supported template variables:

Run-window variables — substituted for **every** runner (builtin, claude-code,
codex):

- `{{now}}` — this run's start time, UTC (e.g. `2026-06-08 03:00 UTC`)
- `{{last_run}}` — the previous **successful** run's time, UTC. Sourced from the
  last success (not the last attempt), so a failed run does not shrink the next
  window. On a topic's first run it renders `(no previous run — first run for
  this topic)`; a prompt that uses `{{last_run}}` as a hard lower bound should
  branch on that marker (there is no defensible concrete bound on a cold start).
- `{{cadence_window}}` — a human phrase describing the `[last_run, now]` window
  (e.g. `since the last run at 2026-06-07 03:00 UTC, through 2026-06-08 03:00
  UTC`), for templates that want prose rather than raw bounds.

Builtin-template variables — substituted by the **builtin** runner only:

- `{{title}}`
- `{{description}}`
- `{{sources}}`
- `{{history_paths}}`

Any placeholder a prompt does not use is left as-is.

## Global Configuration

Global defaults live in the data repo's `scout.toml`.

```toml
[defaults]
runner = "builtin"
model  = "anthropic/claude-sonnet-4-6"
timeout_seconds = 300

[scheduler]
max_concurrent_workers = 3

[llm]
# Reserved for future overrides.
```

Current behavior to know:

- `scheduler.max_concurrent_workers` caps concurrent topic workers launched by
  `scout tick`.
- `defaults.timeout_seconds` is used when a topic does not set
  `limits.timeout_seconds`.
- Built-in topics currently still need an explicit `model` field in their YAML.

## Runners

### `builtin`

The default runner. Scout owns the agent loop and calls LiteLLM directly.

Use it when you want:

- Full JSONL run trajectories (messages, tool calls/results, metrics).
- Tool-call counts in digest frontmatter.
- Token and cost telemetry when LiteLLM returns it.
- Scout's built-in tool allowlist.

Requires:

- A `model` field on the topic.
- Provider credentials for that model.
- `BRAVE_SEARCH_API_KEY` if the model uses `web_search`.

### `claude-code`

Runs the external Claude Code CLI (`claude -p`) as a subprocess. Scout asks the
CLI to write the digest into the topic output directory, then Scout adds
frontmatter.

Use it when you want Claude Code's own tool behavior instead of Scout's
built-in loop.

The CLI is invoked with `--output-format stream-json`, and Scout parses that
stream, so the run is not opaque:

- The agent has the full Claude Code built-in tool set available. `WebSearch`,
  `WebFetch`, `Read`, `Glob`, and `Write` are the ones it leans on, but it can
  also reach `Bash`, `Task`, and the multi-agent `Workflow` tool. Because a
  headless `claude -p` run can't answer permission prompts, it runs with
  `--permission-mode bypassPermissions` so any tool can be called without
  stalling. The host's MCP servers are still ignored (`--strict-mcp-config`) to
  keep runs focused and deterministic.
- If the topic sets `model`, it is passed to `claude --model`; otherwise the
  CLI's default model is used.
- The agent reviews prior digests in the topic's output folder (`Glob` + `Read`)
  to avoid repeating items.

Requires:

- `claude` available on `PATH`.
- The Claude Code CLI already authenticated.

Telemetry:

- `model`, `tool_calls`, `tokens`, and `cost_usd` are parsed from the CLI's
  `stream-json` result and recorded in the run log and digest frontmatter, just
  like the `builtin` runner. They fall back to `unknown` only if the CLI emits
  no parseable result (e.g. a crash before the final event).
- On timeout, Scout still records the partial tool activity and output streamed
  before the run was killed.

### `codex`

Runs the external Codex CLI as a subprocess. The operational shape is the same
as `claude-code`.

Requires:

- `codex` available on `PATH`.
- The Codex CLI already authenticated.

Telemetry:

- Opaque fields are recorded as `unknown`.

## Built-in Tools

The `builtin` runner exposes these tools to the model:

| Tool | Default | Purpose |
| --- | --- | --- |
| `web_search` | Yes | Search the web through Brave Search. |
| `fetch_url` | Yes | Fetch and extract text from HTML pages or RSS feeds. |
| `read_history` | Yes | Read recent prior digests for the topic. |
| `write_digest` | Yes | Save the final Markdown digest and finish the run. |
| `browser_use` | No | Render a URL in headless Chromium and return page text. |

`browser_use` is opt-in because it is heavier than the other tools and requires
Playwright's browser runtime:

```bash
cd /path/to/scout
uv run playwright install chromium
```

Enable it per topic:

```yaml
tools:
  - web_search
  - fetch_url
  - read_history
  - write_digest
  - browser_use
```

Tool errors are returned to the model as structured error payloads. For example,
missing `BRAVE_SEARCH_API_KEY` causes `web_search` to return an error instead of
crashing the whole process.

## CLI Reference

The examples below assume your shell is in the data repo and the code repo is
available at `../scout`:

```bash
cd /path/to/scout-data
```

### `scout validate`

Schema-check every `topics/*.yaml` file in the data repo.

```bash
uv --project ../scout run scout validate
```

Returns nonzero if any topic fails validation.

### `scout topics`

Print a status table for configured topics:

```bash
uv --project ../scout run scout topics
```

Columns:

- `slug`
- `cadence`
- `last_run`
- `last_status`
- `next_due`

### `scout run`

Run one topic:

```bash
uv --project ../scout run scout run --topic ai-research
```

Options:

- `--force`: bypass due-check logic and run now.

Examples:

```bash
uv --project ../scout run scout run --topic ai-research --force
```

### `scout tick`

Evaluate every topic and run the ones that are due:

```bash
uv --project ../scout run scout tick
```

This is the command intended for cron.

### `scout doctor`

Summarize runs from the last seven days using the data repo's `trajectories/`:

```bash
uv --project ../scout run scout doctor
```

Shows per-topic success count, failure count, total observed cost, and most
recent error.

### `scout serve`

Serve the data repo's digests as a mobile-friendly web app:

```bash
uv --project ../scout run scout serve
```

Options:

- `--host`: bind address (default: `127.0.0.1`).
- `--port`: port (default: `8533`).

See [Web App (PWA)](#web-app-pwa) for what it serves and how to install it on
a phone.

### `scout trajectories serve`

Serve the run [trajectories](#trajectories) as a browsable dashboard — an index
of recent runs across topics, a per-topic run list, and a per-run timeline that
walks each message, tool call/result, artifact, and the final metrics:

```bash
uv --project ../scout run scout trajectories serve
```

Options:

- `--host`: bind address (default: `127.0.0.1`).
- `--port`: port (default: `8534`).

There is also a JSON endpoint at `/api/r/<slug>/<run-id>` returning the raw
records for a run.

### `scout feedback add`

Append a feedback block to a digest:

```bash
uv --project ../scout run scout feedback add \
  --topic ai-research \
  --rating 4 \
  --notes "Good structure."
```

Target a specific digest date:

```bash
uv --project ../scout run scout feedback add --topic ai-research --date 2026-05-27 --rating 5
```

If `--date` is omitted, Scout appends feedback to the latest digest for that
topic.

### `scout feedback list`

List feedback blocks:

```bash
uv --project ../scout run scout feedback list
uv --project ../scout run scout feedback list --topic ai-research
```

`--since` exists as a reserved v1 option but is currently ignored.

## Output, State, Logs, and Trajectories

### Output

Digests are written in the data repo under:

```text
output/<slug>/<YYYY-MM-DD>.md
```

The built-in runner avoids same-day filename collisions by adding a UTC time
suffix when needed:

```text
output/<slug>/<YYYY-MM-DD-HHMMSS>.md
```

Every digest starts with YAML frontmatter:

```yaml
---
topic: ai-research
date: 2026-05-27
runner: builtin
model: anthropic/claude-sonnet-4-6
duration_seconds: 38.2
tool_calls:
  web_search: 3
  fetch_url: 8
  read_history: 1
  write_digest: 1
tokens:
  input: 45000
  output: 3200
cost_usd: 0.18
---
```

The digest body follows the frontmatter.

### State

Scout stores per-topic scheduler state in the data repo:

```text
state/<slug>.json
```

`state/` is gitignored. It records:

- `last_run`
- `last_status`
- `last_error`
- `last_duration_seconds`

State is updated for both successful and failed runs. Lock-contention skips do
not update state.

### Trajectories

Every run records a full **trajectory** — a replayable transcript of what the
agent did — as newline-delimited JSON in the data repo:

```text
trajectories/<slug>/<run-id>.jsonl
```

`<run-id>` is a [ULID](https://github.com/ulid/spec) (time-sortable, so a
directory listing stays chronological). The file is a `run` header, a stream of
`message` / `tool_call` / `tool_result` / `artifact` records, and a terminal
`result` with aggregate metrics (duration, token usage incl. cache breakdown,
per-model split, cost, tool counts). Field names follow the OpenTelemetry GenAI
semantic conventions; the schema and a worked example live in
[`docs/trajectory-schema.md`](docs/trajectory-schema.md) and
[`docs/trajectory.schema.json`](docs/trajectory.schema.json).

Unlike `logs/`, `trajectories/` is **committed** to the data repo, so every
digest keeps its full provenance. Browse them with
[`scout trajectories serve`](#scout-trajectories-serve).

## Feedback Workflow

Feedback is stored inline in digest Markdown as an HTML comment containing YAML:

```markdown
<!-- scout-feedback
rating: 4
notes: |
  Good structure, but it missed the most important release.
tags: [missed, source-quality]
missed:
  - https://example.com/important-release
-->
```

Scout can append these blocks with `scout feedback add` and list them with
`scout feedback list`.

In v1, feedback is captured but not automatically incorporated into future
prompts. Because feedback lives in the digest file, it stays alongside the
digest and can later be read by agents through history.

## Web App (PWA)

`scout serve` runs a small FastAPI server that renders the data repo's
digests as an installable progressive web app:

- **Latest** — newest digests across all topics in one feed.
- **Topics** — every topic that has output (including paused/disabled ones),
  with unread-count badges.
- **Digest** — the rendered Markdown, a collapsible "Run details" section
  (runner, model, duration, tokens, cost, tool calls), and a feedback form.

Feedback submitted from the app is appended to the digest file as a standard
`scout-feedback` block (with `source: web`), so `scout feedback list` and
agents reading history see it like any other feedback. Read/unread state is
stored in the browser's local storage; it does not sync across devices.

### Installing on a phone

Android Chrome only installs PWAs (and registers their service worker) from
an HTTPS origin, so the easiest path to your phone is
[Tailscale](https://tailscale.com/):

```bash
uv --project ../scout run scout serve          # binds 127.0.0.1:8533
tailscale serve --bg 8533                      # one-time; HTTPS on your tailnet
```

`tailscale serve` prints the URL (`https://<machine>.<tailnet>.ts.net`). Open
it in Chrome on the phone (with Tailscale connected) and choose
**Install app** / **Add to Home Screen** from the menu.

Without HTTPS the app still works as a plain website over the LAN — run with
`--host 0.0.0.0` and open `http://<machine-ip>:8533`; only installability and
the service worker are lost.

### Icons

The PWA icons are committed under `src/scout/server/static/icons/` and
regenerated with `python3 scripts/gen_icons.py` (needs Pillow, which is
deliberately not a project dependency).

## Running on a Schedule

Make sure the data repo has the expected runtime directories:

```bash
cd /path/to/scout-data
mkdir -p logs state output topics trajectories
```

Install dependencies in the code repo:

```bash
cd /path/to/scout
uv sync
```

Make sure secrets are available to cron. A common pattern is a small wrapper
script that exports keys or sources a local `.env`, then runs Scout.

Example crontab entry:

```cron
*/15 * * * * cd /path/to/scout-data && ./run-scout-tick.sh
```

Where `run-scout-tick.sh` is a small data-repo-local wrapper like:

```bash
#!/bin/sh
uv --project /path/to/scout run scout tick >> logs/tick.log 2>&1
```

Use `scout topics` and `scout doctor` to verify the schedule is healthy:

```bash
cd /path/to/scout-data
uv --project /path/to/scout run scout topics
uv --project /path/to/scout run scout doctor
```

## Development

Install all dependencies:

```bash
uv sync --all-extras
```

Run lint:

```bash
uv run ruff check .
```

Run the default test suite:

```bash
uv run pytest -m "not browser and not smoke" -q
```

Run all non-smoke tests, including browser tests, after installing Chromium:

```bash
uv run playwright install chromium
uv run pytest -m "not smoke"
```

Run real-LLM smoke tests:

```bash
GOOGLE_API_KEY="$GOOGLE_API_KEY" uv run pytest -m smoke
```

The smoke test fixture maps `GOOGLE_API_KEY` to `GEMINI_API_KEY` for LiteLLM
when needed.

CI runs on GitHub Actions and executes:

```bash
uv run ruff check .
uv run pytest -m "not browser and not smoke" -q
```

## Project Layout

Code repo:

```text
scout/
|-- pyproject.toml
|-- docs/
|   `-- spec-initial-implementation.md
|-- prompts/
|   |-- briefing.md
|   |-- headlines.md
|   `-- sectioned.md
|-- src/scout/
|   |-- cli.py
|   |-- config.py
|   |-- scheduler.py
|   |-- worker.py
|   |-- orchestrator.py
|   |-- runner.py
|   |-- runners/
|   |-- agent/
|   |-- server/
|   |-- output.py
|   |-- state.py
|   |-- runlog.py
|   |-- doctor.py
|   `-- feedback.py
`-- tests/
```

Data repo:

```text
scout-data/
|-- scout.toml
|-- topics/
|   `-- <slug>.yaml
|-- output/
|   `-- <slug>/<YYYY-MM-DD>.md
|-- trajectories/
|   `-- <slug>/<run-id>.jsonl
|-- state/
`-- logs/
```

Important boundaries:

- `scheduler.py` handles due-time logic only.
- `worker.py` owns one-topic execution and data-repo state updates.
- `orchestrator.py` implements `scout tick`.
- `runner.py` selects a runner implementation.
- `runners/builtin.py` wires the LiteLLM agent loop.
- `agent/tools/` contains one built-in tool per file.
- `feedback.py` parses and appends inline feedback blocks.

## Troubleshooting

### `web_search` returns `BRAVE_SEARCH_API_KEY missing`

Set `BRAVE_SEARCH_API_KEY` in the environment used to run Scout.

To run it once for inspection:

```bash
cd /path/to/scout-data
BRAVE_SEARCH_API_KEY=... uv --project /path/to/scout run scout run \
  --topic ai-research \
  --force
```

### Built-in runner fails before writing a digest

Common causes:

- Missing or invalid LiteLLM provider credentials.
- Invalid model string.
- Timeout too short for the topic.
- The model returned final text instead of calling `write_digest`.

Check:

```bash
ls trajectories/<slug>/
uv --project /path/to/scout run scout doctor
```

### `scout tick` says no topics are due

Check the topic table:

```bash
uv --project /path/to/scout run scout topics
```

Run manually if you want to bypass cadence:

```bash
uv --project /path/to/scout run scout run --topic <slug> --force
```

### A topic is skipped as locked

Another process already holds `state/<slug>.lock`. This is normal when two runs
overlap. If no Scout process is running and the message persists, inspect the
host process table before deleting lock files.
