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

    sub.add_parser("tick", help="orchestrator (run from cron)")
    sub.add_parser("doctor", help="health summary across last 7 days")

    fb = sub.add_parser("feedback", help="capture or report feedback")
    fb_sub = fb.add_subparsers(dest="fb_cmd", required=True)
    fb_list = fb_sub.add_parser("list")
    fb_list.add_argument("--topic")
    fb_list.add_argument("--since", help="ignored in v1; reserved for future filtering")
    fb_add = fb_sub.add_parser("add")
    fb_add.add_argument("--topic", required=True)
    fb_add.add_argument("--date")
    fb_add.add_argument("--rating", type=int)
    fb_add.add_argument("--notes")

    args = parser.parse_args(argv)
    if args.command == "validate":
        return _cmd_validate(args)
    if args.command == "topics":
        return _cmd_topics(args)
    if args.command == "run":
        from scout.worker import run_topic
        return run_topic(args.topic, repo_dir=Path("."), force=args.force, dry_run=args.dry_run)
    if args.command == "tick":
        from scout.orchestrator import tick
        return tick(Path("."))
    if args.command == "doctor":
        from scout.doctor import doctor
        return doctor(Path("."))
    if args.command == "feedback":
        from scout.feedback import append_block, find_latest, parse_blocks
        output_dir = Path("output")
        if args.fb_cmd == "list":
            if output_dir.exists():
                for topic_dir in sorted(output_dir.iterdir()):
                    if not topic_dir.is_dir():
                        continue
                    if args.topic and topic_dir.name != args.topic:
                        continue
                    for f in sorted(topic_dir.glob("*.md")):
                        blocks, _ = parse_blocks(f.read_text())
                        for b in blocks:
                            print(f"{topic_dir.name}/{f.name}: {b}")
            return 0
        if args.fb_cmd == "add":
            if args.date:
                target = output_dir / args.topic / f"{args.date}.md"
                if not target.exists():
                    print(f"no digest at {target}", file=sys.stderr)
                    return 1
            else:
                target = find_latest(args.topic, output_dir)
                if target is None:
                    print(f"no digests for {args.topic}", file=sys.stderr)
                    return 1
            data = {}
            if args.rating is not None:
                data["rating"] = args.rating
            if args.notes:
                data["notes"] = args.notes
            append_block(target, data)
            print(f"appended feedback to {target}")
            return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
