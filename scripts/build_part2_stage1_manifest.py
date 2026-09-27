#!/usr/bin/env python3
"""Build or check the deterministic Part 2 Stage 1 artifact manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "evidence/part2/stage1/manifest.json"
EXACT_PATHS = {
    ".github/workflows/part2-stage1-consumer.yml",
    "part2/stage1/docs/audits/completion.md",
    "part2/stage1/docs/audits/entry.md",
    "part2/stage1/docs/decisions/calculability.md",
    "part2/stage1/docs/INTERVIEW.md",
    "part2/stage1/docs/known-limits.md",
    "part2/stage1/docs/claims.json",
    "part2/stage1/docs/proof-matrix.json",
    "part2/stage1/docs/status.md",
    "part2/stage1/docs/requirements.json",
    "part2/stage1/docs/traceability.json",
    "evidence/part2/stage1/handler-result.json",
    "evidence/part2/stage1/package-inventory.json",
    "pyproject.toml",
    "scripts/build_lambda_package.py",
    "scripts/build_part2_stage1_evidence.py",
    "scripts/build_part2_stage1_manifest.py",
    "scripts/build_part2_stage1_traceability.py",
    "scripts/render_wheel_lock.py",
    "scripts/run_part2_stage1_local.py",
    "scripts/validate_part2_stage1.py",
    "tests/part2_stage1_helpers.py",
}
DIRECTORIES = (
    "fixtures/part2/stage1/",
    "requirements/",
    "src/eventpulse/",
)
FILE_PREFIXES = (
    "tests/test_part2_stage1_",
)


def included(path: Path) -> bool:
    relative = str(path.relative_to(ROOT))
    return (
        path.is_file()
        and path != TARGET
        and "__pycache__" not in path.parts
        and path.suffix != ".pyc"
        and (
            relative in EXACT_PATHS
            or any(relative.startswith(prefix) for prefix in DIRECTORIES)
            or any(relative.startswith(prefix) for prefix in FILE_PREFIXES)
        )
    )


def render() -> str:
    artifacts = []
    for path in sorted(path for path in ROOT.rglob("*") if included(path)):
        body = path.read_bytes()
        artifacts.append(
            {
                "path": str(path.relative_to(ROOT)),
                "sha256": hashlib.sha256(body).hexdigest(),
                "size_bytes": len(body),
            }
        )
    value = {
        "artifacts": artifacts,
        "claim_ceiling": "LOCAL_VERIFIED",
        "project": "eventpulse-realtime-engagement-platform",
        "stage": "part2-stage1",
    }
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = render()
    if args.check:
        if not TARGET.exists() or TARGET.read_text(encoding="utf-8") != expected:
            raise SystemExit("Part 2 Stage 1 manifest is stale")
    else:
        TARGET.parent.mkdir(parents=True, exist_ok=True)
        TARGET.write_text(expected, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
