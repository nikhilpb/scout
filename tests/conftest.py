import json
import sys
from functools import lru_cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent))  # add repo root for `from tests.fakes...`

from scout.paths import DataPaths  # noqa: E402

_REPO_ROOT = Path(__file__).parent.parent
_SCHEMA_PATH = _REPO_ROOT / "docs" / "trajectory.schema.json"


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
        trajectories_dir=root / "trajectories",
        config_path=root / "scout.toml",
    )


@lru_cache
def _traj_validator():
    from jsonschema import Draft202012Validator

    return Draft202012Validator(json.loads(_SCHEMA_PATH.read_text()))


def read_trajectory(path: Path) -> list[dict]:
    """Parse a trajectory JSONL file, asserting every record matches the schema."""
    records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    validator = _traj_validator()
    for rec in records:
        errors = sorted(validator.iter_errors(rec), key=lambda e: list(e.path))
        assert not errors, (
            f"schema violation in {rec.get('type')!r} record: {errors[0].message}"
        )
    return records


def only_trajectory(trajectories_dir: Path, slug: str) -> list[dict]:
    """Read the single trajectory written for ``slug`` (schema-validated)."""
    files = list((trajectories_dir / slug).glob("*.jsonl"))
    assert len(files) == 1, f"expected one trajectory, found {files}"
    return read_trajectory(files[0])
