#!/usr/bin/env python3
"""Build the exhaustive Part 2 Stage 1 acceptance traceability registry."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "part2/stage1/docs/traceability.json"


def mapping(identifier: str) -> dict[str, object]:
    number = int(identifier.rsplit("-", 1)[1])
    if number <= 5:
        source = [
            "part2/stage1/docs/audits/completion.md",
            "part2/stage1/docs/audits/entry.md",
            "part2/stage1/docs/requirements.json",
            "part2/stage1/docs/status.md",
        ]
        tests = ["scripts/validate_part2_stage1.py"]
    elif number <= 10:
        source = ["part2/stage1/docs/decisions/calculability.md", "requirements/dev.lock"]
        tests = ["tests/test_part2_stage1_kernel.py", "tests/test_part2_stage1_aws_shapes.py"]
    elif number <= 18:
        source = ["src/eventpulse/admission.py", "src/eventpulse/semantics.py"]
        tests = ["tests/test_part2_stage1_kernel.py", "tests/test_part2_stage1_corpus.py"]
    elif number <= 25:
        source = ["src/eventpulse/handler.py", "src/eventpulse/local.py", "src/eventpulse/aws.py"]
        tests = ["tests/test_part2_stage1_handler.py", "tests/test_part2_stage1_aws_shapes.py"]
    else:
        source = [
            "scripts/validate_part2_stage1.py",
            ".github/workflows/part2-stage1-consumer.yml",
            "part2/stage1/docs/audits/completion.md",
            "part2/stage1/docs/claims.json",
            "part2/stage1/docs/proof-matrix.json",
        ]
        tests = [
            "tests/test_part2_stage1_corpus.py",
            "tests/test_part2_stage1_negative_controls.py",
        ]
    return {
        "artifacts": source,
        "claim_level": "LOCAL_VERIFIED" if number not in {22, 31, 32} else "DESIGN_ONLY",
        "evidence": ["evidence/part2/stage1/handler-result.json"],
        "id": identifier,
        "tests": tests,
    }


def render() -> str:
    value = {
        "authority": "EP-FUTURE-P2-001",
        "claim_ceiling": "LOCAL_VERIFIED",
        "mappings": [mapping(f"P2S1-AC-{number:02d}") for number in range(1, 33)],
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
            raise SystemExit("Part 2 Stage 1 traceability is stale")
    else:
        TARGET.parent.mkdir(parents=True, exist_ok=True)
        TARGET.write_text(expected, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
