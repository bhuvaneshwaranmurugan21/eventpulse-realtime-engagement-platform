#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "part2/stage3/docs/traceability.json"


def render() -> str:
    criteria = json.loads((ROOT / "part2/stage3/docs/requirements.json").read_text())["criteria"]
    mappings = [
        {
            "id": item,
            "artifacts": ["part2/stage3/docs/requirements.json"],
            "evidence": ["evidence/part2/stage3/critical-coverage.json"],
            "tests": [
                "tests/test_part2_stage3_properties.py",
                "tests/test_part2_stage3_mutations.py",
            ],
        }
        for item in criteria
    ]
    return (
        json.dumps(
            {"authority": "EP-FUTURE-P2-003", "mappings": mappings}, indent=2, sort_keys=True
        )
        + "\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    body = render()
    if args.check:
        if not TARGET.exists() or TARGET.read_text() != body:
            raise SystemExit("stale traceability")
    else:
        TARGET.write_text(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
