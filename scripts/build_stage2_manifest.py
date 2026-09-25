"""Build the deterministic EventPulse Part 1 Stage 2 artifact manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "evidence/part1/stage2/manifest.json"
BASE_SHA = "cac96a23648be8512c5cab58774217169d7e5829"
BASE_TREE = "17bcfb451e52e4cdce7975b09de76e4848a29138"

ARTIFACTS = [
    ".github/workflows/stage2-contract.yml",
    "contracts/engagement-event-v1.schema.json",
    "contracts/event-semantics-v1.json",
    "contracts/recovery-protocol-v1.json",
    "contracts/semantic-examples-v1.json",
    "docs/INTERVIEW.md",
    "docs/STATUS.md",
    "docs/adr/0001-kinesis-lambda-consumer.md",
    "docs/architecture.md",
    "docs/audits/part1-stage2-decision-authority.md",
    "docs/claims.json",
    "docs/known-limits.md",
    "docs/operations-contract.md",
    "docs/proof-matrix.json",
    "docs/requirements/part1-stage2.json",
    "docs/security-and-lifecycle.md",
    "docs/threat-model.md",
    "scripts/build_stage2_manifest.py",
    "scripts/validate_stage2_contract.py",
    "tests/test_stage2_contract.py",
]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build() -> dict[str, object]:
    completion = ROOT / "docs/audits/part1-stage2-completion.md"
    paths = list(ARTIFACTS)
    status = "IN_REVIEW"
    if completion.exists():
        paths.append("docs/audits/part1-stage2-completion.md")
        status = "COMPLETED"
    artifacts = []
    for relative in sorted(paths):
        path = ROOT / relative
        artifacts.append(
            {"path": relative, "sha256": digest(path), "size_bytes": path.stat().st_size}
        )
    return {
        "project": "eventpulse-realtime-engagement-platform",
        "stage": "PART1_STAGE2_COMPLETION_CONTRACT",
        "status": status,
        "contract_version": "1.0.0",
        "source": {"base_sha": BASE_SHA, "base_tree": BASE_TREE, "region": "ap-south-2"},
        "claim_boundary": {
            "design": "DESIGN_ONLY",
            "document_validation": "LOCAL_VERIFIED",
            "aws_streaming": "UNCLAIMED",
            "measured_performance": "UNCLAIMED",
        },
        "artifacts": artifacts,
    }


def rendered() -> str:
    return json.dumps(build(), indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = rendered()
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != expected:
            raise SystemExit("Stage 2 manifest is missing or stale; rebuild it")
        print("Stage 2 artifact manifest: current")
    else:
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(expected, encoding="utf-8")
        print(f"wrote {OUTPUT.relative_to(ROOT)}")
