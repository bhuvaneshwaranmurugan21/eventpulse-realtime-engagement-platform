#!/usr/bin/env python3
"""Fail-closed structural validator for EventPulse Part 3 Stage 1."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import shutil
import subprocess  # nosec B404
from pathlib import Path

# Subprocess use below is limited to the resolved git executable and constant arguments.

ROOT = Path(__file__).resolve().parents[1]
BASE_SHA = "75923c9c272d940ed2a6f90de1e2492a1269a3ea"
BASE_TREE = "00bf6480d299461cb879d528a0bff6ba8c8dc191"
GIT = shutil.which("git") or "git"


def load(path: str) -> object:
    return json.loads((ROOT / path).read_text())


def validate() -> list[str]:
    errors: list[str] = []
    req = load("part3/stage1/docs/requirements.json")
    trace = load("part3/stage1/docs/traceability.json")
    allow = load("part3/stage1/docs/command-allowlist.json")
    claims = load("part3/stage1/docs/claims.json")
    manifest = load("evidence/part3/stage1/manifest.json")
    if not all(isinstance(item, dict) for item in (req, trace, allow, claims, manifest)):
        return ["authority document root must be an object"]
    criteria = req.get("criteria", [])
    if len(criteria) != 40 or len(set(criteria)) != 40:
        errors.append("criteria registry drift")
    mapped = [row.get("criterion") for row in trace.get("mappings", [])]
    if mapped != criteria:
        errors.append("traceability does not cover criteria exactly and in order")
    if req.get("predecessor_commit") != BASE_SHA or req.get("predecessor_tree") != BASE_TREE:
        errors.append("predecessor drift")
    if req.get("expected_account") != "773994909635" or req.get("expected_region") != "ap-south-2":
        errors.append("AWS boundary drift")
    script = (ROOT / "scripts/eventpulse_part3_stage1_read_only_aws_kit.sh").read_text()
    operations = set()
    for line in script.splitlines():
        stripped = line.strip()
        if stripped.startswith("run ") and " aws " in f" {stripped} ":
            words = stripped.split()
            index = words.index("aws")
            operations.add(" ".join(words[index + 1 : index + 3]))
    if operations != set(allow.get("allowed_aws_operations", [])):
        errors.append("AWS command allow-list mismatch")
    lowered = script.lower()
    for token in allow.get("forbidden_tokens", []):
        if token in lowered:
            errors.append(f"forbidden AWS mutation token: {token}")
    oracle_tree = ast.parse((ROOT / "part3/stage1/oracles/admission_oracle.py").read_text())
    for node in ast.walk(oracle_tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = (
                [item.name for item in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
            )
            if any(name.startswith(("eventpulse", "boto", "botocore")) for name in names):
                errors.append("independent oracle imports production or AWS SDK")
    levels = {row.get("id"): row.get("level") for row in claims.get("claims", [])}
    if (
        levels.get("P3S1-AWS") != "AWS_OBSERVED_INDETERMINATE"
        or levels.get("P3S1-DEPLOYMENT") != "UNCLAIMED"
    ):
        errors.append("AWS observation or deployment claim exceeds evidence")
    receipt = load("evidence/part3/stage1/aws-observation-receipt.json")
    if not isinstance(receipt, dict):
        errors.append("AWS observation receipt root must be an object")
    elif (
        receipt.get("bundle_sha256")
        != "ce6f720d3a3f3049f3dae2fdc25eb8f5dcfbe9be62b99e59c888222ba067bb5c"
        or receipt.get("decision") != "INDETERMINATE"
        or receipt.get("region_status") != "DISABLED"
        or receipt.get("raw_evidence_committed") is not False
        or receipt.get("stage2_gate") != "BLOCKED"
    ):
        errors.append("AWS observation receipt drift")
    rows = manifest.get("artifacts", [])
    if [row.get("path") for row in rows] != sorted({row.get("path") for row in rows}):
        errors.append("manifest paths not sorted and unique")
    for row in rows:
        path = ROOT / row["path"]
        if (
            not path.is_file()
            or len(path.read_bytes()) != row["size_bytes"]
            or hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]
        ):
            errors.append(f"manifest mismatch: {row['path']}")
    changed = set(
        subprocess.check_output(  # nosec B603  # noqa: S603
            [GIT, "diff", "--name-only", BASE_SHA, "--"], cwd=ROOT, text=True
        ).splitlines()
    )
    allowed_prefixes = (
        ".github/workflows/part3-stage1-",
        "evidence/part3/stage1/",
        "part3/stage1/",
        "scripts/build_part3_stage1_",
        "scripts/eventpulse_part3_stage1_",
        "scripts/validate_part3_stage1.py",
        "tests/test_part3_stage1_",
    )
    errors.extend(
        f"out-of-scope file: {item}" for item in changed if not item.startswith(allowed_prefixes)
    )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-source", action="store_true")
    args = parser.parse_args()
    errors = validate()
    if args.verify_source:
        tree = subprocess.check_output(  # nosec B603  # noqa: S603
            [GIT, "show", "-s", "--format=%T", BASE_SHA], cwd=ROOT, text=True
        ).strip()
        if (
            tree != BASE_TREE
            or subprocess.run(  # nosec B603  # noqa: S603
                [GIT, "merge-base", "--is-ancestor", BASE_SHA, "HEAD"], cwd=ROOT
            ).returncode
        ):
            errors.append("source identity failed")
    if errors:
        print("\n".join(errors))
        return 1
    print("EventPulse Part 3 Stage 1 pre-observation validation: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
