"""Build deterministic EventPulse Part 1 Stage 3 oracle evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from oracles.eventpulse_reference import canonical_bytes, evaluate_corpus  # noqa: E402


OUTPUT = ROOT / "evidence/part1/stage3/manifest.json"
ORACLE_OUTPUT = ROOT / "evidence/part1/stage3/oracle-results.json"
BASE_SHA = "9394d1795d3e4e9622e4f580aef61be455f6ce4b"
BASE_TREE = "ad4077ea62bcae275030a7c389d5a0538a07d6fc"

ARTIFACTS = [
    ".github/workflows/stage3-oracles.yml",
    "contracts/stage3-oracle-spec-v1.json",
    "docs/INTERVIEW.md",
    "docs/STATUS.md",
    "docs/audits/part1-stage3-decision-authority.md",
    "docs/audits/part1-stage3-skeptical-review.md",
    "docs/claims.json",
    "docs/proof-matrix.json",
    "docs/rehearsal/part1-stage3-execution-rehearsal.md",
    "docs/requirements/part1-stage3-acceptance.json",
    "docs/requirements/parts2-5-acceptance.json",
    "docs/stage3-traceability.json",
    "evidence/part1/stage2/manifest.json",
    "evidence/part1/stage3/oracle-results.json",
    "fixtures/part1/stage3/envelope.json",
    "fixtures/part1/stage3/fixture-manifest.json",
    "fixtures/part1/stage3/identity.json",
    "fixtures/part1/stage3/recovery.json",
    "fixtures/part1/stage3/replay-and-skew.json",
    "fixtures/part1/stage3/sessions.json",
    "fixtures/part1/stage3/time.json",
    "oracles/eventpulse_reference.py",
    "scripts/build_stage3_manifest.py",
    "scripts/validate_stage2_contract.py",
    "scripts/validate_stage3_completion.py",
    "tests/test_stage3_negative_controls.py",
    "tests/test_stage3_oracle.py",
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def oracle_rendered() -> str:
    return canonical_bytes(evaluate_corpus()).decode("utf-8") + "\n"


def build() -> dict[str, object]:
    completion = ROOT / "docs/audits/part1-completion.md"
    paths = list(ARTIFACTS)
    status = "IN_REVIEW"
    if completion.exists():
        paths.append("docs/audits/part1-completion.md")
        status = "COMPLETED"
    artifacts = [
        {
            "path": relative,
            "sha256": sha256(ROOT / relative),
            "size_bytes": (ROOT / relative).stat().st_size,
        }
        for relative in sorted(paths)
    ]
    return {
        "acceptance_criteria": 30,
        "artifacts": artifacts,
        "claim_boundary": {
            "independent_local_oracle": "LOCAL_VERIFIED",
            "aws_streaming": "UNCLAIMED",
            "durable_aws_recovery": "UNCLAIMED",
            "measured_performance": "UNCLAIMED",
        },
        "contract_version": "1.0.0",
        "project": "eventpulse-realtime-engagement-platform",
        "source": {"base_sha": BASE_SHA, "base_tree": BASE_TREE, "region": "ap-south-2"},
        "stage": "PART1_STAGE3_EXECUTABLE_ORACLES",
        "status": status,
    }


def manifest_rendered() -> str:
    return json.dumps(build(), indent=2, sort_keys=True) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected_oracle = oracle_rendered()
    if args.check:
        if not ORACLE_OUTPUT.exists() or ORACLE_OUTPUT.read_text(encoding="utf-8") != expected_oracle:
            raise SystemExit("Stage 3 oracle results are missing or stale")
        expected_manifest = manifest_rendered()
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != expected_manifest:
            raise SystemExit("Stage 3 manifest is missing or stale")
        print("Stage 3 oracle results and artifact manifest: current")
        return
    ORACLE_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    ORACLE_OUTPUT.write_text(expected_oracle, encoding="utf-8")
    OUTPUT.write_text(manifest_rendered(), encoding="utf-8")
    print(f"wrote {ORACLE_OUTPUT.relative_to(ROOT)} and {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
