"""Validate the bounded Stage 1 audit receipt using only the Python standard library."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "evidence/part1/stage1/manifest.json"
AUDIT = ROOT / "docs/audits/part1-stage1-exact-state.md"
STATUS = ROOT / "docs/STATUS.md"
COMPLETION = ROOT / "docs/audits/part1-stage1-completion.md"
SHA = re.compile(r"^[0-9a-f]{40}$")
ALLOWED_LEVELS = {
    "LOCAL_VERIFIED_ON_DRAFT_ONLY",
    "DESIGN_ONLY_ON_DRAFT_ONLY",
    "UNCLAIMED",
}


def validate(*, verify_source: bool = False) -> list[str]:
    errors: list[str] = []
    try:
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
        audit = AUDIT.read_text(encoding="utf-8")
        status = STATUS.read_text(encoding="utf-8")
    except (OSError, json.JSONDecodeError) as exc:
        return [f"audit input cannot be read: {exc}"]

    if data.get("project") != "eventpulse-realtime-engagement-platform":
        errors.append("wrong project")
    if data.get("stage") != "PART1_STAGE1_EXACT_STATE_AUDIT":
        errors.append("wrong stage")
    if data.get("status") not in {"IN_PROGRESS", "COMPLETED"}:
        errors.append("invalid audit status")

    source = data.get("source", {})
    draft = data.get("draft_pr", {})
    if not isinstance(source, dict) or not isinstance(draft, dict):
        return errors + ["source and draft_pr must be objects"]
    if source.get("repository") != "bhuvaneshwaranmurugan21/eventpulse-realtime-engagement-platform":
        errors.append("wrong source repository")
    if source.get("default_branch") != "main":
        errors.append("unexpected default branch")
    for key, value in (
        ("source.commit_sha", source.get("commit_sha")),
        ("source.tree_sha", source.get("tree_sha")),
        ("draft_pr.base_sha", draft.get("base_sha")),
        ("draft_pr.head_sha", draft.get("head_sha")),
        ("draft_pr.head_tree_sha", draft.get("head_tree_sha")),
    ):
        if not isinstance(value, str) or not SHA.fullmatch(value):
            errors.append(f"{key} must be a full SHA")
    if draft.get("base_sha") != source.get("commit_sha"):
        errors.append("draft base does not match source checkpoint")
    if draft.get("state") != "open" or draft.get("draft") is not True:
        errors.append("draft PR state contradicts audit")
    if draft.get("disposition") != "RETAIN_OPEN_DRAFT_FOR_SEPARATE_REVIEW":
        errors.append("draft disposition changed without reviewed audit")

    ci = data.get("ci")
    if not isinstance(ci, list) or len(ci) != 3:
        errors.append("expected three explicitly scoped historical CI runs")
    else:
        for run in ci:
            if not isinstance(run, dict) or run.get("conclusion") != "success":
                errors.append("CI run record malformed or not successful")
                continue
            if run.get("head_sha") not in {source.get("commit_sha"), draft.get("head_sha")}:
                errors.append("CI head not bound to audited source or draft")

    baseline = data.get("local_baseline", {})
    if not isinstance(baseline, dict):
        errors.append("local_baseline must be an object")
    elif baseline.get("simulation") == "PASS" and baseline.get(
        "committed_simulation_sha256"
    ) != baseline.get("regenerated_simulation_sha256"):
        errors.append("simulation cannot pass with unequal SHA-256 digests")

    isolation = data.get("isolation", {})
    if not isinstance(isolation, dict):
        errors.append("isolation must be an object")
    elif isolation.get("verification") == "PENDING":
        for key in ("observed_account", "observed_region", "current_role_trust", "resource_inventory"):
            if isolation.get(key) != "UNKNOWN":
                errors.append(f"{key} requires separately reviewed read-only evidence")
        if "AWS_IDENTITY_AND_OWNERSHIP_BOUNDARY_UNVERIFIED" not in data.get("blockers", []):
            errors.append("AWS isolation blocker cannot be omitted while observations are unknown")
    elif isolation.get("verification") == "SCOPED_READ_ONLY_VERIFIED":
        if not re.fullmatch(r"[0-9a-f]{64}", str(isolation.get("private_evidence_sha256", ""))):
            errors.append("verified isolation requires a private evidence SHA-256")
        if not re.fullmatch(r"[0-9]{12}", str(isolation.get("observed_account", ""))):
            errors.append("verified isolation requires a 12-digit observed account")
        if isolation.get("private_evidence_manifest_verified") is not True:
            errors.append("verified isolation requires checked private evidence entries")
        variables = isolation.get("github_repository_variables", {})
        if variables:
            if not isinstance(variables, dict) or variables.get("role_arn_account_matches_observed_account") is not True:
                errors.append("GitHub role ARN account binding is not verified")
            elif not re.fullmatch(r"[0-9a-f]{64}", str(variables.get("screenshot_sha256", ""))):
                errors.append("GitHub variable observation requires private screenshot digest")
            elif variables.get("observed_region") != isolation.get("observed_region"):
                errors.append("GitHub region does not match the audited AWS region")
        if isolation.get("observed_region") in (None, "UNKNOWN"):
            errors.append("verified isolation requires observed region")
        if isolation.get("current_role_trust") != "VERIFIED":
            errors.append("verified isolation requires role trust observation")
        if isolation.get("resource_inventory") not in ("PRESENT", "ABSENT", "PARTIAL_WITH_UNKNOWNS"):
            errors.append("verified isolation requires a classified resource inventory")
        if isolation.get("resource_inventory") == "PARTIAL_WITH_UNKNOWNS" and (
            "UNTAGGED_OR_DIFFERENTLY_NAMED_RESOURCES_NOT_EXCLUDED" not in data.get("unknowns", [])
        ):
            errors.append("partial inventory requires an explicit scope unknown")
        if "AWS_IDENTITY_AND_OWNERSHIP_BOUNDARY_UNVERIFIED" in data.get("blockers", []):
            errors.append("verified isolation conflicts with unresolved identity blocker")
    else:
        errors.append("isolation verification state is invalid")

    claims = data.get("claim_boundaries")
    if not isinstance(claims, list) or {c.get("id") for c in claims if isinstance(c, dict)} != {
        "local_streaming_kernel", "terraform_topology", "managed_consumer",
        "aws_workload_and_latency", "exactly_once_transport",
    }:
        errors.append("claim boundary inventory is incomplete")
    elif any(c.get("level") not in ALLOWED_LEVELS for c in claims):
        errors.append("claim boundary has unsupported level")
    if source.get("commit_sha", "") not in audit or draft.get("head_sha", "") not in audit:
        errors.append("audit text does not reference both exact commits")
    if data.get("status") == "IN_PROGRESS":
        if "IN PROGRESS" not in audit or "IN PROGRESS" not in status:
            errors.append("public status conflicts with pending gates")
    else:
        completion = data.get("completion", {})
        try:
            receipt = COMPLETION.read_text(encoding="utf-8")
        except OSError as exc:
            receipt = ""
            errors.append(f"completion receipt cannot be read: {exc}")
        if data.get("blockers") != []:
            errors.append("completed audit cannot retain a stage blocker")
        if not isinstance(completion, dict):
            errors.append("completion must be an object")
        else:
            for key in ("reviewed_audit_head_sha", "audit_merge_sha", "verified_main_sha", "verified_main_tree_sha"):
                if not SHA.fullmatch(str(completion.get(key, ""))):
                    errors.append(f"completion {key} must be a full SHA")
            if completion.get("post_merge_ci_conclusion") != "success" or completion.get("post_merge_ci_job") != "audit":
                errors.append("post-merge audit CI must have succeeded")
            if completion.get("post_merge_ci_run_id") != 36038011108 or completion.get("verified_main_file_count") != 6:
                errors.append("post-merge evidence receipt is incomplete")
            if completion.get("verified_main_sha", "") not in receipt or str(completion.get("post_merge_ci_run_id")) not in receipt:
                errors.append("completion receipt does not bind main and CI")
            if completion.get("verified_main_sha", "") not in status or "COMPLETED" not in status or "COMPLETED" not in audit:
                errors.append("public completion status is inconsistent")
    if re.search(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b", audit + status):
        errors.append("possible AWS access key in public audit text")

    if verify_source and not errors:
        source_sha = source["commit_sha"]
        try:
            tree = subprocess.check_output(
                ["git", "rev-parse", f"{source_sha}^{{tree}}"], cwd=ROOT, text=True
            ).strip()
            subprocess.run(
                ["git", "merge-base", "--is-ancestor", source_sha, "HEAD"],
                cwd=ROOT, check=True, capture_output=True,
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            errors.append(f"source commit is unavailable or not an ancestor: {exc}")
        else:
            if tree != source["tree_sha"]:
                errors.append("source commit tree does not match receipt")
    return errors


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-source", action="store_true")
    args = parser.parse_args()
    failures = validate(verify_source=args.verify_source)
    if failures:
        for failure in failures:
            print(f"ERROR: {failure}", file=sys.stderr)
        raise SystemExit(1)
    print(f"Stage 1 audit receipt: internally consistent; status={json.loads(MANIFEST.read_text())['status']}")
