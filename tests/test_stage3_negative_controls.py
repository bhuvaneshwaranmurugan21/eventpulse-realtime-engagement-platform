"""Non-mutating controls proving Stage 3 gates reject known corruptions."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

from oracles.eventpulse_reference import (
    OracleError,
    build_envelope_case,
    checkpoint_after_batch,
    classify_event_time,
    event_digest,
    event_disposition,
    identity_disposition,
    load_json,
    replay_keys,
    session_components,
    validate_recovery_ids,
)
from scripts.validate_stage2_contract import load_all as load_stage2, validate_data as validate_stage2_data
from scripts.validate_stage3_completion import (
    ROOT,
    load_all,
    validate_acceptance,
    validate_authority,
    validate_claims,
    validate_future_acceptance,
    validate_manifest,
    validate_oracle,
    validate_public_files,
    validate_stage2_proof_alignment,
    validate_traceability,
)


class Stage3NegativeControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.pristine = load_all()

    def fresh(self) -> dict[str, object]:
        return deepcopy(self.pristine)

    def test_altered_golden_output_is_rejected(self) -> None:
        data = self.fresh()
        data["oracle_result"]["results"][0]["expected"] = "CORRUPTED"
        self.assertIn("committed oracle result differs from independent evaluation", validate_oracle(data))

    def test_altered_corpus_digest_is_rejected(self) -> None:
        data = self.fresh()
        data["fixture_manifest"]["expected_corpus_sha256"] = "0" * 64
        self.assertIn("fixture manifest corpus digest differs from oracle result", validate_oracle(data))

    def test_missing_crash_boundary_is_rejected(self) -> None:
        recovery = load_json(ROOT / "contracts/recovery-protocol-v1.json")
        recovery["boundaries"].pop()
        with self.assertRaisesRegex(OracleError, "recovery boundary mismatch"):
            validate_recovery_ids(recovery)

    def test_checkpoint_overadvance_is_detectable(self) -> None:
        actual = checkpoint_after_batch([100, 101, 102, 103], [102])
        self.assertEqual(actual, 101)
        self.assertNotEqual(actual, 103)

    def test_exact_watermark_misclassification_is_detectable(self) -> None:
        actual = classify_event_time(
            event_time_ms=8_200_000,
            previous_max_event_time_ms=10_000_000,
            allowed_lateness_ms=1_800_000,
        )
        self.assertEqual(actual["category"], "accepted_late")
        self.assertNotEqual(actual["category"], "beyond_watermark")

    def test_exclusive_gap_corruption_is_detectable(self) -> None:
        events = [{"event_id": "a", "event_time_ms": 0}, {"event_id": "b", "event_time_ms": 1_800_000}]
        self.assertEqual(session_components(events, inactivity_gap_ms=1_800_000), [["a", "b"]])
        self.assertNotEqual(session_components(events, inactivity_gap_ms=1_799_999), [["a", "b"]])

    def test_event_mutation_and_duplicate_conflict_are_detectable(self) -> None:
        digest_case = load_json(ROOT / "fixtures/part1/stage3/identity.json")["digest_cases"][0]
        original = digest_case["event_a"]
        mutated = deepcopy(original)
        mutated["payload"]["page_id"] = "tampered"
        self.assertNotEqual(event_digest(original), event_digest(mutated))
        self.assertEqual(
            identity_disposition(has_existing=True, same_digest=False, age_ms=1, horizon_ms=604800000),
            "IDENTITY_CONFLICT",
        )

    def test_bridge_removal_corruption_is_detectable(self) -> None:
        events = [
            {"event_id": "left", "event_time_ms": 0},
            {"event_id": "right", "event_time_ms": 1_860_000},
            {"event_id": "bridge", "event_time_ms": 930_000},
        ]
        self.assertEqual(session_components(events, inactivity_gap_ms=1_800_000), [["left", "bridge", "right"]])
        self.assertEqual(session_components(events[:2], inactivity_gap_ms=1_800_000), [["left"], ["right"]])

    def test_same_generation_double_apply_corruption_is_detectable(self) -> None:
        actual = replay_keys(
            generation_id="live-v1",
            event_ids=["e1", "e2", "e1"],
            integrity_verified=True,
        )
        self.assertEqual(actual, ["live-v1:e1", "live-v1:e2"])
        self.assertNotEqual(len(actual), 3)

    def test_contract_version_corruption_is_rejected(self) -> None:
        envelope = load_json(ROOT / "fixtures/part1/stage3/envelope.json")
        case = {"patch": {"schema_version": "2.0.0"}}
        self.assertEqual(event_disposition(build_envelope_case(envelope["base_event"], case)), "INVALID_SCHEMA")

    def test_shortened_protective_ttl_is_rejected(self) -> None:
        data = load_stage2()
        data["semantics"]["identity"]["ttl_storage_ms"] = 604800000
        self.assertIn("dedupe horizon or protective TTL is invalid", validate_stage2_data(data))

    def test_removed_traceability_mapping_is_rejected(self) -> None:
        data = self.fresh()
        data["traceability"]["mappings"].pop()
        self.assertTrue(any("does not cover every requirement exactly once" in value for value in validate_traceability(data)))

    def test_orphan_fixture_is_rejected(self) -> None:
        data = self.fresh()
        target = "EP-S3-FX-SKEW-002"
        for row in data["traceability"]["mappings"]:
            row["fixture_ids"] = [value for value in row["fixture_ids"] if value != target]
        self.assertTrue(any("orphan fixture IDs" in value and target in value for value in validate_traceability(data)))

    def test_proof_level_contradiction_is_rejected(self) -> None:
        data = self.fresh()
        data["stage2_proof"]["mappings"][0]["claim_level"] = "DESIGN_ONLY"
        self.assertTrue(any("proof/traceability level mismatch" in value for value in validate_stage2_proof_alignment(data)))

    def test_claim_inflation_is_rejected(self) -> None:
        data = self.fresh()
        by_id = {row["id"]: row for row in data["claims"]["claims"]}
        by_id["latency_throughput"]["level"] = "MEASURED"
        errors = validate_claims(data)
        self.assertTrue(any("future claim promoted" in value for value in errors))
        self.assertTrue(any("Part 1 claim inflation" in value for value in errors))

    def test_application_effect_promotion_is_rejected(self) -> None:
        data = self.fresh()
        by_id = {row["id"]: row for row in data["claims"]["claims"]}
        by_id["application_effect_idempotency"]["level"] = "LOCAL_VERIFIED"
        self.assertIn("application effects cannot be promoted without production crash proof", validate_claims(data))

    def test_source_drift_is_rejected(self) -> None:
        data = self.fresh()
        data["oracle_spec"]["source"]["base_sha"] = "0" * 40
        self.assertIn("oracle spec: wrong Stage 2 source boundary", validate_authority(data))

    def test_manifest_digest_corruption_and_extra_artifact_are_rejected(self) -> None:
        data = self.fresh()
        data["manifest"]["artifacts"][0]["sha256"] = "0" * 64
        data["manifest"]["artifacts"].append(
            {"path": "docs/extra.md", "sha256": "0" * 64, "size_bytes": 0}
        )
        errors = validate_manifest(data["manifest"])
        self.assertTrue(any("manifest digest mismatch" in value for value in errors))
        self.assertTrue(any("manifest artifact inventory mismatch" in value for value in errors))

    def test_incomplete_acceptance_registry_is_rejected(self) -> None:
        data = self.fresh()
        data["acceptance"]["acceptance"].pop()
        self.assertIn("Stage 3 acceptance registry is not exactly AC-01 through AC-30", validate_acceptance(data))

    def test_incomplete_future_registry_is_rejected(self) -> None:
        data = self.fresh()
        data["future"]["acceptance"] = data["future"]["acceptance"][:2]
        self.assertIn("future acceptance registry is incomplete", validate_future_acceptance(data))

    def test_foreign_project_and_cloud_identifier_are_rejected_without_writing(self) -> None:
        manifest = {"artifacts": [{"path": "docs/STATUS.md"}]}
        original = Path.read_text

        def injected(path: Path, *args: object, **kwargs: object) -> str:
            if path == ROOT / "docs/STATUS.md":
                return "ledger" + "guard account " + "123456" + "789012"
            return original(path, *args, **kwargs)

        with patch.object(Path, "read_text", autospec=True, side_effect=injected):
            errors = validate_public_files(manifest)
        self.assertEqual(errors, ["foreign-project material in docs/STATUS.md", "sensitive AWS identifier in docs/STATUS.md"])


if __name__ == "__main__":
    unittest.main()
