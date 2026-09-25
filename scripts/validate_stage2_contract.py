"""Fail-closed validation for the EventPulse Part 1 Stage 2 authority."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
BASE_SHA = "cac96a23648be8512c5cab58774217169d7e5829"
BASE_TREE = "17bcfb451e52e4cdce7975b09de76e4848a29138"
ALLOWED_LEVELS = {
    "DESIGN_ONLY", "LOCAL_VERIFIED", "AWS_VERIFIED", "MEASURED", "EXTRAPOLATED", "UNCLAIMED"
}
PROHIBITED_STAGE2_LEVELS = {"AWS_VERIFIED", "MEASURED", "EXTRAPOLATED"}
REQUIRED_FIELDS = {
    "schema_version", "event_id", "source", "user_id", "event_type",
    "event_time_ms", "ingest_time_ms", "partition_key", "payload",
}
REQUIRED_CATEGORIES = {"on_time", "accepted_late", "beyond_watermark"}
REQUIRED_CRASH_IDS = {f"EP-CRASH-{number:02d}" for number in range(1, 9)}
REQUIRED_GROUPS = {"Envelope", "Identity", "Event time", "Sessions", "Effects", "Replay", "Operations", "Security", "Cost", "Proof"}
FOREIGN_NAMES = tuple("".join(parts) for parts in (("ledger", "guard"), ("change", "bridge"), ("feature", "forge"), ("atlas", "retail")))
AWS_KEY = re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")
ACCOUNT = re.compile(r"(?<![0-9])[0-9]{12}(?![0-9])")


def load(relative: str) -> object:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def load_all() -> dict[str, object]:
    return {
        "schema": load("contracts/engagement-event-v1.schema.json"),
        "semantics": load("contracts/event-semantics-v1.json"),
        "examples": load("contracts/semantic-examples-v1.json"),
        "recovery": load("contracts/recovery-protocol-v1.json"),
        "requirements": load("docs/requirements/part1-stage2.json"),
        "proof": load("docs/proof-matrix.json"),
        "claims": load("docs/claims.json"),
        "manifest": load("evidence/part1/stage2/manifest.json"),
    }


def validate_data(data: dict[str, object]) -> list[str]:
    errors: list[str] = []
    schema = data["schema"]
    semantics = data["semantics"]
    examples = data["examples"]
    recovery = data["recovery"]
    requirements = data["requirements"]
    proof = data["proof"]
    claims = data["claims"]
    manifest = data["manifest"]
    if not all(isinstance(value, dict) for value in data.values()):
        return ["all authority roots must be objects"]

    assert isinstance(schema, dict) and isinstance(semantics, dict) and isinstance(examples, dict)
    assert isinstance(recovery, dict) and isinstance(requirements, dict)
    assert isinstance(proof, dict) and isinstance(claims, dict) and isinstance(manifest, dict)

    for name, obj in (("semantics", semantics), ("recovery", recovery), ("requirements", requirements), ("claims", claims), ("manifest", manifest)):
        if obj.get("project") != "eventpulse-realtime-engagement-platform":
            errors.append(f"{name}: wrong project")

    authority = semantics.get("authority", {})
    source = manifest.get("source", {})
    if not isinstance(authority, dict) or authority.get("source_base_sha") != BASE_SHA or authority.get("source_base_tree") != BASE_TREE:
        errors.append("semantic authority is not bound to the Stage 1 checkpoint")
    if not isinstance(source, dict) or source.get("base_sha") != BASE_SHA or source.get("base_tree") != BASE_TREE:
        errors.append("manifest is not bound to the Stage 1 checkpoint")
    if authority.get("region") != "ap-south-2" or source.get("region") != "ap-south-2":
        errors.append("authoritative region must be ap-south-2")

    if schema.get("$id") != "urn:eventpulse:engagement-event:1.0.0":
        errors.append("unexpected schema identifier")
    if set(schema.get("required", [])) != REQUIRED_FIELDS:
        errors.append("event envelope required-field set is incomplete")
    if schema.get("additionalProperties") is not False:
        errors.append("event envelope must reject unknown top-level fields")
    properties = schema.get("properties", {})
    if not isinstance(properties, dict) or properties.get("schema_version", {}).get("const") != "1.0.0":
        errors.append("schema version is not frozen")
    if len(schema.get("allOf", [])) != 2:
        errors.append("purchase payload conditional rules are incomplete")

    identity = semantics.get("identity", {})
    time = semantics.get("event_time", {})
    sessions = semantics.get("sessions", {})
    retention = semantics.get("retention", {})
    if not all(isinstance(x, dict) for x in (identity, time, sessions, retention)):
        errors.append("semantic sections must be objects")
    else:
        if identity.get("dedupe_horizon_ms") != 604800000 or identity.get("ttl_storage_ms", 0) <= identity.get("dedupe_horizon_ms", 0):
            errors.append("dedupe horizon or protective TTL is invalid")
        if "quarantine" not in str(identity.get("conflicting_duplicate", "")).lower():
            errors.append("same-ID conflicts must be quarantined")
        if "no live application effect" not in str(identity.get("after_horizon", "")):
            errors.append("post-horizon behavior may double apply an event")
        if time.get("allowed_lateness_ms") != 1800000 or set(time.get("categories", {})) != REQUIRED_CATEGORIES:
            errors.append("watermark categories or allowed lateness drifted")
        if not str(time.get("boundary", "")).startswith("event_time_ms equal"):
            errors.append("watermark equality boundary is ambiguous")
        if sessions.get("inactivity_gap_ms") != 1800000 or "exactly equal" not in str(sessions.get("boundary", "")):
            errors.append("session gap boundary is ambiguous")
        if time.get("allowed_lateness_ms", 0) < sessions.get("inactivity_gap_ms", 0):
            errors.append("allowed lateness cannot support the required bridge case")
        if "watermark >" not in str(sessions.get("closure", "")):
            errors.append("session closure is not strictly defined")
        if retention.get("raw_archive_days") != 7 or retention.get("identity_and_open_state_days", 0) <= retention.get("raw_archive_days", 0):
            errors.append("retention does not protect the replay/dedupe boundary")

    time_examples = examples.get("time_examples", [])
    session_examples = examples.get("session_examples", [])
    ttl_examples = examples.get("ttl_examples", [])
    if len(time_examples) != 5 or {row.get("expected_category") for row in time_examples} != REQUIRED_CATEGORIES:
        errors.append("worked time examples are incomplete")
    if not any(row.get("event_time_ms") == row.get("watermark_before_ms") and row.get("expected_category") == "accepted_late" for row in time_examples):
        errors.append("worked watermark equality example is missing")
    if {row.get("expected_session_count") for row in session_examples} != {1, 2} or not any("bridge" in row.get("name", "") for row in session_examples):
        errors.append("worked session boundary or bridge examples are incomplete")
    if {row.get("expected") for row in ttl_examples} != {"IDENTITY_PROTECTED", "EXPIRED_IDENTITY_QUARANTINE"}:
        errors.append("worked TTL boundary examples are incomplete")

    mapping = recovery.get("lambda_mapping", {})
    boundaries = recovery.get("boundaries", [])
    if not isinstance(mapping, dict) or mapping.get("parallelization_factor") != 1 or mapping.get("report_batch_item_failures") is not True:
        errors.append("Lambda ordering or partial-failure controls drifted")
    crash_ids = {row.get("id") for row in boundaries if isinstance(row, dict)} if isinstance(boundaries, list) else set()
    if crash_ids != REQUIRED_CRASH_IDS:
        errors.append("crash transition matrix is incomplete")
    recovery_claims = recovery.get("claims", {})
    if not isinstance(recovery_claims, dict) or recovery_claims.get("transport_exactly_once") is not False:
        errors.append("transport exactly-once must remain false")
    if any(not row.get("retry") or not row.get("safety") for row in boundaries if isinstance(row, dict)):
        errors.append("crash transition is missing retry or safety behavior")

    rows = requirements.get("requirements", [])
    if not isinstance(rows, list) or len(rows) < 35:
        errors.append("requirement inventory is unexpectedly small")
        rows = []
    ids = [row.get("id") for row in rows if isinstance(row, dict)]
    if len(ids) != len(set(ids)):
        errors.append("duplicate requirement ID")
    if {row.get("group") for row in rows if isinstance(row, dict)} != REQUIRED_GROUPS:
        errors.append("requirement groups are incomplete")
    if any(not row.get("authority") or not row.get("failure_condition") for row in rows if isinstance(row, dict)):
        errors.append("requirement lacks authority or failure condition")

    mappings = proof.get("mappings", [])
    mapped = [row.get("requirement_id") for row in mappings if isinstance(row, dict)] if isinstance(mappings, list) else []
    if set(mapped) != set(ids) or len(mapped) != len(ids):
        errors.append("proof matrix does not cover every requirement exactly once")
    authorities = {row.get("id"): row.get("authority") for row in rows if isinstance(row, dict)}
    for row in mappings if isinstance(mappings, list) else []:
        if not isinstance(row, dict):
            errors.append("proof row is malformed")
            continue
        if row.get("authority") != authorities.get(row.get("requirement_id")):
            errors.append(f"proof authority mismatch for {row.get('requirement_id')}")
        if row.get("claim_level") not in {"DESIGN_ONLY", "LOCAL_VERIFIED"}:
            errors.append(f"invalid Stage 2 proof level for {row.get('requirement_id')}")

    claim_rows = claims.get("claims", [])
    if not isinstance(claim_rows, list) or len(claim_rows) < 10:
        errors.append("claim registry is incomplete")
        claim_rows = []
    claim_ids = [row.get("id") for row in claim_rows if isinstance(row, dict)]
    if len(claim_ids) != len(set(claim_ids)):
        errors.append("duplicate claim ID")
    for row in claim_rows:
        if not isinstance(row, dict) or row.get("level") not in ALLOWED_LEVELS:
            errors.append("invalid claim label")
            continue
        if row.get("level") in PROHIBITED_STAGE2_LEVELS:
            errors.append(f"Stage 2 claim inflation: {row.get('id')}")
        for evidence in row.get("evidence", []):
            if not (ROOT / evidence).exists():
                errors.append(f"claim evidence path does not exist: {evidence}")
    if {"managed_consumer", "durable_aws_recovery", "latency_throughput", "observed_spend", "teardown"} - set(claim_ids):
        errors.append("mandatory unverified claims are absent")

    manifest_status = manifest.get("status")
    completion_exists = (ROOT / "docs/audits/part1-stage2-completion.md").exists()
    expected_status = "COMPLETED" if completion_exists else "IN_REVIEW"
    if manifest_status != expected_status:
        errors.append("manifest status contradicts completion-receipt presence")
    return errors


def validate_manifest(manifest: dict[str, object]) -> list[str]:
    errors: list[str] = []
    rows = manifest.get("artifacts", [])
    if not isinstance(rows, list):
        return ["manifest artifacts must be a list"]
    paths = [row.get("path") for row in rows if isinstance(row, dict)]
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        errors.append("manifest paths must be sorted and unique")
    for row in rows:
        if not isinstance(row, dict):
            errors.append("manifest row malformed")
            continue
        relative = row.get("path")
        if not isinstance(relative, str):
            errors.append("manifest path must be a string")
            continue
        pure = PurePosixPath(relative)
        if pure.is_absolute() or ".." in pure.parts:
            errors.append(f"unsafe manifest path: {relative}")
            continue
        path = ROOT / relative
        if not path.is_file() or path.is_symlink():
            errors.append(f"manifest artifact missing or not a regular file: {relative}")
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != row.get("sha256") or path.stat().st_size != row.get("size_bytes"):
            errors.append(f"manifest digest or size mismatch: {relative}")
    return errors


def validate_public_files(manifest: dict[str, object]) -> list[str]:
    errors: list[str] = []
    rows = manifest.get("artifacts", [])
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or not isinstance(row.get("path"), str):
            continue
        relative = row["path"]
        path = ROOT / relative
        if path.suffix not in {".md", ".json", ".py", ".yml", ".yaml"}:
            continue
        text = path.read_text(encoding="utf-8")
        lowered = text.lower()
        if any(name in lowered for name in FOREIGN_NAMES):
            errors.append(f"foreign-project material in {relative}")
        if AWS_KEY.search(text) or ACCOUNT.search(text) or ("arn:" + "aws:") in lowered:
            errors.append(f"sensitive AWS identifier in {relative}")
    adr = (ROOT / "docs/adr/0001-kinesis-lambda-consumer.md").read_text(encoding="utf-8")
    required_sources = (
        "docs.aws.amazon.com/lambda/latest/dg/services-kinesis-batchfailurereporting.html",
        "docs.aws.amazon.com/amazondynamodb/latest/developerguide/transaction-apis.html",
        "docs.aws.amazon.com/AmazonS3/latest/API/API_PutObject.html",
        "docs.aws.amazon.com/general/latest/gr/ak.html",
    )
    if any(source not in adr for source in required_sources):
        errors.append("runtime ADR lacks primary-source support")
    if "ap-south-1" not in adr or "rejected" not in adr.lower() or "ap-south-2" not in adr:
        errors.append("runtime ADR does not resolve the historical region conflict")
    return errors


def validate_git_scope(verify_source: bool) -> list[str]:
    if not verify_source:
        return []
    errors: list[str] = []
    try:
        tree = subprocess.check_output(["git", "rev-parse", f"{BASE_SHA}^{{tree}}"], cwd=ROOT, text=True).strip()
        subprocess.run(["git", "merge-base", "--is-ancestor", BASE_SHA, "HEAD"], cwd=ROOT, check=True, capture_output=True)
        changed = subprocess.check_output(["git", "diff", "--name-only", f"{BASE_SHA}...HEAD"], cwd=ROOT, text=True).splitlines()
    except (OSError, subprocess.CalledProcessError) as exc:
        return [f"source checkpoint cannot be verified: {exc}"]
    if tree != BASE_TREE:
        errors.append("Stage 1 source tree does not match the recorded tree")
    allowed_exact = {
        ".github/workflows/stage2-contract.yml", "docs/STATUS.md",
        "scripts/build_stage2_manifest.py", "scripts/validate_stage2_contract.py",
        "tests/test_stage2_contract.py",
    }
    allowed_prefixes = ("contracts/", "docs/adr/", "docs/audits/part1-stage2", "docs/requirements/", "evidence/part1/stage2/")
    allowed_docs = {
        "docs/INTERVIEW.md", "docs/architecture.md", "docs/claims.json", "docs/known-limits.md",
        "docs/operations-contract.md", "docs/proof-matrix.json", "docs/security-and-lifecycle.md", "docs/threat-model.md",
    }
    for path in changed:
        if path in allowed_exact or path in allowed_docs or path.startswith(allowed_prefixes):
            continue
        errors.append(f"out-of-scope Stage 2 path: {path}")
    return errors


def validate(*, verify_source: bool = False) -> list[str]:
    try:
        data = load_all()
    except (OSError, json.JSONDecodeError) as exc:
        return [f"Stage 2 input cannot be read: {exc}"]
    manifest = data["manifest"]
    assert isinstance(manifest, dict)
    return validate_data(data) + validate_manifest(manifest) + validate_public_files(manifest) + validate_git_scope(verify_source)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-source", action="store_true")
    args = parser.parse_args()
    failures = validate(verify_source=args.verify_source)
    if failures:
        for failure in failures:
            print(f"ERROR: {failure}", file=sys.stderr)
        raise SystemExit(1)
    manifest = load("evidence/part1/stage2/manifest.json")
    print(f"Stage 2 contract: internally consistent; status={manifest['status']}")
