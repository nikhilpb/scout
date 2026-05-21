# Scout — Split code and data into separate repos

## 1. Purpose

Today the scout repo holds both the Python code and the data scout produces and consumes (topic configs, generated digests, run state, run logs). This conflates two things with different change cadences and audiences: the code is a developer-edited project, while the data is operational state for one (or more) deployments.

After this change:

- The **code repo** (`~/git/scout`) stays a pure Python project — source, tests, shipped prompt templates, docs.
- A new **data repo** (`~/git/scout-data`) holds the user-edited topic configs, the live `scout.toml`, the committed digests, and the (gitignored) per-machine run state and logs.

This split makes the code repo independent of any particular deployment, lets the user share or move the data repo (e.g., across machines) without dragging the code with it, and stops accumulating runtime state inside a Python package's source tree.

## 2. Scope

### In scope

- Move `topics/`, `output/`, `state/`, `logs/`, and `scout.toml` out of the code repo.
- Introduce a `DataPaths` value object that resolves once at the CLI entry point and is threaded through every consumer.
- A `--data-dir` flag on the root parser plus `$SCOUT_DATA_DIR` env var for runtime discovery; explicit error when neither is set.
- Update the cron documentation, `spec.md` (§2.2 and §3.2), and add a `docs/setup.md` covering bootstrap.
- Update tests to build `DataPaths` over `tmp_path` instead of treating `tmp_path` as a repo root.
- One-time bootstrap of the new data repo at `~/git/scout-data` (performed manually as part of cutover, not by a scout subcommand).

### Out of scope

- A `scout init` subcommand. Data repo bootstrap is manual and documented.
- Auto-cloning the data repo from a configured remote.
- Any backward-compat shim that auto-detects an "old layout" where data lives next to code. Clean cut: if no data dir is supplied, scout errors.
- Preserving git history of `topics/` or `output/` from the code repo. Current contents are placeholder `.gitkeep` files only; nothing material to migrate.
- Reworking the runner protocol, prompts, or any user-facing behavior beyond path resolution.

## 3. Repo layout after the split

### Code repo (`~/git/scout`)

```
scout/
├── pyproject.toml, uv.lock, .python-version
├── spec.md, AGENTS.md, CLAUDE.md, docs/
├── scout.toml.example          # template; not loaded at runtime
├── src/scout/                  # unchanged module layout + new paths.py
├── prompts/                    # shipped templates stay with code
├── tests/
└── .github/, .gitignore
```

Removed from the code repo:

- `topics/` (and its `.gitkeep`)
- `output/` (and its `.gitkeep`)
- `scout.toml` (renamed to `scout.toml.example`)
- `.gitignore` entries for `state/` and `logs/` (no longer expected here)

`prompts/` stays in the code repo because it ships with the code and is versioned alongside it.

### Data repo (`~/git/scout-data`)

```
scout-data/
├── scout.toml                  # the live config
├── topics/                     # user-edited YAMLs, committed
│   └── *.yaml
├── output/                     # digests, committed and pushed
│   └── <slug>/<YYYY-MM-DD>.md
├── state/                      # gitignored (per-machine)
├── logs/                       # gitignored
└── .gitignore                  # state/, logs/
```

Commit policy unchanged from today: only `output/` files are committed and pushed by `scout` itself. `topics/` and `scout.toml` are committed by the user when they edit them. `state/` and `logs/` are gitignored.

## 4. Runtime resolution

### Discovery order

At every CLI entry point, the data dir is resolved in this order:

1. The `--data-dir <path>` flag on the root parser, if present.
2. The `$SCOUT_DATA_DIR` environment variable.
3. Otherwise, exit with a clear error pointing at `docs/setup.md`.

There is no fallback to the current working directory. Explicit beats clever and keeps the code repo from being misinterpreted as a data repo if scout is invoked from inside it.

### `DataPaths` value object

A new module `src/scout/paths.py`:

```python
@dataclass(frozen=True)
class DataPaths:
    root: Path
    topics_dir: Path        # root / "topics"
    output_dir: Path        # root / "output"
    state_dir: Path         # root / "state"
    logs_dir: Path          # root / "logs"
    config_path: Path       # root / "scout.toml"

    @classmethod
    def resolve(cls, cli_arg: Optional[str]) -> "DataPaths":
        # cli_arg → $SCOUT_DATA_DIR → error.
        # Validates that the resolved path exists and is a directory.
        # Does NOT validate that subdirectories exist — callers create as needed
        # (matches today's `mkdir(parents=True, exist_ok=True)` behavior).
```

`DataPaths` is constructed exactly once per `scout` invocation, inside `cli.main`, and passed by reference to every consumer.

### CLI surface

Every existing subcommand (`tick`, `run`, `topics`, `validate`, `doctor`, `feedback`) accepts a top-level `--data-dir` registered on the root parser. Usage:

```
scout --data-dir ~/git/scout-data tick
SCOUT_DATA_DIR=~/git/scout-data scout tick
```

### Cron line

Documented in `docs/setup.md`:

```
*/15 * * * * SCOUT_DATA_DIR=/home/nikhil/git/scout-data cd /home/nikhil/git/scout && uv run scout tick
```

`cd` to the code repo so `uv run` finds the project; the data repo path is supplied via env.

## 5. Module-level changes

| Module | Change |
|---|---|
| `src/scout/paths.py` *(new)* | `DataPaths` dataclass and `DataPaths.resolve()`. |
| `src/scout/cli.py` | Add `--data-dir` to root parser. Build `DataPaths` once and pass it into every subcommand handler. Remove the literal `Path("topics")`, `Path("state")`, `Path("output")` references. |
| `src/scout/worker.py` | `run_topic(slug, *, data: DataPaths, force, dry_run)`. Drop `repo_dir`. `load_global_config(data.config_path)`. |
| `src/scout/orchestrator.py` | `tick(data: DataPaths)`. Spawn workers with `uv run scout --data-dir <data.root> run --topic <slug>` so children inherit the same root regardless of env. |
| `src/scout/git_publish.py` | `publish(*, data: DataPaths, file_path, slug, date_str, git_cfg)`. Git operations run with `cwd=data.root`. `.publish.lock` lives at `data.state_dir / ".publish.lock"`. |
| `src/scout/doctor.py` | `doctor(data: DataPaths)`. Reads `data.logs_dir`. |
| `src/scout/feedback.py` | No signature change (already takes `output_dir`); callers in `cli.py` pass `data.output_dir`. |
| `src/scout/config.py` | No signature change; call sites use `data.topics_dir` and `data.config_path`. |
| `src/scout/runner.py`, `runners/*` | No deeper change. The existing `Paths(output_dir, logs_dir)` is built from `DataPaths` at the worker boundary. |

`git_publish` previously used `repo_dir` to mean both "the directory that contains the file" and "the directory git operates on." After the split these are still the same path — the data repo — so the relative-path math (`file_path.relative_to(repo_dir)`) is unchanged in behavior, just with `data.root` substituted in.

## 6. Tests

Existing tests that build a synthetic repo layout under `tmp_path` are updated to:

- Build a `DataPaths` over `tmp_path` (helper added to `tests/conftest.py`, e.g. `make_data_paths(tmp_path) -> DataPaths`).
- Pass that into the consumer instead of `repo_dir=tmp_path`.

The full-pipeline integration test (`tests/test_full_pipeline.py`) already initializes a temp git repo for output. After the split, that temp repo is the *data* repo — no temp code repo is needed.

New test: `tests/test_paths_resolve.py` covers `DataPaths.resolve()` precedence (flag overrides env), the error case when neither is set, and the error case when the path does not exist or is not a directory.

## 7. Migration plan

### One PR, code-repo side

1. Add `src/scout/paths.py`.
2. Refactor every consumer per §5.
3. Add `--data-dir` to the root parser; wire env resolution.
4. Rename `scout.toml` → `scout.toml.example`.
5. Delete `topics/.gitkeep` and `output/.gitkeep`. Remove the `state/` and `logs/` lines from `.gitignore`.
6. Update tests per §6.
7. Update `spec.md` §2.2 (repo layout) and §3.2 (scout.toml location) to reflect the split.
8. Add `docs/setup.md` covering the bootstrap and cron line.

### Data repo bootstrap (one-time, outside the PR)

```
mkdir -p ~/git/scout-data/{topics,output,state,logs}
cd ~/git/scout-data
git init -b main
cp ~/git/scout/scout.toml ./scout.toml          # before step 4 above
printf "state/\nlogs/\n" > .gitignore
git add . && git commit -m "scout-data: initial layout"
# user creates GitHub remote and pushes
```

The current code repo's `topics/` and `output/` contain only `.gitkeep` placeholders — no user data to copy beyond `scout.toml`.

### Post-merge

The user updates the cron line per §4 ("Cron line").

## 8. Risks

- The cron update is the only step that can silently break a deployed setup. `docs/setup.md` calls it out as step 1 post-merge.
- A user running `scout` from inside the code repo without `$SCOUT_DATA_DIR` set will get an error instead of an accidental match. This is intended; the error message names both the flag and the env var.
- Two machines pointing at the same data repo will still each maintain their own `state/` and `logs/` (gitignored). The `.publish.lock` is per-data-repo, so cross-machine push races are mitigated only by git's own push/rebase logic, same as today.
