#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "part3/stage1/docs/traceability.json"


def render() -> str:
    requirements = json.loads((ROOT / "part3/stage1/docs/requirements.json").read_text())
    mappings = []
    for criterion in requirements["criteria"]:
        mappings.append(
            {
                "criterion": criterion,
                "failure_mode": "missing, stale, contradictory or unverified evidence",
                "proof": [
                    "scripts/validate_part3_stage1.py",
                    "tests/test_part3_stage1_admission.py",
                ],
                "result": "PENDING"
                if criterion
                in {
                    "EXACT_HEAD_CI",
                    "GUARDED_MERGE",
                    "MERGED_MAIN_CI",
                    "SEPARATE_RECEIPT",
                    "STAGE2_CHECKPOINT",
                }
                else "IMPLEMENTED",
            }
        )
    return (
        json.dumps(
            {"authority": "EP-FUTURE-P3-001", "mappings": mappings}, indent=2, sort_keys=True
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
            raise SystemExit("stale Stage 1 traceability")
    else:
        TARGET.parent.mkdir(parents=True, exist_ok=True)
        TARGET.write_text(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
