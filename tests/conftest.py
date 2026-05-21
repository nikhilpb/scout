import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent))  # add repo root for `from tests.fakes...`

from scout.paths import DataPaths  # noqa: E402


def make_data_paths(root: Path) -> DataPaths:
    """Build a DataPaths over an arbitrary directory for tests.

    Bypasses DataPaths.resolve() so tests don't have to round-trip through
    env vars or CLI flags.
    """
    root = root.resolve()
    return DataPaths(
        root=root,
        topics_dir=root / "topics",
        output_dir=root / "output",
        state_dir=root / "state",
        logs_dir=root / "logs",
        config_path=root / "scout.toml",
    )
