#!/usr/bin/env python3
"""Stream-decompress a Zstandard JSON snapshot without requiring frame size metadata."""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path



def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Path to the .json.zst file")
    parser.add_argument("output", type=Path, help="Destination path for unpacked JSON")
    args = parser.parse_args()

    if not args.input.is_file():
        parser.error(f"input file not found: {args.input}")
    try:
        import zstandard
    except ImportError:
        parser.error("zstandard is required; install project dependencies with: python -m pip install -e .")
    args.output.parent.mkdir(parents=True, exist_ok=True)

    with args.input.open("rb") as source, zstandard.ZstdDecompressor().stream_reader(source) as reader:
        with args.output.open("wb") as destination:
            shutil.copyfileobj(reader, destination)

    print(f"Decompressed {args.input} -> {args.output} ({args.output.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
