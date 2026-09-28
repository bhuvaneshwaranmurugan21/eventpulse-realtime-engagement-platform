#!/usr/bin/env python3
"""Build exhaustive Part 2 Stage 2 acceptance traceability."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "part2/stage2/docs/traceability.json"


def mapping(number: int) -> dict[str, object]:
    identifier = f"P2S2-AC-{number:02d}"
    if number <= 7:
        artifacts = [
            "part2/stage2/docs/requirements.json",
            "part2/stage2/docs/audits/entry.md",
            "scripts/validate_part2_stage2.py",
        ]
        tests = ["scripts/validate_part2_stage2.py"]
    elif number <= 17:
        artifacts = [
            "src/eventpulse/local.py",
            "src/eventpulse/recovery.py",
            "scripts/run_part2_stage2_crash_matrix.py",
            "oracles/part2_stage2_recovery.py",
        ]
        tests = ["tests/test_part2_stage2_crash_matrix.py"]
    elif number <= 25:
        artifacts = [
            "fixtures/part2/stage2/crash-matrix.json",
            "fixtures/part2/stage2/golden-digests.json",
            "oracles/part2_stage2_recovery.py",
        ]
        tests = ["tests/test_part2_stage2_crash_matrix.py"]
    elif number <= 32:
        artifacts = [
            "src/eventpulse/recovery.py",
            "oracles/part2_stage2_recovery.py",
        ]
        tests = [
            "tests/test_part2_stage2_recovery.py",
            "tests/test_part2_stage2_negative_controls.py",
        ]
    else:
        artifacts = [
            ".github/workflows/part2-stage2-recovery.yml",
            "part2/stage2/docs/claims.json",
            "part2/stage2/docs/proof-matrix.json",
            "scripts/build_part2_stage2_manifest.py",
            "scripts/validate_part2_stage2.py",
        ]
        tests = [
            "tests/test_part2_stage2_negative_controls.py",
            "scripts/validate_part2_stage2.py",
        ]
    return {
        "artifacts": artifacts,
        "claim_level": "LOCAL_VERIFIED",
        "evidence": [
            "evidence/part2/stage2/crash-matrix.json",
            "evidence/part2/stage2/environment-reproducibility.json",
        ],
        "id": identifier,
        "tests": tests,
    }


def render() -> str:
    value = {
        "authority": "EP-FUTURE-P2-002",
        "claim_ceiling": "LOCAL_VERIFIED",
        "mappings": [mapping(number) for number in range(1, 37)],
        "project": "eventpulse-realtime-engagement-platform",
        "status": "IMPLEMENTED",
        "version": "1.0.0",
    }
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = render()
    if args.check:
        if not TARGET.exists() or TARGET.read_text(encoding="utf-8") != expected:
            raise SystemExit("Part 2 Stage 2 traceability is stale")
    else:
        TARGET.parent.mkdir(parents=True, exist_ok=True)
        TARGET.write_text(expected, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
