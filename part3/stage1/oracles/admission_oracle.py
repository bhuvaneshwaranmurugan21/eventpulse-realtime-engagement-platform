#!/usr/bin/env python3
"""Independent standard-library oracle for a private Stage 1 observation directory."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

EXPECTED_ACCOUNT = "773994909635"
EXPECTED_REGION = "ap-south-2"
EXPECTED_ROLE = "EventPulseGitHubOidcRole"
EXPECTED_PROVIDER = "token.actions.githubusercontent.com"
EXPECTED_AUD = "sts.amazonaws.com"
EXPECTED_SUB = (
    "repo:bhuvaneshwaranmurugan21/eventpulse-realtime-engagement-platform:ref:refs/heads/main"
)


def read_json(root: Path, name: str) -> Any:
    return json.loads((root / f"{name}.json").read_text(encoding="utf-8"))


def verify_manifest(root: Path) -> list[str]:
    errors: list[str] = []
    rows = read_json(root, "sha256-manifest")
    for row in rows:
        path = root / row["path"]
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
            errors.append(f"digest mismatch: {row['path']}")
    return errors


def decide(root: Path) -> dict[str, Any]:
    errors = verify_manifest(root)
    statuses = read_json(root, "command-status")
    required = {
        "caller",
        "region",
        "providers",
        "provider",
        "role",
        "attached",
        "inline",
        "role_tags",
        "tagged",
        "logs",
        "streams",
        "functions",
        "tables",
        "buckets",
        "queues",
        "quota_kinesis",
        "quota_lambda",
        "quota_dynamodb",
        "alarms",
        "budgets",
    }
    if set(statuses) != required:
        errors.append("command status inventory mismatch")
    errors.extend(f"command failed: {name}" for name, code in statuses.items() if code != 0)
    caller = read_json(root, "caller")
    region = read_json(root, "region")
    role = read_json(root, "role").get("Role", {})
    trust = role.get("AssumeRolePolicyDocument", {})
    trust_text = json.dumps(trust, sort_keys=True)
    if caller.get("Account") != EXPECTED_ACCOUNT:
        errors.append("account mismatch")
    if region.get("RegionName") != EXPECTED_REGION or region.get("RegionOptStatus") != "ENABLED":
        errors.append("region mismatch or disabled")
    if role.get("RoleName") != EXPECTED_ROLE:
        errors.append("role mismatch")
    for token in (EXPECTED_PROVIDER, EXPECTED_AUD, EXPECTED_SUB):
        if token not in trust_text:
            errors.append(f"trust missing: {token}")
    provider = read_json(root, "provider")
    if EXPECTED_AUD not in provider.get("ClientIDList", []):
        errors.append("OIDC provider audience missing")
    attached = read_json(root, "attached").get("AttachedPolicies", [])
    inline = read_json(root, "inline").get("PolicyNames", [])
    resources = read_json(root, "tagged").get("ResourceTagMappingList", [])
    # A readable but empty permission set is a concrete NO_GO, not missing evidence.
    gaps = []
    if not attached and not inline:
        gaps.append("OIDC role has no workload or deployment policy")
    budget_count = len(read_json(root, "budgets").get("Budgets", []))
    if budget_count == 0:
        gaps.append("no readable account budget")
    if errors:
        decision = "INDETERMINATE"
    elif gaps:
        decision = "NO_GO"
    else:
        decision = "ADMITTED"
    return {
        "account_match": caller.get("Account") == EXPECTED_ACCOUNT,
        "attached_policy_count": len(attached),
        "budget_count": budget_count,
        "decision": decision,
        "errors": sorted(errors),
        "gaps": sorted(gaps),
        "inline_policy_count": len(inline),
        "region_enabled": region.get("RegionOptStatus") == "ENABLED",
        "resource_tag_match_count": len(resources),
        "schema": "eventpulse-part3-stage1-admission-v1",
    }


if __name__ == "__main__":
    print(json.dumps(decide(Path(sys.argv[1])), indent=2, sort_keys=True))
