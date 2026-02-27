"""
docrawler utils — CLI tools for managing crawl state files.

Commands
--------
  dedup     Remove duplicate URLs from a link file
  subtract  Remove already-visited URLs from a queue file
  merge     Combine multiple link files into one (deduplicated)

Usage examples
--------------
  python utils.py dedup queue.txt
  python utils.py subtract queue.txt visited.txt
  python utils.py merge part1.txt part2.txt part3.txt -o queue.txt
"""

import argparse
import os


def load(filepath: str) -> set:
    with open(filepath, encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}


def write(links: set, filepath: str) -> None:
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(sorted(links)))


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_dedup(args: argparse.Namespace) -> None:
    """Remove duplicate URLs from a file in-place (or to a new file)."""
    links = load(args.file)
    output = args.output or args.file
    write(links, output)
    print(f"{len(links):,} unique URLs → {output}")


def cmd_subtract(args: argparse.Namespace) -> None:
    """Remove visited URLs from a queue file."""
    queue = load(args.queue)
    visited = load(args.visited)
    remaining = queue - visited
    output = args.output or args.queue
    write(remaining, output)
    removed = len(queue) - len(remaining)
    print(f"Removed {removed:,} visited URLs. {len(remaining):,} remaining → {output}")


def cmd_merge(args: argparse.Namespace) -> None:
    """Merge multiple link files into one deduplicated file."""
    combined = set()
    for filepath in args.files:
        if not os.path.exists(filepath):
            print(f"Warning: {filepath} not found, skipping.")
            continue
        combined.update(load(filepath))
    write(combined, args.output)
    print(f"Merged {len(args.files)} file(s): {len(combined):,} unique URLs → {args.output}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="utils",
        description="Utilities for managing docrawler state files.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # dedup
    p_dedup = subparsers.add_parser("dedup", help="Remove duplicate URLs from a file")
    p_dedup.add_argument("file", help="Link file to deduplicate")
    p_dedup.add_argument("-o", "--output", metavar="FILE", help="Output file (default: overwrite input)")
    p_dedup.set_defaults(func=cmd_dedup)

    # subtract
    p_sub = subparsers.add_parser("subtract", help="Remove visited URLs from a queue file")
    p_sub.add_argument("queue", help="Queue file to filter")
    p_sub.add_argument("visited", help="Visited URLs file")
    p_sub.add_argument("-o", "--output", metavar="FILE", help="Output file (default: overwrite queue)")
    p_sub.set_defaults(func=cmd_subtract)

    # merge
    p_merge = subparsers.add_parser("merge", help="Merge multiple link files into one")
    p_merge.add_argument("files", nargs="+", metavar="FILE", help="Files to merge")
    p_merge.add_argument("-o", "--output", required=True, metavar="FILE", help="Output file")
    p_merge.set_defaults(func=cmd_merge)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
