# Project Improvement Suggestions

These are documentation-adjacent issues I noticed while writing the README.
They are suggestions only; no project files besides this note and `README.md`
were changed.

## 1. Make the data repo path explicit in the CLI

Scout is intended to publish digests into a separate data repo such as
`../scout-data`. The current mainline implementation gets there by relying on
the process working directory, so source runs need a command like
`cd ../scout-data && uv --project ../scout run scout tick`.

Suggested direction: merge the explicit data-path work (`--data-dir` and
`$SCOUT_DATA_DIR`) so Scout can be run from the code repo without accidentally
using the code repo as the data repo.

## 2. Mark `spec.md` as historical or replace it

`spec.md` describes the initial implementation and still says topics, output,
state, and logs live in the project repo. That conflicts with the intended
two-repo model where runtime data lives in `scout-data`.

Suggested direction: either label `spec.md` as an archived design document or
replace it with a current architecture document that makes the data repo the
source of truth.

## 3. Apply or remove unused global defaults

The data repo's `scout.toml` defines `defaults.runner` and `defaults.model`, but
topic loading currently requires `model` whenever `runner: builtin` and does not
merge the global model into topic configs.

Suggested direction: either apply global defaults during topic loading or make
the config/docs explicit that those default keys are reserved or only partially
used.

## 4. Validate prompt template existence

`scout validate` checks topic schema, but `prompt.template` is not checked
against files in the code repo's `prompts/`. A typo can pass validation and fail
later at run time when the runner reads the template.

Suggested direction: have topic loading or `scout validate` verify that
`prompts/<template>.md` exists.

## 5. Add first-topic scaffolding

The data repo starts without a topic example. A `scout init-topic` command or a
committed `topics/example.yaml.sample` in the data repo would make first-run
setup less error-prone.

Suggested direction: provide an example that includes a safe prompt, a search
seed, a web seed, and notes about required environment variables.

## 6. Clarify or change `--dry-run` state semantics

`scout run --dry-run` skips git publish, but it still writes output and updates
the data repo's `state/<slug>.json`. That is accurate to the implementation,
but may surprise users who expect dry runs not to affect scheduling.

Suggested direction: either document this very prominently, rename the mode to
something like `--no-publish`, or add a stricter dry-run mode that avoids state
updates.

## 7. Add optional `.env` loading

`.env` is gitignored and the spec mentions environment-based secrets, but the
application does not load `.env` directly. Users must export variables via their
shell, cron, or wrapper script.

Suggested direction: either add `python-dotenv` loading at CLI startup or keep
runtime behavior environment-only and avoid implying first-class `.env` support.

## 8. Handle same-day output collisions for external runners

The built-in runner uses `pick_output_path()` to avoid overwriting same-day
digests. The `claude-code` and `codex` runners prompt the external CLI to write
to the data repo's `output/<slug>/<YYYY-MM-DD>.md`, which can overwrite an
existing same-day file during repeated forced runs.

Suggested direction: allocate the output path in Scout before invoking the
external runner and pass that exact path into the prompt.

## 9. Make cron logging setup safer

The recommended cron command redirects to the data repo's `logs/tick.log`, but a
fresh data repo clone may not have `logs/` because it is gitignored. Redirects
fail before Scout starts if the directory is missing.

Suggested direction: either include setup instructions that run `mkdir -p logs`
or provide a wrapper command that creates runtime directories before ticking.

## 10. Bring `scout topics` in line with current architecture docs

The historical spec describes a `last_cost_usd` value in the topics table, but
the current CLI prints `slug`, `cadence`, `last_run`, `last_status`, and
`next_due`.

Suggested direction: either add the cost column by reading recent data repo logs
or update the current architecture docs to match the CLI.

## 11. Add a targeted browser-test workflow

CI skips `browser` and `smoke` tests. That is sensible for default CI, but the
optional Playwright path would benefit from a manual or scheduled workflow that
installs Chromium and runs `pytest -m browser`.

Suggested direction: add a `workflow_dispatch` GitHub Actions job for browser
tests.
