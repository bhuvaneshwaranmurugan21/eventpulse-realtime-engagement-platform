from __future__ import annotations

import datetime as dt
import hashlib
import json
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import Any

from part3.stage2.admission.admission_oracle import EXPECTED_COMMANDS, decide
from scripts.collect_part3_stage2_admission import BUDGETS_REGION, collect_budgets

ROOT = Path(__file__).resolve().parents[1]
ACCOUNT = "773994909635"
PROVIDER = f"arn:aws:iam::{ACCOUNT}:oidc-provider/token.actions.githubusercontent.com"
ROLE = f"arn:aws:iam::{ACCOUNT}:role/EventPulseGitHubOidcRole"
SUBJECT = (
    "repo:bhuvaneshwaranmurugan21@276895096/"
    "eventpulse-realtime-engagement-platform@1333031049:ref:refs/heads/main"
)
NOW = dt.datetime(2026, 10, 7, 6, 0, tzinfo=dt.UTC)


def file_digest(relative: str) -> str:
    return hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()


def seed() -> dict[str, Any]:
    policy = json.loads(
        (ROOT / "part3/stage2/admission/expected-read-policy.json").read_text()
    )
    price_sources = {
        code: {
            "error": None,
            "format_version": "v1.0",
            "offer_code": code,
            "publication_date": "2026-10-01T00:00:00Z",
            "sha256": "a" * 64,
            "source": (
                "https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/"
                f"{code}/current/ap-south-2/index.json"
            ),
        }
        for code in (
            "AmazonCloudWatch",
            "AmazonDynamoDB",
            "AmazonKinesis",
            "AmazonS3",
            "AWSLambda",
            "AWSQueueService",
        )
    }
    inventory = {
        "alarm_collision_count": 0,
        "bucket_collision_count": 0,
        "function_collision_count": 0,
        "log_group_collision_count": 0,
        "pagination_complete": True,
        "queue_collision_count": 0,
        "stream_collision_count": 0,
        "table_collision_count": 0,
        "tagged_eventpulse_count": 0,
    }
    return {
        "account_id": ACCOUNT,
        "authority": "EP-FUTURE-P3-002-ENTRY",
        "backend_digest": file_digest("part3/stage2/admission/backend-and-lease.json"),
        "budget": {
            "account_budget_count": 1,
            "eventpulse_budget_count": 1,
            "eventpulse_budgets": [
                {
                    "amount": "8.0",
                    "currency": "USD",
                    "time_unit": "MONTHLY",
                    "type": "COST",
                }
            ],
            "readable": True,
        },
        "claim_ceiling": "DESIGN_ONLY",
        "commands": {
            "attempted": len(EXPECTED_COMMANDS),
            "failures": [],
            "statuses": dict.fromkeys(EXPECTED_COMMANDS, 0),
        },
        "cost_digest": file_digest("part3/stage2/admission/cost-envelope.json"),
        "expires_at_utc": "2026-10-08T05:55:00Z",
        "github": {
            "aud": "sts.amazonaws.com",
            "iss": "https://token.actions.githubusercontent.com",
            "job_workflow_ref": (
                "bhuvaneshwaranmurugan21/eventpulse-realtime-engagement-platform/"
                ".github/workflows/part3-stage2-admission-requalification.yml@refs/heads/main"
            ),
            "ref": "refs/heads/main",
            "repository": "bhuvaneshwaranmurugan21/eventpulse-realtime-engagement-platform",
            "repository_id": "1333031049",
            "repository_owner": "bhuvaneshwaranmurugan21",
            "repository_owner_id": "276895096",
            "sub": SUBJECT,
        },
        "inventory": inventory,
        "observed_at_utc": "2026-10-07T05:55:00Z",
        "policy": {
            "attached": [],
            "inline_names": ["EventPulseAdmissionReadOnly"],
            "inline_policy": policy,
            "inline_policy_name": "EventPulseAdmissionReadOnly",
        },
        "price_sources": price_sources,
        "provider": {
            "audiences": ["sts.amazonaws.com"],
            "listed_arns": [PROVIDER],
            "thumbprint_count": 1,
            "url": "token.actions.githubusercontent.com",
        },
        "quotas": {
            "dynamodb": {
                "entry_count": 1,
                "entries": [{"name": "Tables per Region", "value": 2500}],
            },
            "kinesis": {
                "entry_count": 1,
                "entries": [{"name": "Shards per Region", "value": 10}],
            },
            "lambda": {
                "entry_count": 1,
                "entries": [{"name": "Concurrent executions", "value": 1000}],
            },
        },
        "raw_evidence_committed": False,
        "ref": "refs/heads/main",
        "region": "ap-south-2",
        "region_status": "ENABLED",
        "role": {
            "arn": ROLE,
            "max_session_duration": 3600,
            "name": "EventPulseGitHubOidcRole",
            "tags": [
                {"Key": "Project", "Value": "EventPulse"},
                {"Key": "Purpose", "Value": "GitHubOIDC"},
                {"Key": "ManagedBy", "Value": "EventPulseBootstrap"},
            ],
            "trust": {
                "Statement": [
                    {
                        "Action": "sts:AssumeRoleWithWebIdentity",
                        "Condition": {
                            "StringEquals": {
                                "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
                                "token.actions.githubusercontent.com:sub": SUBJECT,
                            }
                        },
                        "Effect": "Allow",
                        "Principal": {"Federated": PROVIDER},
                        "Sid": "EventPulseMainOnly",
                    }
                ],
                "Version": "2012-10-17",
            },
        },
        "schema": "eventpulse-part3-stage2-admission-observation-v1",
        "source_sha": "1" * 40,
        "source_tree": "2" * 40,
    }


class TestStage2AdmissionOracle(unittest.TestCase):
    def assert_rejected(self, mutate: Callable[[dict[str, Any]], None]) -> None:
        observation = seed()
        mutate(observation)
        self.assertNotEqual(decide(observation, now=NOW)["decision"], "ADMITTED")

    def test_exact_fixture_is_admitted(self) -> None:
        result = decide(seed(), now=NOW)
        self.assertEqual(result["decision"], "ADMITTED", result)
        self.assertEqual(result["stage2_gate"], "OPEN")

    def test_budgets_inventory_uses_supported_global_region(self) -> None:
        class RecordingCollector:
            call: tuple[str, tuple[str, ...]] | None = None

            def aws(self, name: str, *args: str) -> dict[str, list[Any]]:
                self.call = (name, args)
                return {"Budgets": []}

        collector = RecordingCollector()
        result = collect_budgets(collector)  # type: ignore[arg-type]

        self.assertEqual(BUDGETS_REGION, "us-east-1")
        self.assertEqual(result, {"Budgets": []})
        self.assertEqual(
            collector.call,
            (
                "budgets",
                (
                    "budgets",
                    "describe-budgets",
                    "--account-id",
                    ACCOUNT,
                    "--region",
                    "us-east-1",
                ),
            ),
        )

    def test_identity_boundaries_fail_closed(self) -> None:
        mutations = (
            lambda row: row.__setitem__("account_id", "000000000000"),
            lambda row: row.__setitem__("region", "ap-south-1"),
            lambda row: row.__setitem__("region_status", "DISABLED"),
            lambda row: row.__setitem__("ref", "refs/heads/feature"),
            lambda row: row["github"].__setitem__("sub", "repo:untrusted/repository:*"),
            lambda row: row["provider"].__setitem__(
                "audiences", ["sts.amazonaws.com", "unreviewed"]
            ),
            lambda row: row["role"].__setitem__("arn", "arn:aws:iam::0:role/Other"),
        )
        for index, mutate in enumerate(mutations, 1):
            with self.subTest(case=index):
                self.assert_rejected(mutate)

    def test_broadened_trust_is_rejected(self) -> None:
        def mutate(row: dict[str, Any]) -> None:
            row["role"]["trust"]["Statement"].append(
                {
                    "Action": "sts:AssumeRoleWithWebIdentity",
                    "Effect": "Allow",
                    "Principal": {"Federated": PROVIDER},
                }
            )

        self.assert_rejected(mutate)

    def test_wrong_trust_action_is_rejected(self) -> None:
        self.assert_rejected(
            lambda row: row["role"]["trust"]["Statement"][0].__setitem__(
                "Action", "sts:AssumeRole"
            )
        )

    def test_policy_drift_is_rejected(self) -> None:
        self.assert_rejected(
            lambda row: row["policy"]["inline_policy"]["Statement"][0].__setitem__(
                "Action", "*"
            )
        )

    def test_managed_policy_is_rejected(self) -> None:
        self.assert_rejected(
            lambda row: row["policy"].__setitem__(
                "attached", [{"PolicyName": "AdministratorAccess"}]
            )
        )

    def test_failed_or_missing_command_is_rejected(self) -> None:
        for mode in ("failed", "missing"):
            with self.subTest(mode=mode):
                def mutate(row: dict[str, Any], selected: str = mode) -> None:
                    if selected == "failed":
                        row["commands"]["statuses"]["budgets"] = 254
                        row["commands"]["failures"] = ["budgets"]
                    else:
                        row["commands"]["statuses"].pop("budgets")

                self.assert_rejected(mutate)

    def test_resource_collision_is_no_go(self) -> None:
        observation = seed()
        observation["inventory"]["stream_collision_count"] = 1
        result = decide(observation, now=NOW)
        self.assertEqual(result["decision"], "NO_GO")

    def test_incomplete_pagination_is_rejected(self) -> None:
        self.assert_rejected(
            lambda row: row["inventory"].__setitem__("pagination_complete", False)
        )

    def test_empty_or_irrelevant_quota_is_no_go(self) -> None:
        for entries in ([], [{"name": "Unrelated quota", "value": 10}]):
            with self.subTest(entries=entries):
                observation = seed()
                observation["quotas"]["lambda"] = {
                    "entry_count": len(entries),
                    "entries": entries,
                }
                self.assertEqual(decide(observation, now=NOW)["decision"], "NO_GO")

    def test_missing_or_over_cap_budget_is_no_go(self) -> None:
        cases = ([], [{"amount": "100", "currency": "USD", "type": "COST"}])
        for budgets in cases:
            with self.subTest(budgets=budgets):
                observation = seed()
                observation["budget"]["eventpulse_budgets"] = budgets
                observation["budget"]["eventpulse_budget_count"] = len(budgets)
                self.assertEqual(decide(observation, now=NOW)["decision"], "NO_GO")

    def test_stale_or_future_observation_is_rejected(self) -> None:
        for timestamp in ("2026-10-01T00:00:00Z", "2026-10-07T07:00:00Z"):
            with self.subTest(timestamp=timestamp):
                self.assert_rejected(
                    lambda row, value=timestamp: row.__setitem__("observed_at_utc", value)
                )

    def test_price_source_failure_is_rejected(self) -> None:
        self.assert_rejected(
            lambda row: row["price_sources"]["AmazonS3"].__setitem__(
                "error", "URLError"
            )
        )

    def test_backend_cost_and_raw_evidence_drift_is_rejected(self) -> None:
        mutations = (
            lambda row: row.__setitem__("backend_digest", "0" * 64),
            lambda row: row.__setitem__("cost_digest", "0" * 64),
            lambda row: row.__setitem__("raw_evidence_committed", True),
        )
        for index, mutate in enumerate(mutations, 1):
            with self.subTest(case=index):
                self.assert_rejected(mutate)

    def test_duplicate_json_key_is_rejected_by_loader(self) -> None:
        from part3.stage2.admission.admission_oracle import strict_object

        with self.assertRaises(ValueError):
            json.loads('{"account_id":"a","account_id":"b"}', object_pairs_hook=strict_object)


if __name__ == "__main__":
    unittest.main()
