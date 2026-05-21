from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


class DataPathsError(Exception):
    pass


@dataclass(frozen=True)
class DataPaths:
    root: Path
    topics_dir: Path
    output_dir: Path
    state_dir: Path
    logs_dir: Path
    config_path: Path

    @classmethod
    def resolve(cls, cli_arg: Optional[str]) -> "DataPaths":
        raw = cli_arg if cli_arg else os.environ.get("SCOUT_DATA_DIR")
        if not raw:
            raise DataPathsError(
                "no data directory configured: "
                "set $SCOUT_DATA_DIR or pass --data-dir"
            )
        root = Path(raw).expanduser()
        if not root.exists():
            raise DataPathsError(f"data directory does not exist: {root}")
        if not root.is_dir():
            raise DataPathsError(f"data path is not a directory: {root}")
        root = root.resolve()
        return cls(
            root=root,
            topics_dir=root / "topics",
            output_dir=root / "output",
            state_dir=root / "state",
            logs_dir=root / "logs",
            config_path=root / "scout.toml",
        )
