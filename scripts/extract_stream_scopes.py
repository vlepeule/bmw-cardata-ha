#!/usr/bin/env python3
"""Extract streaming descriptors from the CarData catalogue file."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Iterable

ZERO_WIDTH = "\u200b"
DEFAULT_PREFIX = "cardata:streaming:"


def extract_descriptors(text: str) -> Iterable[str]:
    pattern = re.compile(r"vehicle[\w\.\u200b]+", re.UNICODE)
    seen = set()
    for match in pattern.findall(text):
        cleaned = match.replace(ZERO_WIDTH, "")
        if cleaned not in seen:
            seen.add(cleaned)
            yield cleaned


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate streaming scopes from catalogue")
    parser.add_argument("catalogue", default="catalogue", nargs="?", help="Path to catalogue file")
    parser.add_argument("--prefix", default=DEFAULT_PREFIX, help="Scope prefix (default cardata:streaming:)")
    parser.add_argument("--output", help="Optional output file; writes to stdout if omitted")
    args = parser.parse_args()

    text = Path(args.catalogue).read_text(encoding="utf-8")
    descriptors = list(extract_descriptors(text))
    scopes = [args.prefix + d for d in descriptors]

    output_lines = [
        "# Generated streaming scopes",
        f"# Total: {len(scopes)}",
        *scopes,
    ]
    output_text = "\n".join(output_lines) + "\n"

    if args.output:
        Path(args.output).write_text(output_text, encoding="utf-8")
        print(f"Wrote {len(scopes)} scopes to {args.output}")
    else:
        print(output_text)


if __name__ == "__main__":
    main()
