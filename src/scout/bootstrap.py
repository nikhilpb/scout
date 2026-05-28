from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

# Kept in sync with scout.toml.example (see test_default_scout_toml_matches_example).
# Embedded rather than read at runtime so `scout init` works whether scout is run
# from source or installed (the example file is not shipped in the wheel).
DEFAULT_SCOUT_TOML = """\
[defaults]
runner = "builtin"
model  = "anthropic/claude-sonnet-4-6"
timeout_seconds = 300

[scheduler]
max_concurrent_workers = 3

[llm]
# LiteLLM credentials read from env vars by convention;
# this section is reserved for future overrides.
"""

GITIGNORE_BODY = "state/\nlogs/\n"

_SUBDIRS = ("topics", "output", "state", "logs")
# state/ and logs/ are gitignored, so .gitkeep only helps the committed dirs.
_GITKEEP_DIRS = ("topics", "output")


class BootstrapError(Exception):
    pass


def resolve_init_root(positional: Optional[str], data_dir_flag: Optional[str]) -> Path:
    """Resolve the target data-repo root for `scout init`.

    Precedence: positional arg > --data-dir flag > $SCOUT_DATA_DIR. Unlike
    DataPaths.resolve(), the path is NOT required to exist yet.
    """
    raw = positional or data_dir_flag or os.environ.get("SCOUT_DATA_DIR")
    if not raw:
        raise BootstrapError(
            "no data directory given: pass a path, --data-dir, or set $SCOUT_DATA_DIR"
        )
    return Path(raw).expanduser()


def init_data_repo(root: Path) -> Path:
    """Scaffold an empty data repo at `root` (files only; no git).

    Refuses to touch a directory that already contains scout.toml. Returns the
    resolved root.
    """
    config_path = root / "scout.toml"
    if config_path.exists():
        raise BootstrapError(f"already a scout data repo (scout.toml exists): {root}")

    root.mkdir(parents=True, exist_ok=True)
    for name in _SUBDIRS:
        (root / name).mkdir(parents=True, exist_ok=True)

    config_path.write_text(DEFAULT_SCOUT_TOML)

    gitignore = root / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(GITIGNORE_BODY)

    for name in _GITKEEP_DIRS:
        keep = root / name / ".gitkeep"
        if not keep.exists():
            keep.write_text("")

    return root.resolve()
