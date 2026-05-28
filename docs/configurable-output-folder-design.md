# Configurable output folder

## Problem

Scout resolves a single data directory (`--data-dir` / `$SCOUT_DATA_DIR`) and
derives every working subdirectory from it, including the output folder at
`<data-dir>/output`. There is no way to write digests anywhere else. Now that
the git-publish step has been removed, the output folder is just a write
location with no requirement to live inside the data repo, so it can be made
independently configurable.

## Goal

Let the output folder be configured independently of the data directory, via a
CLI flag and an environment variable. When unset, it defaults to
`<data-dir>/output` so existing setups continue to work unchanged.

## Non-goals

- Configuring the output folder through `scout.toml`.
- Relocating `topics/`, `state/`, `logs/`, or `scout.toml` out of the data dir.
- Restoring or changing any git-publish behavior (already removed).

## Design

### Resolution (`src/scout/paths.py`)

`DataPaths.resolve()` gains a second optional argument:

```python
resolve(cls, data_dir_arg: Optional[str], output_dir_arg: Optional[str] = None)
```

Output folder precedence (highest first):

1. `output_dir_arg` (the `--output-dir` CLI flag)
2. `$SCOUT_OUTPUT_DIR`
3. default: `root / "output"`

An empty-string flag is treated as unset (matching the existing `--data-dir`
behavior). When a custom value is provided, it is `expanduser().resolve()`-d, so
relative paths resolve against the current working directory and the folder may
live anywhere — including outside the data directory. If the custom path exists
but is not a directory, raise `DataPathsError`. The folder is **not** required
to pre-exist: the digest writer (`output.pick_output_path`) already calls
`mkdir(parents=True, exist_ok=True)` on the per-topic subfolder.

All other paths (`topics_dir`, `state_dir`, `logs_dir`, `config_path`) remain
derived from `root` and are unchanged.

### CLI surface (`src/scout/cli.py`)

Add a top-level `--output-dir` argument alongside `--data-dir`:

- `dest="output_dir"`, `default=None`
- help text references `$SCOUT_OUTPUT_DIR` and the `<data-dir>/output` default

Pass it through: `DataPaths.resolve(args.data_dir, args.output_dir)`.

### Subprocess propagation (`src/scout/orchestrator.py`)

`_spawn_run` builds a `scout run` subprocess command and currently forwards only
`--data-dir`. Add `--output-dir str(data.output_dir)` so a custom output folder
reaches child workers. `data.output_dir` is always set and absolute (custom or
default), so forwarding it unconditionally is safe and explicit.

## Data flow

```
CLI args / env
   │  (--output-dir | $SCOUT_OUTPUT_DIR | default root/output)
   ▼
DataPaths.resolve() ── output_dir ──▶ DataPaths.output_dir
   │                                        │
   ├─ worker.run_topic ──▶ Paths(output_dir=data.output_dir, …) ──▶ runner writes digest
   ├─ orchestrator.tick ──▶ _spawn_run forwards --output-dir to child `scout run`
   └─ cli feedback (list/add) ──▶ reads from data.output_dir
```

## Error handling

- Custom output path exists but is not a directory → `DataPathsError`
  (`"output path is not a directory: <path>"`).
- Missing output folder is not an error; it is created on demand by the writer.
- Data-dir resolution and its existing errors are unchanged.

## Testing

Extend `tests/unit/test_paths_resolve.py`:

- `--output-dir` flag overrides `$SCOUT_OUTPUT_DIR`.
- `$SCOUT_OUTPUT_DIR` is used when no flag is given.
- Output dir defaults to `root / "output"` when neither is set.
- `~` expansion works for a custom output dir.
- Empty-string output flag is treated as unset.
- Custom output path that is a file raises `DataPathsError`.
- A custom output dir need not pre-exist (resolve succeeds).

Add a test that `orchestrator._spawn_run` includes `--output-dir <resolved>` in
the spawned command (e.g. by patching `subprocess.run` and asserting on argv).

## Documentation

- `README.md`: document `--output-dir` / `$SCOUT_OUTPUT_DIR` and the
  `<data-dir>/output` default where the data-dir / output layout is described.
- `docs/setup.md`: mention the option where relevant.
- `scout.toml.example`: unchanged (output config is flag/env only).
