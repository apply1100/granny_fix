from __future__ import annotations

import argparse
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read a text file as UTF-8 and print selected lines."
    )
    parser.add_argument("path", help="File path to read")
    parser.add_argument("--start", type=int, default=1, help="1-based start line")
    parser.add_argument("--end", type=int, help="1-based end line (inclusive)")
    parser.add_argument("--number", action="store_true", help="Show line numbers")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    path = Path(args.path)
    lines = path.read_text(encoding="utf-8").splitlines()
    start = max(args.start, 1)
    end = args.end if args.end is not None else len(lines)
    end = min(max(end, start), len(lines))

    for lineno in range(start, end + 1):
        text = lines[lineno - 1]
        if args.number:
            print(f"{lineno:04d}: {text}")
        else:
            print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
