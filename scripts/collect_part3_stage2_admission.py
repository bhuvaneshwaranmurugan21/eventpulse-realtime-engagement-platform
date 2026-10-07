#!/usr/bin/env python3
"""Collect a sanitized, read-only Stage 2 entry observation in GitHub Actions."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import subprocess  # nosec B404
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
AWS = shutil.which("aws") or "aws"
GIT = shutil.which("git") or "git"
ACCOUNT = "773994909635"
REGION = "ap-south-2"
BUDGETS_REGION = "us-east-1"
ROLE = "EventPulseGitHubOidcRole"
POLICY = "EventPulseAdmissionReadOnly"
PROVIDER_ARN = f"arn:aws:iam::{ACCOUNT}:oidc-provider/token.actions.githubusercontent.com"
PRICE_CODES = (
    "AmazonCloudWatch",
    "AmazonDynamoDB",
    "AmazonKinesis",
    "AmazonS3",
    "AWSLambda",
    "AWSQueueService",
)


def canonical(value: Any) -> bytes:
    return (json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n").encode()


def digest_file(relative: str) -> str:
    return hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()


def git_value(*args: str) -> str:
    return subprocess.check_output(  # nosec B603  # noqa: S603
        [GIT, *args], cwd=ROOT, text=True
    ).strip()


class Collector:
    def __init__(self, raw: Path) -> None:
        self.raw = raw
        self.status: dict[str, int] = {}
        self.documents: dict[str, Any] = {}

    def aws(self, name: str, *args: str) -> Any:
        completed = subprocess.run(  # nosec B603  # noqa: S603
            [AWS, *args, "--output", "json", "--no-cli-pager"],
            cwd=ROOT,
            env={**os.environ, "AWS_PAGER": "", "AWS_DEFAULT_REGION": REGION},
            capture_output=True,
            text=True,
            check=False,
        )
        self.status[name] = completed.returncode
        (self.raw / f"{name}.stdout").write_text(completed.stdout, encoding="utf-8")
        (self.raw / f"{name}.stderr").write_text(completed.stderr, encoding="utf-8")
        try:
            document = json.loads(completed.stdout) if completed.stdout.strip() else {}
        except json.JSONDecodeError:
            document = {}
        self.documents[name] = document
        return document


def collect_budgets(collector: Collector) -> Any:
    """Read the global Budgets inventory through a supported AWS endpoint."""
    return collector.aws(
        "budgets",
        "budgets",
        "describe-budgets",
        "--account-id",
        ACCOUNT,
        "--region",
        BUDGETS_REGION,
    )


def count_prefixed(values: list[Any], prefix: str) -> int:
    return sum(isinstance(value, str) and value.lower().startswith(prefix) for value in values)


def normalized_quotas(document: Any) -> dict[str, Any]:
    rows = document.get("Quotas", []) if isinstance(document, dict) else []
    normalized = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        value = row.get("Value")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            normalized.append(
                {
                    "adjustable": bool(row.get("Adjustable")),
                    "code": row.get("QuotaCode"),
                    "global": bool(row.get("GlobalQuota")),
                    "name": row.get("QuotaName"),
                    "unit": row.get("Unit"),
                    "value": value,
                }
            )
    return {
        "entry_count": len(normalized),
        "entries": sorted(normalized, key=lambda item: (str(item["code"]), str(item["name"]))),
    }


def price_sources() -> dict[str, Any]:
    result: dict[str, Any] = {}
    for code in PRICE_CODES:
        host = "pricing.us-east-1.amazonaws.com"
        path = f"/offers/v1.0/aws/{code}/current/{REGION}/index.json"
        url = f"https://{host}{path}"
        try:
            parsed = urllib.parse.urlparse(url)
            if parsed.scheme != "https" or parsed.hostname != host:
                raise ValueError("pricing URL escaped the exact AWS HTTPS origin")
            request = urllib.request.Request(  # noqa: S310  # nosec B310
                url, headers={"User-Agent": "eventpulse-admission/1"}
            )
            with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310  # nosec B310
                body = response.read()
            document = json.loads(body)
            result[code] = {
                "error": None,
                "format_version": document.get("formatVersion"),
                "offer_code": document.get("offerCode"),
                "publication_date": document.get("publicationDate"),
                "sha256": hashlib.sha256(body).hexdigest(),
                "source": url,
            }
        except (OSError, urllib.error.URLError, ValueError, json.JSONDecodeError) as exc:
            result[code] = {
                "error": type(exc).__name__,
                "source": url,
            }
    return result


def build_observation(claims: dict[str, Any]) -> dict[str, Any]:
    observed = dt.datetime.now(dt.UTC).replace(microsecond=0)
    expires = observed + dt.timedelta(hours=24)
    with tempfile.TemporaryDirectory(prefix="eventpulse-admission-") as temp:
        collector = Collector(Path(temp))
        caller = collector.aws("caller", "sts", "get-caller-identity")
        caller_account = caller.get("Account") if isinstance(caller, dict) else None
        identity_ok = collector.status["caller"] == 0 and caller_account == ACCOUNT
        if identity_ok:
            collector.aws(
                "region",
                "account",
                "get-region-opt-status",
                "--region-name",
                REGION,
                "--region",
                "us-east-1",
            )
            collector.aws("providers", "iam", "list-open-id-connect-providers")
            collector.aws(
                "provider",
                "iam",
                "get-open-id-connect-provider",
                "--open-id-connect-provider-arn",
                PROVIDER_ARN,
            )
            collector.aws("role", "iam", "get-role", "--role-name", ROLE)
            collector.aws(
                "attached", "iam", "list-attached-role-policies", "--role-name", ROLE
            )
            collector.aws("inline", "iam", "list-role-policies", "--role-name", ROLE)
            collector.aws(
                "inline_policy",
                "iam",
                "get-role-policy",
                "--role-name",
                ROLE,
                "--policy-name",
                POLICY,
            )
            collector.aws("role_tags", "iam", "list-role-tags", "--role-name", ROLE)
            collector.aws(
                "tagged",
                "resourcegroupstaggingapi",
                "get-resources",
                "--region",
                REGION,
                "--tag-filters",
                "Key=Project,Values=EventPulse",
            )
            collector.aws(
                "logs",
                "logs",
                "describe-log-groups",
                "--region",
                REGION,
                "--log-group-name-prefix",
                "/aws/lambda/eventpulse",
            )
            collector.aws("streams", "kinesis", "list-streams", "--region", REGION)
            collector.aws("functions", "lambda", "list-functions", "--region", REGION)
            collector.aws("tables", "dynamodb", "list-tables", "--region", REGION)
            collector.aws("buckets", "s3api", "list-buckets")
            collector.aws(
                "queues",
                "sqs",
                "list-queues",
                "--region",
                REGION,
                "--queue-name-prefix",
                "eventpulse",
            )
            collector.aws(
                "alarms",
                "cloudwatch",
                "describe-alarms",
                "--region",
                REGION,
                "--alarm-name-prefix",
                "eventpulse",
            )
            for service in ("kinesis", "lambda", "dynamodb"):
                collector.aws(
                    f"quota_{service}",
                    "service-quotas",
                    "list-service-quotas",
                    "--region",
                    REGION,
                    "--service-code",
                    service,
                )
            collect_budgets(collector)

        role_document = collector.documents.get("role", {})
        role = role_document.get("Role", {}) if isinstance(role_document, dict) else {}
        provider = collector.documents.get("provider", {})
        providers = collector.documents.get("providers", {})
        attached = collector.documents.get("attached", {})
        inline = collector.documents.get("inline", {})
        inline_policy = collector.documents.get("inline_policy", {})
        role_tags = collector.documents.get("role_tags", {})
        tagged = collector.documents.get("tagged", {})
        logs = collector.documents.get("logs", {})
        streams = collector.documents.get("streams", {})
        functions = collector.documents.get("functions", {})
        tables = collector.documents.get("tables", {})
        buckets = collector.documents.get("buckets", {})
        queues = collector.documents.get("queues", {})
        alarms = collector.documents.get("alarms", {})
        budgets = collector.documents.get("budgets", {})

        budget_rows = budgets.get("Budgets", []) if isinstance(budgets, dict) else []
        eventpulse_budgets = []
        for row in budget_rows:
            if not isinstance(row, dict):
                continue
            name = row.get("BudgetName")
            if isinstance(name, str) and name.lower().startswith("eventpulse"):
                limit = row.get("BudgetLimit", {})
                eventpulse_budgets.append(
                    {
                        "amount": limit.get("Amount") if isinstance(limit, dict) else None,
                        "currency": limit.get("Unit") if isinstance(limit, dict) else None,
                        "type": row.get("BudgetType"),
                        "time_unit": row.get("TimeUnit"),
                    }
                )

        function_names = [
            row.get("FunctionName")
            for row in functions.get("Functions", [])
            if isinstance(row, dict)
        ] if isinstance(functions, dict) else []
        bucket_names = [
            row.get("Name") for row in buckets.get("Buckets", []) if isinstance(row, dict)
        ] if isinstance(buckets, dict) else []
        queue_names = [
            str(url).rsplit("/", 1)[-1]
            for url in queues.get("QueueUrls", [])
        ] if isinstance(queues, dict) else []

        observation = {
            "account_id": caller_account,
            "authority": "EP-FUTURE-P3-002-ENTRY",
            "backend_digest": digest_file("part3/stage2/admission/backend-and-lease.json"),
            "budget": {
                "account_budget_count": len(budget_rows),
                "eventpulse_budget_count": len(eventpulse_budgets),
                "eventpulse_budgets": eventpulse_budgets,
                "readable": collector.status.get("budgets") == 0,
            },
            "claim_ceiling": "DESIGN_ONLY",
            "commands": {
                "attempted": len(collector.status),
                "failures": sorted(
                    name for name, status in collector.status.items() if status != 0
                ),
                "statuses": dict(sorted(collector.status.items())),
            },
            "cost_digest": digest_file("part3/stage2/admission/cost-envelope.json"),
            "expires_at_utc": expires.isoformat().replace("+00:00", "Z"),
            "github": {
                key: claims.get(key)
                for key in (
                    "aud",
                    "iss",
                    "job_workflow_ref",
                    "ref",
                    "repository",
                    "repository_id",
                    "repository_owner",
                    "repository_owner_id",
                    "sub",
                )
            },
            "inventory": {
                "alarm_collision_count": len(alarms.get("MetricAlarms", []))
                + len(alarms.get("CompositeAlarms", []))
                if isinstance(alarms, dict)
                else 0,
                "bucket_collision_count": count_prefixed(bucket_names, "eventpulse-"),
                "function_collision_count": count_prefixed(function_names, "eventpulse"),
                "log_group_collision_count": len(logs.get("logGroups", []))
                if isinstance(logs, dict)
                else 0,
                "pagination_complete": all(
                    not isinstance(value, dict)
                    or not any(key in value for key in ("NextToken", "nextToken"))
                    for value in (tagged, logs, streams, functions, tables, queues, alarms)
                ),
                "queue_collision_count": count_prefixed(queue_names, "eventpulse"),
                "stream_collision_count": count_prefixed(
                    streams.get("StreamNames", []) if isinstance(streams, dict) else [],
                    "eventpulse",
                ),
                "table_collision_count": count_prefixed(
                    tables.get("TableNames", []) if isinstance(tables, dict) else [],
                    "eventpulse",
                ),
                "tagged_eventpulse_count": len(tagged.get("ResourceTagMappingList", []))
                if isinstance(tagged, dict)
                else 0,
            },
            "observed_at_utc": observed.isoformat().replace("+00:00", "Z"),
            "policy": {
                "attached": attached.get("AttachedPolicies", [])
                if isinstance(attached, dict)
                else [],
                "inline_names": inline.get("PolicyNames", [])
                if isinstance(inline, dict)
                else [],
                "inline_policy": inline_policy.get("PolicyDocument")
                if isinstance(inline_policy, dict)
                else None,
                "inline_policy_name": inline_policy.get("PolicyName")
                if isinstance(inline_policy, dict)
                else None,
            },
            "price_sources": price_sources(),
            "provider": {
                "audiences": provider.get("ClientIDList", [])
                if isinstance(provider, dict)
                else [],
                "thumbprint_count": len(provider.get("ThumbprintList", []))
                if isinstance(provider, dict)
                else 0,
                "url": provider.get("Url") if isinstance(provider, dict) else None,
                "listed_arns": sorted(
                    row.get("Arn")
                    for row in providers.get("OpenIDConnectProviderList", [])
                    if isinstance(row, dict) and isinstance(row.get("Arn"), str)
                )
                if isinstance(providers, dict)
                else [],
            },
            "quotas": {
                service: normalized_quotas(collector.documents.get(f"quota_{service}", {}))
                for service in ("dynamodb", "kinesis", "lambda")
            },
            "raw_evidence_committed": False,
            "ref": os.environ.get("GITHUB_REF"),
            "region": REGION,
            "region_status": (
                collector.documents.get("region", {}).get("RegionOptStatus")
                if isinstance(collector.documents.get("region", {}), dict)
                else None
            ),
            "role": {
                "arn": role.get("Arn") if isinstance(role, dict) else None,
                "max_session_duration": role.get("MaxSessionDuration")
                if isinstance(role, dict)
                else None,
                "name": role.get("RoleName") if isinstance(role, dict) else None,
                "tags": role_tags.get("Tags", []) if isinstance(role_tags, dict) else [],
                "trust": role.get("AssumeRolePolicyDocument")
                if isinstance(role, dict)
                else None,
            },
            "schema": "eventpulse-part3-stage2-admission-observation-v1",
            "source_sha": git_value("rev-parse", "HEAD"),
            "source_tree": git_value("show", "-s", "--format=%T", "HEAD"),
        }
        return observation


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--claims", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    claims = json.loads(args.claims.read_text(encoding="utf-8"))
    observation = build_observation(claims)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(canonical(observation))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
