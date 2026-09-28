#!/usr/bin/env python3
"""Build or check the deterministic Part 2 Stage 2 artifact manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "evidence/part2/stage2/manifest.json"
EXACT_PATHS = {
    ".github/workflows/part2-stage2-recovery.yml",
    "oracles/part2_stage2_recovery.py",
    "scripts/build_part2_stage2_evidence.py",
    "scripts/build_part2_stage2_manifest.py",
    "scripts/build_part2_stage2_package.py",
    "scripts/build_part2_stage2_traceability.py",
    "scripts/compare_part2_stage2_environments.py",
    "scripts/run_part2_stage2_crash_matrix.py",
    "scripts/validate_part2_stage2.py",
    "src/eventpulse/aws.py",
    "src/eventpulse/handler.py",
    "src/eventpulse/local.py",
    "src/eventpulse/ports.py",
    "src/eventpulse/recovery.py",
    "evidence/part2/stage2/crash-matrix.json",
    "evidence/part2/stage2/environment-reproducibility.json",
    "evidence/part2/stage2/package-inventory.json",
}
PREFIXES = (
    "fixtures/part2/stage2/",
    "part2/stage2/docs/",
    "tests/test_part2_stage2_",
)


def included(path: Path) -> bool:
    relative = path.relative_to(ROOT).as_posix()
    return (
        path.is_file()
        and path != TARGET
        and "__pycache__" not in path.parts
        and path.suffix != ".pyc"
        and (relative in EXACT_PATHS or any(relative.startswith(prefix) for prefix in PREFIXES))
    )


def render() -> str:
    artifacts = []
    for path in sorted(path for path in ROOT.rglob("*") if included(path)):
        body = path.read_bytes()
        artifacts.append(
            {
                "path": path.relative_to(ROOT).as_posix(),
                "sha256": hashlib.sha256(body).hexdigest(),
                "size_bytes": len(body),
            }
        )
    value = {
        "artifacts": artifacts,
        "authority": "EP-FUTURE-P2-002",
        "claim_ceiling": "LOCAL_VERIFIED",
        "project": "eventpulse-realtime-engagement-platform",
        "stage": "part2-stage2",
    }
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = render()
    if args.check:
        if not TARGET.exists() or TARGET.read_text(encoding="utf-8") != expected:
            raise SystemExit("Part 2 Stage 2 manifest is stale")
    else:
        TARGET.parent.mkdir(parents=True, exist_ok=True)
        TARGET.write_text(expected, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
