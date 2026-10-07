#!/usr/bin/env python3
"""Independent fail-closed oracle for the Stage 2 AWS admission observation."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
AUTHORITY_PATH = ROOT / "part3/stage2/admission/authority.json"
POLICY_PATH = ROOT / "part3/stage2/admission/expected-read-policy.json"
BACKEND_PATH = ROOT / "part3/stage2/admission/backend-and-lease.json"
COST_PATH = ROOT / "part3/stage2/admission/cost-envelope.json"
EXPECTED_COMMANDS = {
    "alarms",
    "attached",
    "buckets",
    "budgets",
    "caller",
    "functions",
    "inline",
    "inline_policy",
    "logs",
    "provider",
    "providers",
    "quota_dynamodb",
    "quota_kinesis",
    "quota_lambda",
    "queues",
    "region",
    "role",
    "role_tags",
    "streams",
    "tables",
    "tagged",
}
EXPECTED_PRICE_CODES = {
    "AmazonCloudWatch",
    "AmazonDynamoDB",
    "AmazonKinesis",
    "AmazonS3",
    "AWSLambda",
    "AWSQueueService",
}


def strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=strict_object)


def canonical(value: Any) -> bytes:
    return (json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n").encode()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def exact_singleton(value: Any, expected: str) -> bool:
    return value == expected or (
        isinstance(value, list) and len(value) == 1 and value[0] == expected
    )


def parse_time(value: Any) -> dt.datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def trust_errors(role: Any, authority: dict[str, Any]) -> list[str]:
    if not isinstance(role, dict):
        return ["role observation is not an object"]
    errors: list[str] = []
    if role.get("name") != authority["role_name"]:
        errors.append("role name mismatch")
    if role.get("arn") != authority["role_arn"]:
        errors.append("role ARN mismatch")
    if role.get("max_session_duration") != 3600:
        errors.append("unexpected role maximum session duration")
    tags = role.get("tags")
    expected_tags = {
        "ManagedBy": "EventPulseBootstrap",
        "Project": "EventPulse",
        "Purpose": "GitHubOIDC",
    }
    actual_tags = (
        {item.get("Key"): item.get("Value") for item in tags if isinstance(item, dict)}
        if isinstance(tags, list)
        else {}
    )
    if actual_tags != expected_tags:
        errors.append("role tag boundary mismatch")
    trust = role.get("trust")
    if not isinstance(trust, dict) or set(trust) != {"Statement", "Version"}:
        return [*errors, "trust root inventory mismatch"]
    if trust.get("Version") != "2012-10-17":
        errors.append("trust version mismatch")
    statements = trust.get("Statement")
    if not isinstance(statements, list) or len(statements) != 1:
        return [*errors, "trust must have exactly one statement"]
    statement = statements[0]
    allowed_keys = {"Action", "Condition", "Effect", "Principal", "Sid"}
    if not isinstance(statement, dict) or set(statement) != allowed_keys:
        return [*errors, "trust statement inventory mismatch"]
    if statement.get("Sid") != "EventPulseMainOnly":
        errors.append("trust statement Sid mismatch")
    if statement.get("Effect") != "Allow":
        errors.append("trust effect mismatch")
    if not exact_singleton(statement.get("Action"), "sts:AssumeRoleWithWebIdentity"):
        errors.append("trust action mismatch")
    principal = statement.get("Principal")
    if (
        not isinstance(principal, dict)
        or set(principal) != {"Federated"}
        or not exact_singleton(principal.get("Federated"), authority["provider_arn"])
    ):
        errors.append("trust principal mismatch or broadened")
    condition = statement.get("Condition")
    if not isinstance(condition, dict) or set(condition) != {"StringEquals"}:
        return [*errors, "trust condition inventory mismatch"]
    equals = condition.get("StringEquals")
    expected = {
        f"{authority['oidc_provider']}:aud": authority["audience"],
        f"{authority['oidc_provider']}:sub": authority["required_subject"],
    }
    if not isinstance(equals, dict) or set(equals) != set(expected):
        return [*errors, "trust equality inventory mismatch"]
    for key, value in expected.items():
        if not exact_singleton(equals.get(key), value):
            errors.append(f"trust value mismatch or broadened: {key}")
    return errors


def quota_gaps(quotas: Any) -> list[str]:
    gaps: list[str] = []
    if not isinstance(quotas, dict) or set(quotas) != {"dynamodb", "kinesis", "lambda"}:
        return ["quota service inventory mismatch"]
    relevant = {
        "dynamodb": ("table", "capacity", "write", "read"),
        "kinesis": ("shard", "stream"),
        "lambda": ("concurrent execution",),
    }
    for service, tokens in relevant.items():
        payload = quotas.get(service)
        entries = payload.get("entries", []) if isinstance(payload, dict) else []
        if payload.get("entry_count") != len(entries) or not entries:
            gaps.append(f"{service} quota inventory is empty")
            continue
        candidates = [
            row
            for row in entries
            if isinstance(row, dict)
            and any(token in str(row.get("name", "")).lower() for token in tokens)
            and isinstance(row.get("value"), (int, float))
            and not isinstance(row.get("value"), bool)
            and row["value"] > 0
        ]
        if not candidates:
            gaps.append(f"{service} has no positive workload-relevant quota")
    return gaps


def decide(observation: Any, *, now: dt.datetime | None = None) -> dict[str, Any]:
    authority = load_json(AUTHORITY_PATH)
    expected_policy = load_json(POLICY_PATH)
    backend = load_json(BACKEND_PATH)
    cost = load_json(COST_PATH)
    errors: list[str] = []
    gaps: list[str] = []
    if not isinstance(observation, dict):
        return {
            "decision": "INDETERMINATE",
            "errors": ["observation root is not an object"],
            "gaps": [],
            "schema": "eventpulse-part3-stage2-admission-decision-v1",
            "stage2_gate": "BLOCKED",
        }
    if observation.get("schema") != "eventpulse-part3-stage2-admission-observation-v1":
        errors.append("observation schema mismatch")
    if observation.get("authority") != authority["authority"]:
        errors.append("authority mismatch")
    if observation.get("claim_ceiling") != "DESIGN_ONLY":
        errors.append("claim ceiling mismatch")
    if observation.get("account_id") != authority["account_id"]:
        errors.append("Management account identity mismatch")
    if observation.get("region") != authority["region"]:
        errors.append("region identity mismatch")
    if observation.get("region_status") != "ENABLED":
        errors.append("ap-south-2 is not enabled")
    if observation.get("ref") != authority["github_ref"]:
        errors.append("observation was not collected from main")
    if not re.fullmatch(r"[0-9a-f]{40}", str(observation.get("source_sha", ""))):
        errors.append("source SHA is not exact")
    if not re.fullmatch(r"[0-9a-f]{40}", str(observation.get("source_tree", ""))):
        errors.append("source tree is not exact")

    current = now or dt.datetime.now(dt.UTC)
    observed = parse_time(observation.get("observed_at_utc"))
    expires = parse_time(observation.get("expires_at_utc"))
    if observed is None or expires is None:
        errors.append("freshness timestamps are invalid")
    elif observed > current + dt.timedelta(minutes=5):
        errors.append("observation timestamp is in the future")
    elif current > expires or expires - observed != dt.timedelta(hours=24):
        errors.append("observation is stale or has the wrong freshness window")

    github = observation.get("github")
    expected_claims = {
        "aud": authority["audience"],
        "iss": "https://token.actions.githubusercontent.com",
        "ref": authority["github_ref"],
        "repository": authority["repository"],
        "repository_id": authority["repository_id"],
        "repository_owner": authority["repository_owner"],
        "repository_owner_id": authority["repository_owner_id"],
        "sub": authority["required_subject"],
    }
    if not isinstance(github, dict):
        errors.append("GitHub OIDC claim observation is missing")
    else:
        for key, value in expected_claims.items():
            if str(github.get(key)) != value:
                errors.append(f"GitHub OIDC claim mismatch: {key}")
        workflow_ref = github.get("job_workflow_ref")
        if not isinstance(workflow_ref, str) or not workflow_ref.endswith(
            "/.github/workflows/part3-stage2-admission-requalification.yml@refs/heads/main"
        ):
            errors.append("GitHub workflow claim mismatch")

    provider = observation.get("provider")
    if not isinstance(provider, dict):
        errors.append("OIDC provider observation missing")
    else:
        if provider.get("url") != authority["oidc_provider"]:
            errors.append("OIDC provider URL mismatch")
        if provider.get("audiences") != [authority["audience"]]:
            errors.append("OIDC provider audience is missing or broadened")
        if provider.get("listed_arns") != [authority["provider_arn"]]:
            errors.append("OIDC provider inventory mismatch")
        if provider.get("thumbprint_count") != 1:
            errors.append("OIDC provider thumbprint inventory mismatch")

    errors.extend(trust_errors(observation.get("role"), authority))
    policy = observation.get("policy")
    if not isinstance(policy, dict):
        errors.append("role policy observation missing")
    else:
        if policy.get("attached") != []:
            errors.append("managed policy attachment is not allowed")
        if policy.get("inline_names") != [authority["inline_policy_name"]]:
            errors.append("inline policy inventory mismatch")
        if policy.get("inline_policy_name") != authority["inline_policy_name"]:
            errors.append("inline policy name mismatch")
        if canonical(policy.get("inline_policy")) != canonical(expected_policy):
            errors.append("read-only inline policy content mismatch")

    commands = observation.get("commands")
    statuses = commands.get("statuses", {}) if isinstance(commands, dict) else {}
    if set(statuses) != EXPECTED_COMMANDS or commands.get("attempted") != len(EXPECTED_COMMANDS):
        errors.append("read-only command inventory mismatch")
    if commands.get("failures") != [] or any(value != 0 for value in statuses.values()):
        errors.append("one or more read-only observations failed")

    inventory = observation.get("inventory")
    collision_keys = {
        "alarm_collision_count",
        "bucket_collision_count",
        "function_collision_count",
        "log_group_collision_count",
        "queue_collision_count",
        "stream_collision_count",
        "table_collision_count",
        "tagged_eventpulse_count",
    }
    if not isinstance(inventory, dict) or not collision_keys.issubset(inventory):
        errors.append("resource collision inventory is incomplete")
    else:
        for key in collision_keys:
            if type(inventory.get(key)) is not int or inventory[key] < 0:
                errors.append(f"invalid collision count: {key}")
            elif inventory[key] != 0:
                gaps.append(f"existing EventPulse resource collision: {key}")
        if inventory.get("pagination_complete") is not True:
            errors.append("resource inventory pagination is incomplete")

    gaps.extend(quota_gaps(observation.get("quotas")))
    budget = observation.get("budget")
    if not isinstance(budget, dict) or budget.get("readable") is not True:
        errors.append("budget inventory is unreadable")
    else:
        eventpulse_budgets = budget.get("eventpulse_budgets", [])
        if budget.get("eventpulse_budget_count") != len(eventpulse_budgets):
            errors.append("EventPulse budget count mismatch")
        acceptable_budget = False
        for item in eventpulse_budgets:
            try:
                amount = float(item.get("amount"))
            except (AttributeError, TypeError, ValueError):
                continue
            acceptable_budget = acceptable_budget or (
                item.get("currency") == "USD"
                and item.get("type") == "COST"
                and amount <= float(cost["hard_cap_usd"])
            )
        if not acceptable_budget:
            gaps.append("no EventPulse USD cost budget at or below the hard cap")

    if observation.get("backend_digest") != digest(BACKEND_PATH):
        errors.append("backend and lease authority digest mismatch")
    if (
        backend.get("backend", {}).get("mode") != "local-disposable-plan-only"
        or backend.get("lease", {}).get("steal_policy")
        != "cancel-in-progress is false; a later run waits and never steals"
        or backend.get("terraform_apply") is not False
    ):
        errors.append("backend or lease authority is unsafe")

    if observation.get("cost_digest") != digest(COST_PATH):
        errors.append("cost envelope digest mismatch")
    components = cost.get("components", [])
    component_total = sum(float(item.get("upper_bound_usd", 0)) for item in components)
    if abs(component_total - float(cost.get("forecast_total_usd", -1))) > 1e-9:
        errors.append("cost arithmetic mismatch")
    if not (
        float(cost.get("forecast_total_usd", 999))
        < float(cost.get("admission_ceiling_usd", -1))
        < float(cost.get("hard_cap_usd", -1))
        == 12.0
    ):
        errors.append("cost thresholds are invalid or exceeded")
    price_sources = observation.get("price_sources")
    if not isinstance(price_sources, dict) or set(price_sources) != EXPECTED_PRICE_CODES:
        errors.append("regional price-source inventory mismatch")
    else:
        for code, item in price_sources.items():
            if not isinstance(item, dict) or item.get("error") is not None:
                errors.append(f"regional price source unavailable: {code}")
                continue
            if item.get("format_version") != "v1.0":
                errors.append(f"regional price format mismatch: {code}")
            if not re.fullmatch(r"[0-9a-f]{64}", str(item.get("sha256", ""))):
                errors.append(f"regional price digest missing: {code}")
            publication = parse_time(item.get("publication_date"))
            if publication is None or publication > current + dt.timedelta(days=1):
                errors.append(f"regional price publication invalid: {code}")

    if observation.get("raw_evidence_committed") is not False:
        errors.append("raw AWS evidence must remain uncommitted")
    if errors:
        decision = "INDETERMINATE"
    elif gaps:
        decision = "NO_GO"
    else:
        decision = "ADMITTED"
    return {
        "account_id": observation.get("account_id"),
        "authority": authority["authority"],
        "decision": decision,
        "errors": sorted(set(errors)),
        "expires_at_utc": observation.get("expires_at_utc"),
        "gaps": sorted(set(gaps)),
        "observed_at_utc": observation.get("observed_at_utc"),
        "region": observation.get("region"),
        "schema": "eventpulse-part3-stage2-admission-decision-v1",
        "source_sha": observation.get("source_sha"),
        "source_tree": observation.get("source_tree"),
        "stage2_gate": "OPEN" if decision == "ADMITTED" else "BLOCKED",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("observation", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--require-admitted", action="store_true")
    args = parser.parse_args()
    result = decide(load_json(args.observation))
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return int(args.require_admitted and result["decision"] != "ADMITTED")


if __name__ == "__main__":
    raise SystemExit(main())
