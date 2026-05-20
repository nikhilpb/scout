import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scout", description="Personal news agent.")
    parser.add_subparsers(dest="command")
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
