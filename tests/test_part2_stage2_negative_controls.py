from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "part2/stage2/oracles"))

from part2_stage2_recovery import (  # noqa: E402
    canonical_bytes,
    digest,
    logical_identity_disposition,
    read_journal,
    sha256_bytes,
    validate_claim_levels,
    validate_journal,
    validate_recovery_state,
    validate_ttl_boundary,
    verify,
    verify_frozen_result,
)
from run_part2_stage2_crash_matrix import supervise  # noqa: E402


class MandatoryNegativeControls(unittest.TestCase):
    temporary: tempfile.TemporaryDirectory[str]
    output: Path
    summary: dict[str, object]
    golden: dict[str, object]

    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.output = Path(cls.temporary.name) / "evidence"
        cls.summary = supervise(cls.output)
        cls.golden = json.loads(
            (ROOT / "fixtures/part2/stage2/golden-digests.json").read_text(encoding="utf-8")
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def state(self, case_id: str, name: str) -> dict[str, object]:
        return json.loads((self.output / case_id / f"{name}.json").read_text(encoding="utf-8"))

    def result(self, case_id: str) -> dict[str, object]:
        return next(
            copy.deepcopy(row)
            for row in self.summary["results"]  # type: ignore[index]
            if row["case_id"] == case_id
        )

    def test_nc01_archive_digest_corruption_is_rejected(self) -> None:
        state = self.state("EP-CRASH-02", "after-restart")
        state["archive"][0]["body_sha256"] = "0" * 64  # type: ignore[index]
        result = self.result("EP-CRASH-02")
        result["after_restart_sha256"] = digest(state)
        self.assertIn(
            "EP-CRASH-02 frozen after_restart_sha256 mismatch",
            verify_frozen_result(result, self.golden),
        )

    def test_nc02_partial_transaction_visibility_is_rejected(self) -> None:
        crash = self.state("EP-CRASH-03", "after-crash")
        restart = self.state("EP-CRASH-03", "after-restart")
        crash["tables"]["identity_ledger"].append({"event_id": "partial"})  # type: ignore[index]
        response = self.state("EP-CRASH-03", "response")
        errors = verify("EP-CRASH-03", crash, restart, response)
        self.assertIn("EP-CRASH-03 exposed a partial transaction", errors)

    def test_nc03_state_version_bypass_is_rejected(self) -> None:
        state = self.state("EP-CRASH-04", "after-restart")
        state["tables"]["shard_state"][0]["version"] = 0  # type: ignore[index]
        self.assertIn("shard optimistic version is non-positive", validate_recovery_state(state))

    def test_nc04_later_failure_sequence_is_rejected(self) -> None:
        crash = self.state("EP-CRASH-05", "after-crash")
        restart = self.state("EP-CRASH-05", "after-restart")
        response = {"batchItemFailures": [{"itemIdentifier": "3"}]}
        self.assertIn(
            "EP-CRASH-05 did not report earliest failed sequence",
            verify("EP-CRASH-05", crash, restart, response),
        )

    def test_nc05_changed_outbox_identity_is_rejected(self) -> None:
        state = self.state("EP-CRASH-07", "after-restart")
        state["tables"]["outbox"][0]["outbox_id"] = "changed"  # type: ignore[index]
        self.assertIn("stable outbox identity mismatch", validate_recovery_state(state))

    def test_nc06_reversed_ttl_boundary_is_rejected(self) -> None:
        equality = logical_identity_disposition(
            existing_digest="a", incoming_digest="a", first_ingest_ms=0, ingest_ms=604_800_000
        )
        plus_one = logical_identity_disposition(
            existing_digest="a", incoming_digest="a", first_ingest_ms=0, ingest_ms=604_800_001
        )
        self.assertEqual(validate_ttl_boundary(equality, plus_one), [])
        self.assertEqual(
            validate_ttl_boundary(plus_one, equality),
            ["dedupe equality boundary changed", "dedupe plus-one boundary changed"],
        )

    def test_nc07_removed_replay_generation_is_rejected(self) -> None:
        state = self.state("EP-CRASH-04", "after-restart")
        state["tables"]["identity_ledger"][0]["generation_id"] = ""  # type: ignore[index]
        self.assertIn("identity is missing replay generation", validate_recovery_state(state))

    def test_nc08_reordered_journal_transition_is_rejected(self) -> None:
        rows = read_journal(self.output / "EP-CRASH-04")
        rows[0], rows[1] = rows[1], rows[0]
        self.assertTrue(any("journal" in error for error in validate_journal(rows)))

    def test_nc09_output_version_skip_is_rejected(self) -> None:
        state = self.state("EP-CRASH-04", "after-restart")
        state["tables"]["session_output"] = [  # type: ignore[index]
            {"session_id": "session", "output_version": 2}
        ]
        self.assertIn(
            "materialized output version is not exactly one",
            validate_recovery_state(state),
        )

    def test_nc10_reused_process_is_rejected_even_with_valid_chain(self) -> None:
        rows = read_journal(self.output / "EP-CRASH-04")
        crash_pid = next(row["process_id"] for row in rows if row["phase"] == "crash")
        previous = "GENESIS"
        for ordinal, row in enumerate(rows, start=1):
            if row["phase"] == "restart":
                row["process_id"] = crash_pid
            row["ordinal"] = ordinal
            row["previous_sha256"] = previous
            row.pop("entry_sha256", None)
            row["entry_sha256"] = sha256_bytes(canonical_bytes(row))
            previous = row["entry_sha256"]
        self.assertIn("restart reused the crash process", validate_journal(rows))

    def test_nc11_missing_raw_object_is_not_silently_replayable(self) -> None:
        state = self.state("EP-CRASH-02", "after-restart")
        state["archive"] = []
        result = self.result("EP-CRASH-02")
        result["after_restart_sha256"] = digest(state)
        self.assertTrue(verify_frozen_result(result, self.golden))

    def test_nc12_aws_claim_inflation_is_forbidden(self) -> None:
        allowed = {
            "application_effect_crash_restart": "LOCAL_VERIFIED",
            "aws_adapter_request_shapes": "DESIGN_ONLY",
            "durable_aws_recovery": "UNCLAIMED",
            "managed_consumer": "UNCLAIMED",
        }
        mutated = dict(allowed)
        mutated["durable_aws_recovery"] = "AWS_VERIFIED"
        self.assertEqual(validate_claim_levels(allowed), [])
        self.assertEqual(
            validate_claim_levels(mutated),
            ["Stage 2 claim levels exceed or differ from ceiling"],
        )


if __name__ == "__main__":
    unittest.main()
