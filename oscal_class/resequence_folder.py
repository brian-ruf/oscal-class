#!/usr/bin/env python3
"""
oscal_resequence_batch.py

Batch-resequences all OSCAL JSON and YAML files in a source folder,
writing ordered output to a destination folder with the same filenames.

Usage:
    python oscal_resequence_batch.py <source_folder> <destination_folder>

Arguments:
    source_folder       Directory containing *.json and/or *.yaml files.
    destination_folder  Directory where resequenced files will be written.
                        Created automatically if it does not exist.
"""

import sys
from pathlib import Path

from oscal_resequence import resequence_oscal_file


def batch_resequence(source_dir: str | Path, dest_dir: str | Path) -> None:
    source_dir = Path(source_dir)
    dest_dir = Path(dest_dir)

    if not source_dir.is_dir():
        print(f"Error: source folder does not exist or is not a directory: {source_dir}",
              file=sys.stderr)
        sys.exit(1)

    dest_dir.mkdir(parents=True, exist_ok=True)

    candidates = sorted(
        list(source_dir.glob("*.json")) + list(source_dir.glob("*.yaml"))
    )

    if not candidates:
        print(f"No *.json or *.yaml files found in: {source_dir}")
        return

    ok = failed = 0
    for src in candidates:
        dest = dest_dir / src.name
        try:
            resequence_oscal_file(src, dest)
            print(f"  ✓  {src.name}")
            ok += 1
        except Exception as exc:
            print(f"  ✗  {src.name}  —  {exc}", file=sys.stderr)
            failed += 1

    total = ok + failed
    print(f"\n{ok}/{total} files resequenced successfully", end="")
    print(f" — {failed} error(s)" if failed else "")
    if ok:
        print(f"Output written to: {dest_dir.resolve()}")


def main() -> None:
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)

    batch_resequence(sys.argv[1], sys.argv[2])


if __name__ == "__main__":
    main()
