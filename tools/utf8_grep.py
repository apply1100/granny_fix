from __future__ import annotations

import argparse
import re
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Search UTF-8 text files without relying on terminal codepages."
    )
    parser.add_argument("pattern", help="Regex pattern to search for")
    parser.add_argument(
        "paths",
        nargs="+",
        help="File or directory paths to search",
    )
    parser.add_argument(
        "--glob",
        default="*.py",
        help="Glob used when a directory path is provided",
    )
    parser.add_argument(
        "--ignore-case",
        action="store_true",
        help="Case-insensitive regex search",
    )
    return parser


def iter_files(paths: list[str], glob: str) -> list[Path]:
    files: list[Path] = []
    for raw_path in paths:
        path = Path(raw_path)
        if path.is_dir():
            files.extend(sorted(item for item in path.rglob(glob) if item.is_file()))
        elif path.is_file():
            files.append(path)
    return files


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    flags = re.IGNORECASE if args.ignore_case else 0
    pattern = re.compile(args.pattern, flags)
    matched = False

    for path in iter_files(args.paths, args.glob):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue

        for lineno, line in enumerate(lines, start=1):
            if pattern.search(line):
                matched = True
                print(f"{path}:{lineno}: {line}")

    return 0 if matched else 1


if __name__ == "__main__":
    raise SystemExit(main())
