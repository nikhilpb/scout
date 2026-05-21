from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

import yaml

log = logging.getLogger("scout.feedback")

BLOCK_RE = re.compile(r"<!--\s*scout-feedback\s*\n(.*?)\n-->", re.DOTALL)


def parse_blocks(markdown: str) -> tuple[list[dict], int]:
    blocks: list[dict] = []
    errors = 0
    for m in BLOCK_RE.finditer(markdown):
        body = m.group(1)
        try:
            data = yaml.safe_load(body) or {}
            if not isinstance(data, dict):
                errors += 1
                continue
            blocks.append(data)
        except yaml.YAMLError as e:
            log.warning("malformed feedback block: %s", e)
            errors += 1
    return blocks, errors


def append_block(path: Path, data: dict) -> None:
    body = yaml.safe_dump(data, sort_keys=False).strip()
    block = f"\n\n<!-- scout-feedback\n{body}\n-->\n"
    path.write_text(path.read_text().rstrip() + block)


def find_latest(slug: str, output_dir: Path) -> Optional[Path]:
    d = output_dir / slug
    if not d.exists():
        return None
    files = sorted(d.glob("*.md"), reverse=True)
    return files[0] if files else None
