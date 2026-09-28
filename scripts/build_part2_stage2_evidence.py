#!/usr/bin/env python3
"""Build or check deterministic Part 2 Stage 2 crash evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "oracles"))
sys.path.insert(0, str(ROOT / "scripts"))

from run_part2_stage2_crash_matrix import supervise  # noqa: E402

from eventpulse.canonical import canonical_bytes  # noqa: E402

TARGET = ROOT / "evidence/part2/stage2/crash-matrix.json"


def render() -> str:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        first = supervise(root / "run-a")
        second = supervise(root / "run-b")
    if canonical_bytes(first) != canonical_bytes(second):
        raise AssertionError("Stage 2 crash evidence is nondeterministic")
    value = {
        "authority": "EP-FUTURE-P2-002",
        "claim_ceiling": "LOCAL_VERIFIED",
        "environment": {
            "LC_ALL": "C.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONHASHSEED": "0",
            "TZ": "UTC",
            "python": "3.12",
        },
        "matrix": first,
        "matrix_sha256": hashlib.sha256(canonical_bytes(first)).hexdigest(),
        "network_calls": 0,
        "runs_compared": 2,
        "status": "PASS",
    }
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = render()
    if args.check:
        if not TARGET.exists() or TARGET.read_text(encoding="utf-8") != expected:
            raise SystemExit("Part 2 Stage 2 crash evidence is stale")
    else:
        TARGET.parent.mkdir(parents=True, exist_ok=True)
        TARGET.write_text(expected, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
