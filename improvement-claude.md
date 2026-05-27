# Improvements

Notes on things I noticed while writing the README that look like genuine
gaps, mismatches, or low-effort wins. Ranked roughly by ratio of value to
effort. Nothing here is urgent — Scout v1 is coherent as-is.

## Spec ↔ implementation drift

These are places where `spec.md` and the code disagree. The fix is usually a
few lines; the value is keeping the docs honest.

1. **`scout topics` is missing `last_cost_usd`.**
   - `spec.md` §7.3 says the table should be
     `slug | cadence | last_run | last_status | next_due | last_cost_usd`.
   - `src/scout/cli.py:_cmd_topics` only emits the first five columns.
   - The data is already in `logs/<slug>/*.jsonl` (`run_end.cost_usd`) — same
     parse `doctor.py` already does. Lift that into a helper and call from both.

2. **`scout topics` could surface `next_due` as a relative time.**
   - The current ISO string is hard to scan at a glance ("next run in 2h13m"
     is what you actually want). Keep the ISO timestamp as a column; add
     `next_in` next to it.

3. **`scout feedback list --since` is documented but silently ignored.**
   - The argparse argument is declared with the help text
     `"ignored in v1; reserved for future filtering"`. Either implement it
     (parse `7d`, `30d`, ISO date) or drop the flag — currently it advertises
     a feature that doesn't exist.

4. **CLI runners' `tools`/`model` warning is mentioned in the spec but I'd
   double-check it's actually emitted at load time.** If it isn't yet, this
   is a one-line change in `config.py` plus a unit test.

## Operational quality-of-life

5. **No `scout new --topic <slug>` scaffolder.**
   - The fastest path from "I want to track X" to "running" today is
     copy-paste another topic YAML and edit it. A scaffolder that takes
     `--title`, `--description`, `--cadence` and writes a valid
     `topics/<slug>.yaml` from a template would be a 30-line addition and
     would also serve as the canonical "this is what a topic looks like".

6. **No `scout install-cron` helper.**
   - The cron line is the same on every install modulo the path. A helper
     that prints the line for the current install (or appends to the user
     crontab with `--apply`) removes a fiddly manual step. Not strictly
     necessary; reduces a foot-gun.

7. **JSON output mode for `topics` and `doctor`.**
   - Both produce nicely-formatted tables, but they're hard to consume from
     other tools (e.g., a dashboard, a Slack bot a user wires up themselves).
     `--json` on both would unlock that and is trivial to add.

8. **No `tick.log` rotation.**
   - `logs/tick.log` grows forever. The per-run JSONL files are naturally
     bounded by retention, but `tick.log` isn't. Either: (a) document that
     users should `logrotate` it; (b) emit it as `logs/tick-YYYY-MM.log` and
     let old months age out; (c) cap on size with a tiny self-rotating
     writer. (a) is the cheapest.

## Robustness

9. **No per-topic LLM turn cap.**
   - Wall-clock timeout is the only hard limit. A pathological model could
     loop on cheap turns and never call `write_digest`, consuming budget
     until the wall clock fires. A `max_turns` (default ~25?) on the loop
     would be defense in depth. Should be configurable in `scout.toml`
     defaults and overridable per topic.

10. **No retry on the LLM 5xx side of `litellm.completion`.**
    - The spec calls for "exponential backoff: up to 3 attempts, base delay
      2s" for transient errors. Worth verifying this is actually wired up in
      `agent/llm.py` (couldn't tell from a fast read) and that
      auth/model-not-found errors short-circuit.

11. **State file recovery on corruption is silent.**
    - The spec says corrupted state is logged and treated as "no prior run".
      The behavior is right; a one-line `WARNING` in `scout topics` /
      `scout doctor` ("state for X was corrupted; treating as fresh") would
      stop this being invisible.

12. **`git_publish` accepts the local commit when push fails after one
    `pull --rebase`.** The next successful run reconciles, but if a topic
    runs once a week, the local commit can sit unmerged for a long time. A
    `scout doctor` warning when local HEAD is ahead of `origin/<branch>`
    would surface this without changing behavior.

## Developer experience

13. **`spec.md` is 580 lines and is the authoritative source of truth.**
    - That's fine for design, less fine for new contributors. Most readers
      land on the README first now (good), but a small `docs/architecture.md`
      that summarizes the module boundaries in code-link form would be a
      cheap bridge.

14. **No `CHANGELOG.md`.**
    - Single-user project, but with `version = "0.1.0"` already in
      `pyproject.toml`, a one-line `## 0.1.0 — v1 scope shipped` entry per
      release would carry its weight when "did this prompt template change
      affect the briefing format?" comes up six months from now.

15. **`AGENTS.md` is one sentence, symlinked as `CLAUDE.md`.**
    - That's fine, but a few breadcrumbs there would help any future agent
      collaborator orient faster: where to start reading
      (`spec.md → README.md → cli.py`), how to run tests, what
      `superpowers` skills are expected.

## Possible v2 hints

Not improvements, just things the spec already flags as deferred — listed
here so they're not forgotten if/when v2 starts:

- **Auto-incorporation of feedback** into next-run prompts (spec §9.4).
- **Daily summary email** of `scout doctor` (spec §7.3) — only if silent
  failures become a real problem.
- **Social-platform ingestion** (X, Reddit, HN, YouTube) as new tool types
  (spec §1, explicit non-goal for v1).
- **Digest-quality evals** (LLM-as-judge, human grading) (spec §1).

## What I deliberately did *not* suggest

- A web UI. Spec is explicit that v1 is CLI + git + markdown, and that's the
  right call for the user's stated use case.
- A token/cost hard cap. Spec is explicit that wall-clock is the only hard
  limit. Adding a cap is plausible later but isn't worth the complexity now.
- Replacing `read_history` with a content-hash dedupe store. The spec's
  rationale (semantic judgment > URL matching) is correct, and the cost of
  state stays trivial.
