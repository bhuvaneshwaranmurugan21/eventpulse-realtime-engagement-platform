#!/usr/bin/env python3
"""Fail-closed structural validator for EventPulse Part 2 Stage 1."""

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
BASE_SHA = "c642c281c3306356f26f3749ea7e8f92f45623d1"
BASE_TREE = "d2a6db927f3055d0fcddb0af4fdf1dd7d91c2419"
AUTHORITY_HEAD = "482731740a7a733099555803c20e4d25596e6319"
AUTHORITY_TREE = "a500a94a1d6f56741ce90551f4161ddba2600436"
MERGED_MAIN = "0467dfe44f6fcd9615edf20b057870c817356f20"
EXACT_HEAD_RUN = "36303643491"
MERGED_MAIN_RUN = "36303700963"
EXPECTED_AC = {f"P2S1-AC-{number:02d}" for number in range(1, 33)}
GIT = shutil.which("git")
if GIT is None:
    raise RuntimeError("git executable is required for source-bound validation")


def load_json(relative: str) -> Any:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def validate_requirements(requirements: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if set(requirements.get("acceptance_checks", [])) != EXPECTED_AC:
        errors.append("Stage 1 requirements are not exactly AC-01 through AC-32")
    if requirements.get("claim_ceiling") != "LOCAL_VERIFIED":
        errors.append("Stage 1 claim ceiling must remain LOCAL_VERIFIED")
    expected = requirements.get("expected_predecessor", {})
    if expected.get("main_sha") != BASE_SHA or expected.get("main_tree") != BASE_TREE:
        errors.append("Stage 1 predecessor identity drift")
    return errors


def validate_traceability(traceability: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    mappings = traceability.get("mappings", [])
    ids = [row.get("id") for row in mappings]
    if len(ids) != 32 or set(ids) != EXPECTED_AC or len(ids) != len(set(ids)):
        errors.append("traceability does not cover every Stage 1 acceptance check exactly once")
    for row in mappings:
        for field in ("artifacts", "evidence", "tests"):
            values = row.get(field)
            if not isinstance(values, list) or not values:
                errors.append(f"{row.get('id')} has no {field}")
                continue
            for relative in values:
                if not (ROOT / relative).exists():
                    errors.append(f"{row.get('id')} references missing {relative}")
    return errors


def validate_schema_copy() -> list[str]:
    authority = load_json("contracts/engagement-event-v1.schema.json")
    packaged = load_json("src/eventpulse/resources/engagement-event-v1.schema.json")
    return [] if authority == packaged else ["packaged schema differs from contract authority"]


def validate_import_isolation() -> list[str]:
    errors: list[str] = []
    for path in sorted((ROOT / "src/eventpulse").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            if any(name == "oracles" or name.startswith("oracles.") for name in names):
                errors.append(f"production imports independent oracle: {path.relative_to(ROOT)}")
    harness = (ROOT / "scripts/run_part2_stage1_local.py").read_text(encoding="utf-8")
    if "create_handler(runtime)" not in harness:
        errors.append("local harness bypasses production handler factory")
    return errors


def validate_locks() -> list[str]:
    errors: list[str] = []
    pattern = re.compile(r"^[A-Za-z0-9_.-]+==[^ ]+ --hash=sha256:[0-9a-f]{64}$")
    for relative, minimum in (("requirements/runtime.lock", 10), ("requirements/dev.lock", 40)):
        lines = [
            line
            for line in (ROOT / relative).read_text(encoding="utf-8").splitlines()
            if line and not line.startswith("#")
        ]
        if len(lines) < minimum or any(not pattern.fullmatch(line) for line in lines):
            errors.append(f"{relative} is not an exact hash lock")
    dev = (ROOT / "requirements/dev.lock").read_text(encoding="utf-8").lower()
    for required in ("pip==26.2.1", "jsonschema==4.26.0", "boto3==1.43.102"):
        if required not in dev:
            errors.append(f"development lock missing {required}")
    return errors


def validate_evidence(evidence: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if evidence.get("production_entry") != "eventpulse.handler.create_handler":
        errors.append("evidence did not use production handler entry")
    if evidence.get("runs_compared") != 2 or evidence.get("network_calls") != 0:
        errors.append("evidence lacks two-run no-network determinism")
    result = evidence.get("result")
    if not isinstance(result, dict):
        return errors + ["handler result missing"]
    digest = hashlib.sha256(
        json.dumps(result, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode(
            "utf-8"
        )
    ).hexdigest()
    if digest != evidence.get("result_sha256"):
        errors.append("handler result digest mismatch")
    if result.get("handler_response") != {"batchItemFailures": []}:
        errors.append("vertical slice did not fully acknowledge after durable effects")
    state = result.get("state", {})
    if len(state.get("identity_ledger", [])) != 2:
        errors.append("vertical slice identity count mismatch")
    if len(state.get("quarantine", [])) != 1 or len(state.get("outbox", [])) != 1:
        errors.append("vertical slice poison authority count mismatch")
    return errors


def validate_claims(claims: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    by_id = {row["id"]: row for row in claims.get("claims", [])}
    expected = {
        "production_consumer_local",
        "aws_adapter_request_shapes",
        "application_effect_idempotency",
        "managed_consumer",
        "durable_aws_recovery",
        "raw_archive_completeness",
    }
    if set(by_id) != expected or len(by_id) != len(claims.get("claims", [])):
        errors.append("Part 2 Stage 1 claim registry is not exact")
    consumer = by_id.get("production_consumer_local")
    if consumer is None or consumer.get("level") != "LOCAL_VERIFIED":
        errors.append("local production consumer claim is absent")
    if by_id.get("aws_adapter_request_shapes", {}).get("level") != "DESIGN_ONLY":
        errors.append("AWS adapter request-shape claim must remain DESIGN_ONLY")
    for identifier in ("managed_consumer", "durable_aws_recovery", "raw_archive_completeness"):
        if by_id.get(identifier, {}).get("level") != "UNCLAIMED":
            errors.append(f"{identifier} must remain UNCLAIMED")
    if by_id.get("application_effect_idempotency", {}).get("level") != "DESIGN_ONLY":
        errors.append("application effect recovery must remain DESIGN_ONLY in Stage 1")
    if claims.get("claim_ceiling") != "LOCAL_VERIFIED":
        errors.append("Part 2 Stage 1 claim ceiling drift")
    if claims.get("status") != "COMPLETED":
        errors.append("Part 2 Stage 1 claims are not publication-complete")
    return errors


def validate_stage_documents() -> list[str]:
    errors: list[str] = []
    status = (ROOT / "part2/stage1/docs/status.md").read_text(encoding="utf-8")
    limits = (ROOT / "part2/stage1/docs/known-limits.md").read_text(encoding="utf-8")
    proof = load_json("part2/stage1/docs/proof-matrix.json")
    interview = (ROOT / "part2/stage1/docs/INTERVIEW.md").read_text(encoding="utf-8")
    completion = (ROOT / "part2/stage1/docs/audits/completion.md").read_text(
        encoding="utf-8"
    )
    if (
        BASE_SHA not in status
        or BASE_TREE not in status
        or MERGED_MAIN not in status
        or AUTHORITY_TREE not in status
        or "COMPLETED" not in status
    ):
        errors.append("Part 2 Stage 1 status is not bound to the verified publication")
    for marker in (
        "EVENTPULSE_PART2_STAGE1_VERIFIED",
        BASE_SHA,
        BASE_TREE,
        AUTHORITY_HEAD,
        AUTHORITY_TREE,
        MERGED_MAIN,
        EXACT_HEAD_RUN,
        MERGED_MAIN_RUN,
        "Stage 2 continuation checkpoint",
    ):
        if marker not in completion:
            errors.append(f"completion receipt omits {marker}")
    combined = "\n".join((status, limits, interview))
    for boundary in ("UNCLAIMED", "DESIGN_ONLY", "no network", "managed AWS"):
        if boundary.lower() not in combined.lower():
            errors.append(f"Part 2 Stage 1 documents omit boundary: {boundary}")
    rows = proof.get("proofs", [])
    if (
        proof.get("stage") != "PART2_STAGE1"
        or len(rows) != 1
        or rows[0].get("requirement_id") != "EP-FUTURE-P2-001"
        or rows[0].get("claim_level") != "LOCAL_VERIFIED"
        or proof.get("status") != "STAGE1_COMPLETED"
    ):
        errors.append("Part 2 Stage 1 proof matrix is not exact")
    return errors


def validate_public_boundary() -> list[str]:
    errors: list[str] = []
    forbidden = ("ledger" + "guard", "change" + "bridge", "feature" + "forge")
    sensitive = re.compile(
        r"(?i)(?:account(?:_id)?[\s`'\":=]+[0-9]{12}|arn:aws:[^:]+:[^:]*:[0-9]{12}:|AKIA[0-9A-Z]{16})"
    )
    changed = set(
        subprocess.check_output(  # noqa: S603 - absolute executable and fixed arguments
            [GIT, "diff", "--name-only", f"{BASE_SHA}..HEAD"], cwd=ROOT, text=True
        ).splitlines()
    )
    changed.update(
        line[3:]
        for line in subprocess.check_output(  # noqa: S603 - fixed git status command
            [GIT, "status", "--porcelain"], cwd=ROOT, text=True
        ).splitlines()
        if len(line) > 3
    )
    for relative_text in sorted(changed):
        path = ROOT / relative_text
        if not path.is_file() or ".git" in path.parts:
            continue
        relative = path.relative_to(ROOT)
        if relative.parts[0] in {"build", "dist"} or "__pycache__" in relative.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        lowered = text.lower()
        if any(name in lowered for name in forbidden):
            errors.append(f"foreign-project material in {relative}")
        if sensitive.search(text):
            errors.append(f"sensitive identifier in {relative}")
    return errors


def verify_source() -> list[str]:
    errors: list[str] = []
    try:
        tree = subprocess.check_output(  # noqa: S603 - reviewed immutable SHA argument
            [GIT, "show", "-s", "--format=%T", BASE_SHA], cwd=ROOT, text=True
        ).strip()
        subprocess.run(  # noqa: S603 - reviewed immutable SHA and HEAD arguments
            [GIT, "merge-base", "--is-ancestor", BASE_SHA, "HEAD"],
            cwd=ROOT,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ["verified predecessor is not an ancestor of HEAD"]
    if tree != BASE_TREE:
        errors.append("verified predecessor tree mismatch")
    return errors


def validate_all(*, source: bool) -> list[str]:
    errors = []
    errors.extend(validate_requirements(load_json("part2/stage1/docs/requirements.json")))
    errors.extend(validate_traceability(load_json("part2/stage1/docs/traceability.json")))
    errors.extend(validate_schema_copy())
    errors.extend(validate_import_isolation())
    errors.extend(validate_locks())
    errors.extend(validate_evidence(load_json("evidence/part2/stage1/handler-result.json")))
    errors.extend(validate_claims(load_json("part2/stage1/docs/claims.json")))
    errors.extend(validate_stage_documents())
    errors.extend(validate_public_boundary())
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
    print("EventPulse Part 2 Stage 1 validation: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
