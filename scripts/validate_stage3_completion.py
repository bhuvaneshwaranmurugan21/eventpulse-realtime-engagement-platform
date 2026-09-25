"""Fail-closed validation for EventPulse Part 1 Stage 3."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from oracles.eventpulse_reference import (  # noqa: E402
    FIXTURE_FILES,
    canonical_sha256,
    evaluate_corpus,
    fixture_ids,
)


BASE_SHA = "9394d1795d3e4e9622e4f580aef61be455f6ce4b"
BASE_TREE = "ad4077ea62bcae275030a7c389d5a0538a07d6fc"
ALLOWED_LEVELS = {
    "AWS_VERIFIED",
    "DESIGN_ONLY",
    "EXTRAPOLATED",
    "LOCAL_VERIFIED",
    "MEASURED",
    "UNCLAIMED",
}
PROHIBITED_PART1_LEVELS = {"AWS_VERIFIED", "EXTRAPOLATED", "MEASURED"}
FOREIGN_NAMES = tuple(
    "".join(parts)
    for parts in (
        ("ledger", "guard"),
        ("change", "bridge"),
        ("feature", "forge"),
        ("atlas", "retail"),
    )
)
AWS_KEY = re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")
ACCOUNT = re.compile(r"(?<![A-Za-z0-9])[0-9]{12}(?![A-Za-z0-9])")
AUTHORITY_ARTIFACTS = {
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
}


def load(relative: str) -> Any:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def load_all() -> dict[str, Any]:
    return {
        "acceptance": load("docs/requirements/part1-stage3-acceptance.json"),
        "claims": load("docs/claims.json"),
        "fixture_manifest": load("fixtures/part1/stage3/fixture-manifest.json"),
        "future": load("docs/requirements/parts2-5-acceptance.json"),
        "manifest": load("evidence/part1/stage3/manifest.json"),
        "oracle_result": load("evidence/part1/stage3/oracle-results.json"),
        "oracle_spec": load("contracts/stage3-oracle-spec-v1.json"),
        "requirements": load("docs/requirements/part1-stage2.json"),
        "stage2_proof": load("docs/proof-matrix.json"),
        "traceability": load("docs/stage3-traceability.json"),
    }


def validate_authority(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for name in ("acceptance", "claims", "fixture_manifest", "future", "manifest", "oracle_spec", "requirements", "traceability"):
        if data[name].get("project") != "eventpulse-realtime-engagement-platform":
            errors.append(f"{name}: wrong project")
    spec_source = data["oracle_spec"].get("source", {})
    manifest_source = data["manifest"].get("source", {})
    for name, source in (("oracle spec", spec_source), ("manifest", manifest_source)):
        if source.get("base_sha") != BASE_SHA or source.get("base_tree") != BASE_TREE:
            errors.append(f"{name}: wrong Stage 2 source boundary")
    for name in ("fixture_manifest", "future", "traceability"):
        if data[name].get("source_sha") != BASE_SHA:
            errors.append(f"{name}: source SHA drift")
    for name in ("fixture_manifest", "future", "traceability"):
        if data[name].get("source_tree") != BASE_TREE:
            errors.append(f"{name}: source tree drift")
    if manifest_source.get("region") != "ap-south-2":
        errors.append("Stage 3 authoritative region must remain ap-south-2")
    if data["oracle_spec"].get("dependencies", {}).get("shared_production_semantic_code") is not False:
        errors.append("oracle may not share the production semantic path")
    if data["oracle_spec"].get("clarifications", {}).get("clock_reference") != (
        "ingest_time_ms is the reference for max_future_ms and max_age_ms local-oracle classification"
    ):
        errors.append("clock reference is not byte-executable")
    return errors


def validate_acceptance(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    rows = data["acceptance"].get("acceptance", [])
    expected_ids = {f"EP-P1-S3-AC-{number:02d}" for number in range(1, 31)}
    ids = [row.get("id") for row in rows if isinstance(row, dict)]
    if len(rows) != 30 or set(ids) != expected_ids or len(ids) != len(set(ids)):
        errors.append("Stage 3 acceptance registry is not exactly AC-01 through AC-30")
    authority_expected = expected_ids - {
        "EP-P1-S3-AC-27",
        "EP-P1-S3-AC-28",
        "EP-P1-S3-AC-29",
    }
    if set(data["acceptance"].get("authority_gate_ids", [])) != authority_expected:
        errors.append("authority acceptance gate partition is incomplete")
    expected_gate = {
        "EP-P1-S3-AC-27": "POST_AUTHORITY_MERGE",
        "EP-P1-S3-AC-28": "POST_RECEIPT_MERGE",
        "EP-P1-S3-AC-29": "POST_RECEIPT_MERGE",
    }
    for row in rows:
        if not isinstance(row, dict) or not all(
            row.get(key) for key in ("id", "gate", "requirement", "evidence", "failure_condition")
        ):
            errors.append("acceptance row is incomplete")
            continue
        if row["gate"] != expected_gate.get(row["id"], "AUTHORITY"):
            errors.append(f"acceptance gate is incorrect: {row['id']}")
    return errors


def validate_oracle(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    actual = evaluate_corpus()
    expected = data["oracle_result"]
    fixture_manifest = data["fixture_manifest"]
    if actual != expected:
        errors.append("committed oracle result differs from independent evaluation")
    if actual.get("status") != "PASS" or actual.get("failures"):
        errors.append("oracle corpus has failures")
    if actual.get("fixture_count") != 50:
        errors.append("oracle fixture count is not 50")
    if fixture_manifest.get("expected_case_count") != actual.get("fixture_count"):
        errors.append("fixture manifest count differs from oracle result")
    if fixture_manifest.get("expected_corpus_sha256") != actual.get("corpus_sha256"):
        errors.append("fixture manifest corpus digest differs from oracle result")
    ids = fixture_ids()
    if len(ids) != 50:
        errors.append("fixture IDs are not exactly 50 unique cases")
    listed_files = {Path(row["file"]).name for row in fixture_manifest.get("files", []) if isinstance(row, dict)}
    if listed_files != set(FIXTURE_FILES):
        errors.append("fixture manifest does not list the complete corpus")
    required = {
        "EP-S3-FX-ENV-009",
        "EP-S3-FX-ENV-012",
        "EP-S3-FX-ENV-013",
        "EP-S3-FX-ID-004",
        "EP-S3-FX-ID-005",
        "EP-S3-FX-TIME-004",
        "EP-S3-FX-TIME-005",
        "EP-S3-FX-TIME-006",
        "EP-S3-FX-SESSION-001",
        "EP-S3-FX-SESSION-002",
        "EP-S3-FX-SESSION-004",
        "EP-S3-FX-SESSION-005",
        "EP-S3-FX-SESSION-006",
        "EP-S3-FX-REPLAY-003",
        "EP-S3-FX-SKEW-002",
    } | {f"EP-S3-FX-RECOVERY-{number:03d}" for number in range(1, 12)}
    missing = required - ids
    if missing:
        errors.append(f"mandatory boundary fixtures missing: {sorted(missing)}")
    return errors


def validate_traceability(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    requirements = data["requirements"].get("requirements", [])
    requirement_ids = [row.get("id") for row in requirements if isinstance(row, dict)]
    mappings = data["traceability"].get("mappings", [])
    mapped_ids = [row.get("requirement_id") for row in mappings if isinstance(row, dict)]
    if len(requirement_ids) != 40 or len(set(requirement_ids)) != 40:
        errors.append("Stage 2 requirement inventory is not exactly 40 unique IDs")
    if set(mapped_ids) != set(requirement_ids) or len(mapped_ids) != len(requirement_ids):
        errors.append("Stage 3 traceability does not cover every requirement exactly once")
    known_fixtures = fixture_ids()
    referenced_fixtures: set[str] = set()
    for row in mappings:
        if not isinstance(row, dict):
            errors.append("traceability row is malformed")
            continue
        row_fixtures = row.get("fixture_ids", [])
        if not isinstance(row_fixtures, list):
            errors.append(f"fixture_ids is not a list for {row.get('requirement_id')}")
            continue
        referenced_fixtures.update(row_fixtures)
        if set(row_fixtures) - known_fixtures:
            errors.append(f"unknown fixture in {row.get('requirement_id')}")
        if row.get("part1_claim_level") not in {"DESIGN_ONLY", "LOCAL_VERIFIED"}:
            errors.append(f"invalid Part 1 claim level for {row.get('requirement_id')}")
        if not row.get("local_proof") or not row.get("future_proof"):
            errors.append(f"incomplete proof path for {row.get('requirement_id')}")
    if referenced_fixtures != known_fixtures:
        errors.append(f"orphan fixture IDs: {sorted(known_fixtures - referenced_fixtures)}")
    expected_status = "COMPLETED" if (ROOT / "docs/audits/part1-completion.md").exists() else "IN_REVIEW"
    if data["traceability"].get("status") != expected_status:
        errors.append("traceability status contradicts Part 1 receipt presence")
    return errors


def validate_future_acceptance(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    rows = data["future"].get("acceptance", [])
    if not isinstance(rows, list) or len(rows) < 15:
        return ["future acceptance registry is incomplete"]
    ids = [row.get("id") for row in rows if isinstance(row, dict)]
    if len(ids) != len(set(ids)):
        errors.append("duplicate future acceptance ID")
    if {row.get("part") for row in rows if isinstance(row, dict)} != {2, 3, 4, 5}:
        errors.append("future acceptance registry does not cover Parts 2 through 5")
    for row in rows:
        required = (
            "id", "requirement", "proof", "failure_condition", "claim_ceiling",
            "predecessor", "preconditions", "stop_conditions", "rollback_cleanup",
            "resume_point", "stale_evidence",
        )
        if not isinstance(row, dict) or not all(row.get(key) for key in required):
            errors.append("future acceptance row is incomplete")
            continue
        if not isinstance(row["preconditions"], list) or not isinstance(row["stop_conditions"], list):
            errors.append(f"future decision controls are malformed: {row['id']}")
        if row["claim_ceiling"] not in {"DESIGN_ONLY", "LOCAL_VERIFIED", "AWS_VERIFIED", "MEASURED"}:
            errors.append(f"invalid future claim ceiling: {row['id']}")
    return errors


def validate_claims(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    claims = data["claims"].get("claims", [])
    ids = [row.get("id") for row in claims if isinstance(row, dict)]
    if len(ids) != len(set(ids)):
        errors.append("duplicate claim ID")
    mandatory_unclaimed = {
        "durable_aws_recovery",
        "latency_throughput",
        "managed_consumer",
        "observed_spend",
        "teardown",
    }
    by_id = {row.get("id"): row for row in claims if isinstance(row, dict)}
    for claim_id in mandatory_unclaimed:
        if by_id.get(claim_id, {}).get("level") != "UNCLAIMED":
            errors.append(f"future claim promoted in Part 1: {claim_id}")
    if by_id.get("stage3_independent_oracle", {}).get("level") != "LOCAL_VERIFIED":
        errors.append("independent oracle claim is absent or incorrectly classified")
    if by_id.get("application_effect_idempotency", {}).get("level") != "DESIGN_ONLY":
        errors.append("application effects cannot be promoted without production crash proof")
    for row in claims:
        if not isinstance(row, dict) or row.get("level") not in ALLOWED_LEVELS:
            errors.append("invalid claim row or level")
            continue
        if row.get("level") in PROHIBITED_PART1_LEVELS:
            errors.append(f"Part 1 claim inflation: {row.get('id')}")
        for evidence in row.get("evidence", []):
            if not (ROOT / evidence).is_file():
                errors.append(f"claim evidence path missing: {evidence}")
    return errors


def validate_stage2_proof_alignment(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    trace = {row["requirement_id"]: row for row in data["traceability"].get("mappings", [])}
    proof_rows = data["stage2_proof"].get("mappings", [])
    for row in proof_rows:
        requirement_id = row.get("requirement_id")
        expected = trace.get(requirement_id, {}).get("part1_claim_level")
        if row.get("claim_level") != expected:
            errors.append(f"proof/traceability level mismatch: {requirement_id}")
        if "Stage 3" not in str(row.get("local_proof", "")) and expected == "LOCAL_VERIFIED" and requirement_id not in {"EP-EVT-001", "EP-EVT-002", "EP-EVT-004"}:
            errors.append(f"Stage 3 local proof not named: {requirement_id}")
    return errors


def validate_manifest(manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    rows = manifest.get("artifacts", [])
    if not isinstance(rows, list):
        return ["manifest artifacts must be a list"]
    paths = [row.get("path") for row in rows if isinstance(row, dict)]
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        errors.append("manifest paths must be sorted and unique")
    expected_paths = set(AUTHORITY_ARTIFACTS)
    if (ROOT / "docs/audits/part1-completion.md").exists():
        expected_paths.add("docs/audits/part1-completion.md")
    if set(paths) != expected_paths:
        missing = sorted(expected_paths - set(paths))
        extra = sorted(set(paths) - expected_paths)
        errors.append(f"manifest artifact inventory mismatch: missing={missing} extra={extra}")
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("path"), str):
            errors.append("malformed manifest row")
            continue
        relative = row["path"]
        pure = PurePosixPath(relative)
        if pure.is_absolute() or ".." in pure.parts:
            errors.append(f"unsafe manifest path: {relative}")
            continue
        path = ROOT / relative
        if not path.is_file() or path.is_symlink():
            errors.append(f"manifest artifact missing or unsafe: {relative}")
            continue
        if hashlib.sha256(path.read_bytes()).hexdigest() != row.get("sha256"):
            errors.append(f"manifest digest mismatch: {relative}")
        if path.stat().st_size != row.get("size_bytes"):
            errors.append(f"manifest size mismatch: {relative}")
    expected_status = "COMPLETED" if (ROOT / "docs/audits/part1-completion.md").exists() else "IN_REVIEW"
    if manifest.get("status") != expected_status:
        errors.append("manifest status contradicts Part 1 receipt presence")
    if manifest.get("acceptance_criteria") != 30:
        errors.append("manifest does not bind all 30 Stage 3 criteria")
    return errors


def validate_oracle_imports() -> list[str]:
    errors: list[str] = []
    path = ROOT / "oracles/eventpulse_reference.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    allowed_roots = {
        "__future__",
        "collections",
        "copy",
        "fractions",
        "hashlib",
        "json",
        "pathlib",
        "re",
        "typing",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules = [alias.name.split(".")[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            modules = [(node.module or "").split(".")[0]]
        else:
            continue
        for module in modules:
            if module not in allowed_roots:
                errors.append(f"oracle imports non-stdlib/shared module: {module}")
    return errors


def validate_public_files(manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for row in manifest.get("artifacts", []):
        if not isinstance(row, dict) or not isinstance(row.get("path"), str):
            continue
        path = ROOT / row["path"]
        if path.suffix not in {".json", ".md", ".py", ".yaml", ".yml"}:
            continue
        text = path.read_text(encoding="utf-8")
        lowered = text.lower()
        if any(name in lowered for name in FOREIGN_NAMES):
            errors.append(f"foreign-project material in {row['path']}")
        if AWS_KEY.search(text) or ACCOUNT.search(text) or ("arn:" + "aws:") in lowered:
            errors.append(f"sensitive AWS identifier in {row['path']}")
    return errors


def validate_git_scope(verify_source: bool) -> list[str]:
    if not verify_source:
        return []
    errors: list[str] = []
    try:
        tree = subprocess.check_output(["git", "rev-parse", f"{BASE_SHA}^{{tree}}"], cwd=ROOT, text=True).strip()
        subprocess.run(["git", "merge-base", "--is-ancestor", BASE_SHA, "HEAD"], cwd=ROOT, check=True, capture_output=True)
        committed = subprocess.check_output(["git", "diff", "--name-only", f"{BASE_SHA}...HEAD"], cwd=ROOT, text=True).splitlines()
        working = subprocess.check_output(["git", "diff", "--name-only", BASE_SHA], cwd=ROOT, text=True).splitlines()
        untracked = subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard"], cwd=ROOT, text=True).splitlines()
    except (OSError, subprocess.CalledProcessError) as exc:
        return [f"source boundary cannot be verified: {exc}"]
    if tree != BASE_TREE:
        errors.append("Stage 2 source tree differs from the recorded authority")
    paths = set(committed) | set(working) | set(untracked)
    allowed_exact = {
        ".github/workflows/stage3-oracles.yml",
        "contracts/stage3-oracle-spec-v1.json",
        "docs/INTERVIEW.md",
        "docs/STATUS.md",
        "docs/claims.json",
        "docs/proof-matrix.json",
        "docs/requirements/part1-stage3-acceptance.json",
        "docs/stage3-traceability.json",
        "evidence/part1/stage2/manifest.json",
        "scripts/validate_stage2_contract.py",
        "scripts/build_stage3_manifest.py",
        "scripts/validate_stage3_completion.py",
        "tests/test_stage3_negative_controls.py",
        "tests/test_stage3_oracle.py",
    }
    allowed_prefixes = (
        "docs/audits/part1-stage3",
        "docs/audits/part1-completion.md",
        "docs/rehearsal/",
        "docs/requirements/parts2-5-acceptance.json",
        "evidence/part1/stage3/",
        "fixtures/part1/stage3/",
        "oracles/",
    )
    for path in sorted(paths):
        if path in allowed_exact or path.startswith(allowed_prefixes):
            continue
        errors.append(f"out-of-scope Stage 3 path: {path}")
    return errors


def validate(*, verify_source: bool = False) -> list[str]:
    try:
        data = load_all()
    except (OSError, json.JSONDecodeError) as exc:
        return [f"Stage 3 input cannot be read: {exc}"]
    return (
        validate_authority(data)
        + validate_acceptance(data)
        + validate_oracle(data)
        + validate_traceability(data)
        + validate_future_acceptance(data)
        + validate_claims(data)
        + validate_stage2_proof_alignment(data)
        + validate_manifest(data["manifest"])
        + validate_oracle_imports()
        + validate_public_files(data["manifest"])
        + validate_git_scope(verify_source)
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-source", action="store_true")
    args = parser.parse_args()
    failures = validate(verify_source=args.verify_source)
    if failures:
        for failure in failures:
            print(f"ERROR: {failure}", file=sys.stderr)
        raise SystemExit(1)
    result = load("evidence/part1/stage3/oracle-results.json")
    manifest = load("evidence/part1/stage3/manifest.json")
    print(
        "Stage 3 executable oracles: "
        f"status={manifest['status']}; fixtures={result['fixture_count']}; "
        f"corpus_sha256={result['corpus_sha256']}"
    )


if __name__ == "__main__":
    main()
