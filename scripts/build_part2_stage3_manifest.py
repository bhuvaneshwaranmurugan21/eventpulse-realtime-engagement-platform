#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "evidence/part2/stage3/manifest.json"
PREFIXES = (
    ".github/workflows/part2-stage3-",
    "evidence/part2/stage3/",
    "fixtures/part2/stage3/",
    "part2/stage3/",
    "scripts/build_part2_stage3_",
    "scripts/run_part2_stage3_",
    "scripts/validate_part2_stage3.py",
    "tests/test_part2_stage3_",
)


def render() -> str:
    rows = []
    for path in sorted(ROOT.rglob("*")):
        relative = path.relative_to(ROOT).as_posix()
        if (
            path.is_file()
            and path != TARGET
            and "__pycache__" not in path.parts
            and relative.startswith(PREFIXES)
        ):
            body = path.read_bytes()
            rows.append(
                {
                    "path": relative,
                    "sha256": hashlib.sha256(body).hexdigest(),
                    "size_bytes": len(body),
                }
            )
    return (
        json.dumps(
            {"authority": "EP-FUTURE-P2-003", "claim_ceiling": "LOCAL_VERIFIED", "artifacts": rows},
            indent=2,
            sort_keys=True,
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
            raise SystemExit("stale manifest")
    else:
        TARGET.parent.mkdir(parents=True, exist_ok=True)
        TARGET.write_text(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
