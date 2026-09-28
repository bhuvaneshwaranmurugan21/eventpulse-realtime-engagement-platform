#!/usr/bin/env python3
"""Build or check the Stage 2 self-contained Lambda package inventory."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from build_lambda_package import build

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "evidence/part2/stage2/package-inventory.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("wheelhouse", type=Path)
    parser.add_argument("output_zip", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = json.dumps(build(args.wheelhouse, args.output_zip), indent=2, sort_keys=True) + "\n"
    if args.check:
        if not TARGET.exists() or TARGET.read_text(encoding="utf-8") != rendered:
            raise SystemExit("Part 2 Stage 2 Lambda package inventory is stale")
    else:
        TARGET.parent.mkdir(parents=True, exist_ok=True)
        TARGET.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
