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


def read_json(root: Path, name: str, errors: list[str] | None = None) -> Any:
    """Read one observation document without letting missing evidence crash the oracle."""
    path = root / f"{name}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        if errors is not None:
            errors.append(f"unreadable JSON: {name}")
        return {}


def verify_manifest(root: Path) -> list[str]:
    errors: list[str] = []
    rows = read_json(root, "sha256-manifest", errors)
    if not isinstance(rows, list):
        return [*errors, "manifest is not a list"]
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("path"), str):
            errors.append("invalid manifest row")
            continue
        path = root / row["path"]
        if (
            not path.is_file()
            or path.stat().st_size != row.get("size_bytes")
            or hashlib.sha256(path.read_bytes()).hexdigest() != row.get("sha256")
        ):
            errors.append(f"digest mismatch: {row['path']}")
    return errors


def decide(root: Path) -> dict[str, Any]:
    errors = verify_manifest(root)
    statuses = read_json(root, "command-status", errors)
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
    if not isinstance(statuses, dict) or set(statuses) != required:
        errors.append("command status inventory mismatch")
        statuses = statuses if isinstance(statuses, dict) else {}
    errors.extend(f"command failed: {name}" for name, code in statuses.items() if code != 0)
    caller = read_json(root, "caller", errors)
    region = read_json(root, "region", errors)
    role_document = read_json(root, "role", errors)
    role = role_document.get("Role", {}) if isinstance(role_document, dict) else {}
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
    provider = read_json(root, "provider", errors)
    if EXPECTED_AUD not in provider.get("ClientIDList", []):
        errors.append("OIDC provider audience missing")
    attached_document = read_json(root, "attached", errors)
    inline_document = read_json(root, "inline", errors)
    resource_document = read_json(root, "tagged", errors)
    budget_document = read_json(root, "budgets", errors)
    attached = (
        attached_document.get("AttachedPolicies", []) if isinstance(attached_document, dict) else []
    )
    inline = inline_document.get("PolicyNames", []) if isinstance(inline_document, dict) else []
    resources = (
        resource_document.get("ResourceTagMappingList", [])
        if isinstance(resource_document, dict)
        else []
    )
    # A readable but empty permission set is a concrete NO_GO, not missing evidence.
    gaps = []
    if not attached and not inline:
        gaps.append("OIDC role has no workload or deployment policy")
    budget_count = (
        len(budget_document.get("Budgets", [])) if isinstance(budget_document, dict) else 0
    )
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
