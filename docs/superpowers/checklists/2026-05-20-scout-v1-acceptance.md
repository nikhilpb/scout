# Scout v1 Acceptance Checklist

Run from a fresh clone on a Linux or macOS host. Set `BRAVE_SEARCH_API_KEY`
and provider creds for LiteLLM in `.env`. Topic file used: `topics/test.yaml`
with `runner: builtin`, a real model string, and `prompt: { template: briefing }`.

## Config and CLI

- [x] `uv sync` succeeds.
- [x] `uv run scout --help` lists: `tick`, `run`, `topics`, `validate`, `doctor`, `feedback`.
- [x] `uv run scout validate` exits 0 with a clean topics dir.
- [x] Add a malformed topic (`bad.yaml` with a missing required field) → `validate` exits nonzero AND `topics` does not include the bad topic.
- [x] `uv run scout topics` prints a table including the test topic with cadence and `last_run=—`.

## Scheduling

- [x] First `scout tick` after adding a topic marks it due → spawns it.
- [x] After a successful run, `scout tick` does NOT respawn it until the next cadence slot.
- [x] `scout run --topic test --force` runs regardless of due check.
- [x] Running `scout run --topic test` twice concurrently → exactly one runs, the other exits "skipped (locked)".

## Builtin runner (live LLM, dry-run)

- [x] `uv run scout run --topic test --dry-run --force` produces `output/test/<today>.md` with valid frontmatter.
- [x] Frontmatter has non-`unknown` values for `model`, `duration_seconds`, `tool_calls`, `tokens`, `cost_usd`.
- [x] The body is a coherent markdown digest matching the briefing template.
- [x] No git commit was created (dry-run).
- [x] Per-run JSONL exists at `logs/test/<timestamp>.jsonl` and contains `run_start`, `llm_turn` events, at least one `tool_call`, and `run_end` with `status=ok`.

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
