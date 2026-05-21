# Scout v1 Acceptance Checklist

Run from a fresh clone on a Linux or macOS host. Set `BRAVE_SEARCH_API_KEY`
and provider creds for LiteLLM in `.env`. Topic file used: `topics/test.yaml`
with `runner: builtin`, a real model string, and `prompt: { template: briefing }`.

## Config and CLI

- [ ] `uv sync` succeeds.
- [ ] `uv run scout --help` lists: `tick`, `run`, `topics`, `validate`, `doctor`, `feedback`.
- [ ] `uv run scout validate` exits 0 with a clean topics dir.
- [ ] Add a malformed topic (`bad.yaml` with a missing required field) → `validate` exits nonzero AND `topics` does not include the bad topic.
- [ ] `uv run scout topics` prints a table including the test topic with cadence and `last_run=—`.

## Scheduling

- [ ] First `scout tick` after adding a topic marks it due → spawns it.
- [ ] After a successful run, `scout tick` does NOT respawn it until the next cadence slot.
- [ ] `scout run --topic test --force` runs regardless of due check.
- [ ] Running `scout run --topic test` twice concurrently → exactly one runs, the other exits "skipped (locked)".

## Builtin runner (live LLM, dry-run)

- [ ] `uv run scout run --topic test --dry-run --force` produces `output/test/<today>.md` with valid frontmatter.
- [ ] Frontmatter has non-`unknown` values for `model`, `duration_seconds`, `tool_calls`, `tokens`, `cost_usd`.
- [ ] The body is a coherent markdown digest matching the briefing template.
- [ ] No git commit was created (dry-run).
- [ ] Per-run JSONL exists at `logs/test/<timestamp>.jsonl` and contains `run_start`, `llm_turn` events, at least one `tool_call`, and `run_end` with `status=ok`.

## Failure modes

- [ ] Set `timeout_seconds: 1` for the test topic → run fails with `last_status=failed`, `last_error="timeout..."`. No commit. No file written.
- [ ] Remove `BRAVE_SEARCH_API_KEY` → a `web_search` tool call returns `{"ok": false, ...}` in the JSONL but the run can still complete via other tools.
- [ ] Break git push (e.g., delete the remote URL) → the run still succeeds locally, log shows "push deferred".

## External runners

- [ ] `runner: claude-code` topic produces a digest file with `model: unknown` in frontmatter, calling the real `claude` CLI.
- [ ] `runner: codex` topic produces a digest file similarly.

## Feedback

- [ ] Manually add a `<!-- scout-feedback ... -->` block to a digest.
- [ ] `scout feedback list --topic test` shows the block in the report.
- [ ] `scout feedback add --topic test --rating 4 --notes "ok"` appends a new block; `feedback list` shows two blocks.

## Sign-off

- [ ] All boxes above checked.
- [ ] Real cron line added to crontab and one tick observed.
- [ ] Output appears on GitHub via `git pull` on another machine.
