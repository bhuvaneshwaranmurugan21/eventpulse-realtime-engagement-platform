#!/usr/bin/env python3
"""Fail-closed structural validator for the Stage 2 admission authority."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import shutil
import subprocess  # nosec B404
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BASE_SHA = "8108f789b8333b0856470d465c871ab6b6d41130"
BASE_TREE = "9f1d38410a0bb92ebdcb86f0ee088fc8ae1f981c"
GIT = shutil.which("git") or "git"
EXPECTED_ACTIONS = {
    "account:GetRegionOptStatus",
    "budgets:DescribeBudgets",
    "cloudwatch:DescribeAlarms",
    "dynamodb:ListTables",
    "iam:GetOpenIDConnectProvider",
    "iam:GetRole",
    "iam:GetRolePolicy",
    "iam:ListAttachedRolePolicies",
    "iam:ListOpenIDConnectProviders",
    "iam:ListRolePolicies",
    "iam:ListRoleTags",
    "kinesis:ListStreams",
    "lambda:ListFunctions",
    "logs:DescribeLogGroups",
    "resourcegroupstaggingapi:GetResources",
    "s3:ListAllMyBuckets",
    "servicequotas:ListServiceQuotas",
    "sqs:ListQueues",
    "sts:GetCallerIdentity",
}


def load(relative: str) -> Any:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def flatten_actions(policy: dict[str, Any]) -> set[str]:
    actions: set[str] = set()
    for statement in policy.get("Statement", []):
        value = statement.get("Action", [])
        actions.update([value] if isinstance(value, str) else value)
    return actions


def validate() -> list[str]:
    errors: list[str] = []
    requirements = load("part3/stage2/admission/requirements.json")
    authority = load("part3/stage2/admission/authority.json")
    backend = load("part3/stage2/admission/backend-and-lease.json")
    cost = load("part3/stage2/admission/cost-envelope.json")
    policy = load("part3/stage2/admission/expected-read-policy.json")
    manifest = load("evidence/part3/stage2/admission-manifest.json")
    criteria = requirements.get("criteria", [])
    if len(criteria) != 30 or len(set(criteria)) != 30:
        errors.append("Stage 2 admission criteria registry drift")
    if (
        requirements.get("predecessor_main") != BASE_SHA
        or requirements.get("predecessor_tree") != BASE_TREE
        or manifest.get("predecessor_main") != BASE_SHA
        or manifest.get("predecessor_tree") != BASE_TREE
    ):
        errors.append("Stage 2 admission predecessor drift")
    if (
        authority.get("account_label") != "Management account"
        or authority.get("account_id") != "773994909635"
        or authority.get("region") != "ap-south-2"
    ):
        errors.append("Management account boundary drift")
    if authority.get("required_subject") != (
        "repo:bhuvaneshwaranmurugan21@276895096/"
        "eventpulse-realtime-engagement-platform@1333031049:ref:refs/heads/main"
    ):
        errors.append("repository-ID-bound OIDC subject drift")
    actions = flatten_actions(policy)
    if actions != EXPECTED_ACTIONS or any("*" in action for action in actions):
        errors.append("read-only permission action inventory drift")
    if any(statement.get("Effect") != "Allow" for statement in policy.get("Statement", [])):
        errors.append("unexpected policy effect")
    if (
        backend.get("apply_authorized") is not False
        or backend.get("terraform_apply") is not False
        or backend.get("backend", {}).get("remote_initialization_allowed") is not False
        or backend.get("lease", {}).get("maximum_minutes") != 20
    ):
        errors.append("backend/apply/lease boundary drift")
    components = cost.get("components", [])
    forecast = sum(float(item.get("upper_bound_usd", 0)) for item in components)
    if (
        abs(forecast - float(cost.get("forecast_total_usd", -1))) > 1e-9
        or not forecast < float(cost.get("admission_ceiling_usd", -1))
        or cost.get("hard_cap_usd") != 12.0
    ):
        errors.append("cost envelope arithmetic or threshold drift")

    collector_text = (ROOT / "scripts/collect_part3_stage2_admission.py").read_text()
    forbidden = (
        "apply",
        "create-",
        "delete-",
        "put-role-policy",
        "update-",
        "tag-resource",
        "untag-resource",
    )
    for token in forbidden:
        if f'"{token}' in collector_text.lower() or f"'{token}" in collector_text.lower():
            errors.append(f"forbidden collector mutation token: {token}")
    oracle_tree = ast.parse(
        (ROOT / "part3/stage2/admission/admission_oracle.py").read_text(encoding="utf-8")
    )
    for node in ast.walk(oracle_tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = (
                [item.name for item in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
            )
            if any(name.startswith(("boto", "botocore", "eventpulse")) for name in names):
                errors.append("independent admission oracle imports production or AWS SDK")

    rows = manifest.get("artifacts", [])
    paths = [row.get("path") for row in rows]
    if paths != sorted(set(paths)):
        errors.append("Stage 2 admission manifest paths are not sorted and unique")
    if "README.md" not in paths:
        errors.append("README presentation artifact is missing from the admission manifest")
    for row in rows:
        path = ROOT / row["path"]
        if (
            not path.is_file()
            or path.stat().st_size != row.get("size_bytes")
            or hashlib.sha256(path.read_bytes()).hexdigest() != row.get("sha256")
        ):
            errors.append(f"Stage 2 admission manifest mismatch: {row['path']}")

    changed = set(
        subprocess.check_output(  # nosec B603  # noqa: S603
            [GIT, "diff", "--name-only", BASE_SHA, "--"], cwd=ROOT, text=True
        ).splitlines()
    )
    allowed_prefixes = (
        "evidence/part3/stage2/",
        "part3/stage2/admission/",
    )
    allowed_exact = {
        "README.md",
        ".github/workflows/part3-stage1-aws-admission.yml",
        ".github/workflows/part3-stage2-admission-requalification.yml",
        "evidence/part3/stage1/manifest.json",
        "scripts/build_part3_stage2_admission_manifest.py",
        "scripts/collect_part3_stage2_admission.py",
        "scripts/validate_part3_stage2_admission.py",
        "tests/test_part3_stage2_admission.py",
    }
    errors.extend(
        f"out-of-scope admission file: {item}"
        for item in changed
        if item not in allowed_exact and not item.startswith(allowed_prefixes)
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
        if tree != BASE_TREE:
            errors.append("predecessor tree identity failed")
        if subprocess.run(  # nosec B603  # noqa: S603
            [GIT, "merge-base", "--is-ancestor", BASE_SHA, "HEAD"], cwd=ROOT
        ).returncode:
            errors.append("predecessor is not an ancestor")
    if errors:
        print("\n".join(errors))
        return 1
    print("EventPulse Part 3 Stage 2 admission authority: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
