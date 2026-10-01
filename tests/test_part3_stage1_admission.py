from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from part3.stage1.oracles.admission_oracle import decide

COMMANDS = {
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
SUBJECT_KEY = "token.actions.githubusercontent.com:sub"
AUDIENCE_KEY = "token.actions.githubusercontent.com:aud"
EXPECTED_SUBJECT = (
    "repo:bhuvaneshwaranmurugan21/eventpulse-realtime-engagement-platform:ref:refs/heads/main"
)


class AdmissionFixture:
    def __init__(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.documents = {name: {} for name in COMMANDS}
        self.documents.update(
            {
                "caller": {"Account": "773994909635", "Arn": "redacted", "UserId": "redacted"},
                "region": {"RegionName": "ap-south-2", "RegionOptStatus": "ENABLED"},
                "provider": {"ClientIDList": ["sts.amazonaws.com"], "ThumbprintList": ["redacted"]},
                "role": {
                    "Role": {
                        "RoleName": "EventPulseGitHubOidcRole",
                        "AssumeRolePolicyDocument": {
                            "Statement": [
                                {
                                    "Principal": {
                                        "Federated": "token.actions.githubusercontent.com"
                                    },
                                    "Condition": {
                                        "StringEquals": {
                                            AUDIENCE_KEY: "sts.amazonaws.com",
                                            SUBJECT_KEY: EXPECTED_SUBJECT,
                                        }
                                    },
                                }
                            ]
                        },
                    }
                },
                "attached": {"AttachedPolicies": [{"PolicyName": "reviewed-later"}]},
                "inline": {"PolicyNames": []},
                "tagged": {"ResourceTagMappingList": []},
                "budgets": {"Budgets": [{"BudgetName": "account-guardrail"}]},
            }
        )

    def write(self, *, statuses: dict[str, int] | None = None) -> None:
        for name, value in self.documents.items():
            (self.root / f"{name}.json").write_text(json.dumps(value, sort_keys=True))
            (self.root / f"{name}.stderr").write_text("")
        (self.root / "command-status.json").write_text(
            json.dumps(statuses or dict.fromkeys(COMMANDS, 0), sort_keys=True)
        )
        rows = []
        for path in sorted(self.root.iterdir()):
            if path.name != "sha256-manifest.json":
                rows.append(
                    {
                        "path": path.name,
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        "size_bytes": path.stat().st_size,
                    }
                )
        (self.root / "sha256-manifest.json").write_text(json.dumps(rows, sort_keys=True))

    def close(self) -> None:
        self.temp.cleanup()


class TestAdmissionOracle(unittest.TestCase):
    def setUp(self) -> None:
        self.fx = AdmissionFixture()

    def tearDown(self) -> None:
        self.fx.close()

    def test_complete_fixture_is_admitted(self) -> None:
        self.fx.write()
        self.assertEqual(decide(self.fx.root)["decision"], "ADMITTED")

    def test_empty_permissions_are_no_go_not_indeterminate(self) -> None:
        self.fx.documents["attached"] = {"AttachedPolicies": []}
        self.fx.write()
        result = decide(self.fx.root)
        self.assertEqual(result["decision"], "NO_GO")
        self.assertIn("OIDC role has no workload or deployment policy", result["gaps"])

    def test_no_budget_is_no_go(self) -> None:
        self.fx.documents["budgets"] = {"Budgets": []}
        self.fx.write()
        self.assertEqual(decide(self.fx.root)["decision"], "NO_GO")

    def test_wrong_account_fails_closed(self) -> None:
        self.fx.documents["caller"]["Account"] = "000000000000"
        self.fx.write()
        self.assertEqual(decide(self.fx.root)["decision"], "INDETERMINATE")

    def test_wrong_region_fails_closed(self) -> None:
        self.fx.documents["region"]["RegionName"] = "ap-south-1"
        self.fx.write()
        self.assertEqual(decide(self.fx.root)["decision"], "INDETERMINATE")

    def test_disabled_region_fails_closed(self) -> None:
        self.fx.documents["region"]["RegionOptStatus"] = "DISABLED"
        self.fx.write()
        self.assertEqual(decide(self.fx.root)["decision"], "INDETERMINATE")

    def test_wrong_role_fails_closed(self) -> None:
        self.fx.documents["role"]["Role"]["RoleName"] = "OtherRole"
        self.fx.write()
        self.assertEqual(decide(self.fx.root)["decision"], "INDETERMINATE")

    def test_missing_audience_fails_closed(self) -> None:
        self.fx.documents["provider"]["ClientIDList"] = []
        self.fx.write()
        self.assertEqual(decide(self.fx.root)["decision"], "INDETERMINATE")

    def test_broad_subject_fails_closed(self) -> None:
        condition = self.fx.documents["role"]["Role"]["AssumeRolePolicyDocument"]["Statement"][0][
            "Condition"
        ]["StringEquals"]
        condition[SUBJECT_KEY] = "repo:bhuvaneshwaranmurugan21/*"
        self.fx.write()
        self.assertEqual(decide(self.fx.root)["decision"], "INDETERMINATE")

    def test_failed_command_fails_closed(self) -> None:
        status = dict.fromkeys(COMMANDS, 0)
        status["budgets"] = 254
        self.fx.write(statuses=status)
        self.assertEqual(decide(self.fx.root)["decision"], "INDETERMINATE")

    def test_failed_command_with_empty_output_fails_closed_without_crashing(self) -> None:
        status = dict.fromkeys(COMMANDS, 0)
        status["role"] = 254
        self.fx.write(statuses=status)
        (self.fx.root / "role.json").write_text("")
        result = decide(self.fx.root)
        self.assertEqual(result["decision"], "INDETERMINATE")
        self.assertIn("command failed: role", result["errors"])
        self.assertIn("unreadable JSON: role", result["errors"])

    def test_missing_status_fails_closed(self) -> None:
        status = dict.fromkeys(COMMANDS, 0)
        status.pop("budgets")
        self.fx.write(statuses=status)
        self.assertEqual(decide(self.fx.root)["decision"], "INDETERMINATE")

    def test_tampered_file_fails_closed(self) -> None:
        self.fx.write()
        (self.fx.root / "caller.json").write_text("{}")
        self.assertEqual(decide(self.fx.root)["decision"], "INDETERMINATE")


if __name__ == "__main__":
    unittest.main()
