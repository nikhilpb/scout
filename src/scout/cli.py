from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from croniter import croniter

from scout.config import ConfigError, load_all_topics, load_topic
from scout.state import read_state


def _cmd_validate(args: argparse.Namespace) -> int:
    topics_dir = Path("topics")
    failures = 0
    total = 0
    for p in sorted(topics_dir.glob("*.yaml")):
        total += 1
        try:
            load_topic(p)
        except ConfigError as e:
            print(f"FAIL {p}: {e}", file=sys.stderr)
            failures += 1
    print(f"validated {total} topics, {failures} failures")
    return 0 if failures == 0 else 1


def _fmt(v) -> str:
    return "—" if v is None else str(v)


def _cmd_topics(args: argparse.Namespace) -> int:
    topics = load_all_topics(Path("topics"))
    state_dir = Path("state")
    rows = []
    for slug, loaded in topics.items():
        st = read_state(slug, state_dir)
        if st:
            last_run = st.last_run.isoformat()
            last_status = st.last_status
            try:
                cron = croniter(loaded.config.cadence, st.last_run)
                next_due = cron.get_next(datetime).isoformat()
            except Exception:
                next_due = "—"
        else:
            last_run = "—"
            last_status = "—"
            next_due = "now (no prior run)"
        rows.append((slug, loaded.config.cadence, last_run, last_status, next_due))
    header = ("slug", "cadence", "last_run", "last_status", "next_due")
    if rows:
        widths = [max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(header)]
    else:
        widths = [len(h) for h in header]

    def line(parts):
        return "  ".join(p.ljust(w) for p, w in zip(parts, widths))

    print(line(header))
    print(line(["-" * w for w in widths]))
    for r in rows:
        print(line(r))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scout", description="Personal news agent.")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("validate", help="schema-check all topic configs")
    sub.add_parser("topics", help="status table across topics")

    run_p = sub.add_parser("run", help="run a single topic now")
    run_p.add_argument("--topic", required=True)
    run_p.add_argument("--force", action="store_true")
    run_p.add_argument("--dry-run", action="store_true")

    args = parser.parse_args(argv)
    if args.command == "validate":
        return _cmd_validate(args)
    if args.command == "topics":
        return _cmd_topics(args)
    if args.command == "run":
        from scout.worker import run_topic
        return run_topic(args.topic, repo_dir=Path("."), force=args.force, dry_run=args.dry_run)
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
