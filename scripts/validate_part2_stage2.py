#!/usr/bin/env python3
"""Fail-closed structural validator for EventPulse Part 2 Stage 2."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BASE_SHA = "aac89f3f69ab9719f22157433ae50241ab3e7b0a"
BASE_TREE = "74f09687416593a6e195c21cae0596bd8285d14a"
EXPECTED_AC = {f"P2S2-AC-{number:02d}" for number in range(1, 37)}
EXPECTED_BOUNDARIES = {f"EP-CRASH-{number:02d}" for number in range(1, 9)}
EXPECTED_CONTROLS = {f"NC-{number:02d}" for number in range(1, 13)}
GIT = shutil.which("git")
if GIT is None:
    raise RuntimeError("git executable is required for source-bound validation")


def load_json(relative: str) -> Any:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def validate_requirements() -> list[str]:
    value = load_json("part2/stage2/docs/requirements.json")
    errors = []
    if set(value.get("acceptance_checks", [])) != EXPECTED_AC:
        errors.append("requirements are not exactly P2S2-AC-01 through P2S2-AC-36")
    if set(value.get("crash_boundaries", [])) != EXPECTED_BOUNDARIES:
        errors.append("requirements do not freeze exactly EP-CRASH-01 through EP-CRASH-08")
    controls = {str(item)[:5] for item in value.get("negative_controls", [])}
    if controls != EXPECTED_CONTROLS:
        errors.append("requirements do not freeze exactly NC-01 through NC-12")
    predecessor = value.get("expected_predecessor", {})
    if predecessor != {"main_sha": BASE_SHA, "main_tree": BASE_TREE}:
        errors.append("Stage 2 predecessor identity drift")
    if value.get("claim_ceiling") != "LOCAL_VERIFIED":
        errors.append("Stage 2 claim ceiling must remain LOCAL_VERIFIED")
    return errors


def validate_traceability() -> list[str]:
    value = load_json("part2/stage2/docs/traceability.json")
    mappings = value.get("mappings", [])
    identifiers = [row.get("id") for row in mappings]
    errors = []
    if len(identifiers) != 36 or set(identifiers) != EXPECTED_AC:
        errors.append("traceability does not cover all 36 acceptance checks exactly once")
    for row in mappings:
        for field in ("artifacts", "evidence", "tests"):
            paths = row.get(field)
            if not isinstance(paths, list) or not paths:
                errors.append(f"{row.get('id')} lacks {field}")
                continue
            for relative in paths:
                if not (ROOT / relative).exists():
                    errors.append(f"{row.get('id')} references missing {relative}")
    return errors


def validate_fixtures_and_evidence() -> list[str]:
    fixture = load_json("fixtures/part2/stage2/crash-matrix.json")
    golden = load_json("fixtures/part2/stage2/golden-digests.json")
    evidence = load_json("evidence/part2/stage2/crash-matrix.json")
    environment = load_json("evidence/part2/stage2/environment-reproducibility.json")
    package = load_json("evidence/part2/stage2/package-inventory.json")
    errors = []
    fixture_ids = {row.get("id") for row in fixture.get("cases", [])}
    if fixture_ids != EXPECTED_BOUNDARIES or len(fixture.get("cases", [])) != 8:
        errors.append("crash fixture is not exactly the eight frozen boundaries")
    if set(golden.get("cases", {})) != EXPECTED_BOUNDARIES:
        errors.append("golden digest registry does not cover exactly eight boundaries")
    matrix = evidence.get("matrix", {})
    result_ids = {row.get("case_id") for row in matrix.get("results", [])}
    if (
        evidence.get("runs_compared") != 2
        or evidence.get("network_calls") != 0
        or matrix.get("boundaries_passed") != 8
        or matrix.get("status") != "PASS"
        or result_ids != EXPECTED_BOUNDARIES
    ):
        errors.append("crash evidence is incomplete or not deterministic/no-network")
    encoded = json.dumps(matrix, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    if hashlib.sha256(encoded).hexdigest() != evidence.get("matrix_sha256"):
        errors.append("crash evidence digest mismatch")
    if environment.get("environments_compared") != 2 or environment.get("status") != "PASS":
        errors.append("two-environment reproducibility evidence is absent")
    lock_digest = hashlib.sha256((ROOT / "requirements/dev.lock").read_bytes()).hexdigest()
    if environment.get("lock_sha256") != lock_digest:
        errors.append("environment evidence is not bound to the exact development lock")
    package_paths = {row.get("path") for row in package.get("files", [])}
    if (
        package.get("handler") != "eventpulse.lambda_entry.lambda_handler"
        or package.get("self_contained_runtime_dependencies") is not True
        or "eventpulse/recovery.py" not in package_paths
    ):
        errors.append("Stage 2 Lambda package inventory is incomplete")
    return errors


def validate_oracle_isolation() -> list[str]:
    path = ROOT / "part2/stage2/oracles/part2_stage2_recovery.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    errors = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            continue
        if any(name.startswith("eventpulse") or name.startswith("tests") for name in names):
            errors.append(f"independent oracle imports prohibited module {names}")
    for production in sorted((ROOT / "src/eventpulse").glob("*.py")):
        if "part2_stage2_recovery" in production.read_text(encoding="utf-8"):
            errors.append(f"production imports the Stage 2 oracle: {production.name}")
    return errors


def validate_mechanism_and_controls() -> list[str]:
    harness = (ROOT / "scripts/run_part2_stage2_crash_matrix.py").read_text(encoding="utf-8")
    tests = (ROOT / "tests/test_part2_stage2_negative_controls.py").read_text(encoding="utf-8")
    errors = []
    for marker in (
        "os._exit(CRASH_EXIT)",
        "subprocess.run",
        "timeout=30",
        "sys.addaudithook(deny_network)",
        "eventpulse.handler",
        "phase",
        "process_id",
        "previous_sha256",
    ):
        if marker not in harness:
            errors.append(f"crash mechanism omits {marker}")
    controls = {
        f"NC-{match.group(1)}"
        for match in re.finditer(r"def test_nc(\d{2})_", tests)
    }
    if controls != EXPECTED_CONTROLS:
        errors.append("negative-control tests are not exactly NC-01 through NC-12")
    combined = harness + tests
    if "unittest.mock" in combined or '":memory:"' in combined:
        errors.append("Stage 2 acceptance uses a mock or in-memory database")
    return errors


def validate_claims_and_documents() -> list[str]:
    claims = load_json("part2/stage2/docs/claims.json")
    by_id = {row["id"]: row for row in claims.get("claims", [])}
    expected = {
        "application_effect_crash_restart": "LOCAL_VERIFIED",
        "production_consumer_local": "LOCAL_VERIFIED",
        "aws_adapter_request_shapes": "DESIGN_ONLY",
        "managed_consumer": "UNCLAIMED",
        "durable_aws_recovery": "UNCLAIMED",
        "raw_archive_completeness": "UNCLAIMED",
        "transport_exactly_once": "UNCLAIMED",
    }
    errors = []
    if {key: row.get("level") for key, row in by_id.items()} != expected:
        errors.append("Stage 2 claim registry exceeds or differs from its ceiling")
    proof = load_json("part2/stage2/docs/proof-matrix.json")
    rows = proof.get("proofs", [])
    if len(rows) != 1 or rows[0].get("requirement_id") != "EP-FUTURE-P2-002":
        errors.append("Stage 2 proof matrix is not singular and exact")
    documents = "\n".join(
        (ROOT / relative).read_text(encoding="utf-8")
        for relative in (
            "part2/stage2/docs/status.md",
            "part2/stage2/docs/known-limits.md",
            "part2/stage2/docs/INTERVIEW.md",
            "part2/stage2/docs/decisions/process-death-proof.md",
        )
    )
    for marker in (
        "LOCAL_VERIFIED",
        "DESIGN_ONLY",
        "UNCLAIMED",
        "EP-CRASH-08",
        "different process",
        "managed AWS",
        "EP-FUTURE-P2-003",
    ):
        if marker.lower() not in documents.lower():
            errors.append(f"Stage 2 documentation omits {marker}")
    return errors


def _git_blob(revision: str, relative: str) -> bytes:
    return subprocess.check_output(  # noqa: S603 - fixed git executable and reviewed revision
        [GIT, "show", f"{revision}:{relative}"], cwd=ROOT
    )


def validate_predecessor_manifest() -> list[str]:
    manifest_path = "evidence/part2/stage1/manifest.json"
    try:
        manifest = json.loads(_git_blob(BASE_SHA, manifest_path))
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return ["cannot load the immutable Stage 1 manifest from predecessor"]
    errors = []
    for row in manifest.get("artifacts", []):
        relative = str(row["path"])
        try:
            body = _git_blob(BASE_SHA, relative)
        except subprocess.CalledProcessError:
            errors.append(f"Stage 1 predecessor lacks manifest artifact {relative}")
            continue
        if hashlib.sha256(body).hexdigest() != row.get("sha256"):
            errors.append(f"Stage 1 predecessor manifest mismatch for {relative}")
    return errors


def validate_changed_files() -> list[str]:
    allowed_exact = {
        ".github/workflows/part2-stage1-consumer.yml",
        ".github/workflows/part2-stage2-recovery.yml",
        "oracles/part2_stage2_recovery.py",
        "part2/stage2/oracles/part2_stage2_recovery.py",
        "src/eventpulse/aws.py",
        "src/eventpulse/handler.py",
        "src/eventpulse/local.py",
        "src/eventpulse/ports.py",
        "src/eventpulse/recovery.py",
    }
    allowed_prefixes = (
        "evidence/part2/stage2/",
        "fixtures/part2/stage2/",
        "part2/stage2/",
        "scripts/build_part2_stage2_",
        "scripts/compare_part2_stage2_",
        "scripts/run_part2_stage2_",
        "scripts/validate_part2_stage2.py",
        "tests/test_part2_stage2_",
    )
    changed = set(
        subprocess.check_output(  # noqa: S603 - fixed git command
            [GIT, "diff", "--name-only", BASE_SHA, "--"], cwd=ROOT, text=True
        ).splitlines()
    )
    changed.update(
        line[3:]
        for line in subprocess.check_output(  # noqa: S603 - fixed git command
            [GIT, "status", "--porcelain"], cwd=ROOT, text=True
        ).splitlines()
        if len(line) > 3
    )
    errors = []
    for relative in sorted(changed):
        if "__pycache__" in Path(relative).parts:
            continue
        allowed_prefix = any(relative.startswith(prefix) for prefix in allowed_prefixes)
        if relative in allowed_exact or allowed_prefix:
            continue
        errors.append(f"changed file outside Stage 2 allow-list: {relative}")
    requirements_changed = subprocess.run(  # noqa: S603 - fixed read-only git diff
        [GIT, "diff", "--quiet", BASE_SHA, "--", "requirements"], cwd=ROOT, check=False
    ).returncode
    if requirements_changed:
        errors.append("dependency declarations or locks changed without authorization")
    forbidden = ("ledger" + "guard", "change" + "bridge", "feature" + "forge")
    sensitive = re.compile(
        r"(?i)(?:account(?:_id)?[\s`'\":=]+[0-9]{12}|arn:aws:[^:]+:[^:]*:[0-9]{12}:|AKIA[0-9A-Z]{16})"
    )
    for relative in sorted(changed):
        path = ROOT / relative
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if any(name in text.lower() for name in forbidden):
            errors.append(f"foreign-project material in {relative}")
        if sensitive.search(text):
            errors.append(f"sensitive identifier in {relative}")
    return errors


def verify_source() -> list[str]:
    errors = []
    try:
        tree = subprocess.check_output(  # noqa: S603 - reviewed immutable SHA
            [GIT, "show", "-s", "--format=%T", BASE_SHA], cwd=ROOT, text=True
        ).strip()
        subprocess.run(  # noqa: S603 - reviewed immutable SHA
            [GIT, "merge-base", "--is-ancestor", BASE_SHA, "HEAD"],
            cwd=ROOT,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        return ["verified Stage 1 predecessor is not an ancestor of HEAD"]
    if tree != BASE_TREE:
        errors.append("verified predecessor tree mismatch")
    return errors


def validate_all(*, source: bool) -> list[str]:
    errors = []
    errors.extend(validate_requirements())
    errors.extend(validate_traceability())
    errors.extend(validate_fixtures_and_evidence())
    errors.extend(validate_oracle_isolation())
    errors.extend(validate_mechanism_and_controls())
    errors.extend(validate_claims_and_documents())
    errors.extend(validate_predecessor_manifest())
    errors.extend(validate_changed_files())
    if source:
        errors.extend(verify_source())
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-source", action="store_true")
    args = parser.parse_args()
    errors = validate_all(source=args.verify_source)
    if errors:
        for error in errors:
            print(error)
        return 1
    print("EventPulse Part 2 Stage 2 validation: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
