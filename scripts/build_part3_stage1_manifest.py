#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "evidence/part3/stage1/manifest.json"
PREFIXES = (
    ".github/workflows/part3-stage1-",
    "evidence/part3/stage1/",
    "part3/stage1/",
    "scripts/build_part3_stage1_",
    "scripts/eventpulse_part3_stage1_",
    "scripts/validate_part3_stage1.py",
    "tests/test_part3_stage1_",
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
    payload = {
        "authority": "EP-FUTURE-P3-001",
        "claim_ceiling": "LOCAL_VERIFIED_PENDING_AWS_OBSERVATION",
        "predecessor_commit": "75923c9c272d940ed2a6f90de1e2492a1269a3ea",
        "predecessor_tree": "00bf6480d299461cb879d528a0bff6ba8c8dc191",
        "artifacts": rows,
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    body = render()
    if args.check:
        if not TARGET.exists() or TARGET.read_text() != body:
            raise SystemExit("stale Stage 1 manifest")
    else:
        TARGET.parent.mkdir(parents=True, exist_ok=True)
        TARGET.write_text(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
