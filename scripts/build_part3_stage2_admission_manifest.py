#!/usr/bin/env python3
"""Build the deterministic Stage 2 admission authority manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "evidence/part3/stage2/admission-manifest.json"
PREFIXES = (
    ".github/workflows/part3-stage2-admission-requalification.yml",
    "evidence/part3/stage2/",
    "part3/stage2/admission/",
    "scripts/build_part3_stage2_admission_manifest.py",
    "scripts/collect_part3_stage2_admission.py",
    "scripts/validate_part3_stage2_admission.py",
    "tests/test_part3_stage2_admission.py",
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
        "artifacts": rows,
        "authority": "EP-FUTURE-P3-002-ENTRY",
        "claim_ceiling": "DESIGN_ONLY",
        "predecessor_main": "8108f789b8333b0856470d465c871ab6b6d41130",
        "predecessor_tree": "9f1d38410a0bb92ebdcb86f0ee088fc8ae1f981c",
        "status": "IMPLEMENTED_PENDING_FRESH_OBSERVATION",
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = render()
    if args.check:
        if not TARGET.exists() or TARGET.read_text(encoding="utf-8") != rendered:
            raise SystemExit("stale Stage 2 admission manifest")
    else:
        TARGET.parent.mkdir(parents=True, exist_ok=True)
        TARGET.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
