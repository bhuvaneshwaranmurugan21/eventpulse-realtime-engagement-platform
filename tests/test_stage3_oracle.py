"""Focused semantic and determinism tests for the independent Stage 3 oracle."""

from __future__ import annotations

import json
from pathlib import Path
import unittest

from oracles.eventpulse_reference import (
    OracleError,
    build_envelope_case,
    canonical_bytes,
    checkpoint_after_batch,
    classify_event_time,
    evaluate_corpus,
    event_digest,
    event_disposition,
    fixture_ids,
    identity_disposition,
    load_json,
    recovery_observation,
    replay_keys,
    session_closed,
    session_components,
    shard_watermarks,
    skew_summary,
    stable_session_id,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures/part1/stage3"
EXPECTED_CORPUS_SHA256 = "3275a62ca3b7e90be6a6988d2d7f9a321db7ef53a767a8fdb8a3f01ea8de8461"


class Stage3OracleTests(unittest.TestCase):
    def test_full_corpus_is_exact_and_deterministic(self) -> None:
        first = evaluate_corpus()
        second = evaluate_corpus()
        self.assertEqual(first, second)
        self.assertEqual(first["status"], "PASS")
        self.assertEqual(first["failures"], [])
        self.assertEqual(first["fixture_count"], 50)
        self.assertEqual(first["corpus_sha256"], EXPECTED_CORPUS_SHA256)
        self.assertEqual(canonical_bytes(first), canonical_bytes(second))

    def test_fixture_ids_are_unique_and_complete(self) -> None:
        identifiers = fixture_ids()
        self.assertEqual(len(identifiers), 50)
        self.assertEqual(len(identifiers), len(set(identifiers)))
        self.assertEqual(
            {f"EP-S3-FX-RECOVERY-{number:03d}" for number in range(1, 12)},
            {value for value in identifiers if value.startswith("EP-S3-FX-RECOVERY-")},
        )

    def test_envelope_disposition_precedence_and_clock_boundaries(self) -> None:
        fixture = load_json(FIXTURES / "envelope.json")
        by_id = {case["id"]: case for case in fixture["cases"]}
        for identifier in (
            "EP-S3-FX-ENV-009",
            "EP-S3-FX-ENV-011",
            "EP-S3-FX-ENV-012",
            "EP-S3-FX-ENV-013",
            "EP-S3-FX-ENV-014",
            "EP-S3-FX-ENV-015",
        ):
            case = by_id[identifier]
            event = build_envelope_case(fixture["base_event"], case)
            self.assertEqual(event_disposition(event), case["expected"])

    def test_canonical_json_rejects_floats(self) -> None:
        with self.assertRaisesRegex(OracleError, "floating-point"):
            canonical_bytes({"invalid": 1.5})

    def test_identity_digest_excludes_only_ingest_time(self) -> None:
        fixture = load_json(FIXTURES / "identity.json")["digest_cases"][0]
        self.assertEqual(event_digest(fixture["event_a"]), event_digest(fixture["event_b"]))
        changed = json.loads(json.dumps(fixture["event_b"]))
        changed["payload"]["page_id"] = "changed"
        self.assertNotEqual(event_digest(fixture["event_a"]), event_digest(changed))

    def test_dedupe_horizon_is_inclusive_then_expires(self) -> None:
        self.assertEqual(
            identity_disposition(has_existing=True, same_digest=True, age_ms=604800000, horizon_ms=604800000),
            "IDENTICAL_DUPLICATE",
        )
        self.assertEqual(
            identity_disposition(has_existing=True, same_digest=True, age_ms=604800001, horizon_ms=604800000),
            "EXPIRED_IDENTITY_QUARANTINE",
        )

    def test_watermark_exact_boundary_and_minus_one_differ(self) -> None:
        exact = classify_event_time(
            event_time_ms=8200000,
            previous_max_event_time_ms=10000000,
            allowed_lateness_ms=1800000,
        )
        past = classify_event_time(
            event_time_ms=8199999,
            previous_max_event_time_ms=10000000,
            allowed_lateness_ms=1800000,
        )
        self.assertEqual(exact["category"], "accepted_late")
        self.assertEqual(past["category"], "beyond_watermark")
        self.assertEqual(exact["watermark_after_ms"], past["watermark_after_ms"])

    def test_shard_watermarks_are_independent(self) -> None:
        result = shard_watermarks(
            [{"shard": "a", "event_time_ms": 10_000_000}, {"shard": "b", "event_time_ms": 20_000_000}],
            allowed_lateness_ms=1_800_000,
        )
        self.assertEqual(result, {"a": 8_200_000, "b": 18_200_000})

    def test_session_gap_is_inclusive_and_plus_one_splits(self) -> None:
        joined = session_components(
            [{"event_id": "a", "event_time_ms": 0}, {"event_id": "b", "event_time_ms": 1_800_000}],
            inactivity_gap_ms=1_800_000,
        )
        split = session_components(
            [{"event_id": "a", "event_time_ms": 0}, {"event_id": "b", "event_time_ms": 1_800_001}],
            inactivity_gap_ms=1_800_000,
        )
        self.assertEqual(joined, [["a", "b"]])
        self.assertEqual(split, [["a"], ["b"]])

    def test_permitted_session_reordering_and_bridge_are_invariant(self) -> None:
        events = [
            {"event_id": "right", "event_time_ms": 1_860_000},
            {"event_id": "left", "event_time_ms": 0},
            {"event_id": "bridge", "event_time_ms": 930_000},
        ]
        expected = [["left", "bridge", "right"]]
        self.assertEqual(session_components(events, inactivity_gap_ms=1_800_000), expected)
        self.assertEqual(session_components(list(reversed(events)), inactivity_gap_ms=1_800_000), expected)

    def test_session_identity_and_strict_closure(self) -> None:
        identifier = stable_session_id(
            contract_version="1.0.0",
            generation_id="live-v1",
            user_id="user-bridge",
            member_event_ids=["right", "bridge", "left"],
        )
        self.assertEqual(identifier, "333efbbd94c30bf90b14403bc6fca0980d5f07dbfedefa87eaa813da1e2d6b06")
        self.assertFalse(session_closed(watermark_ms=2_800_000, session_end_ms=1_000_000, inactivity_gap_ms=1_800_000))
        self.assertTrue(session_closed(watermark_ms=2_800_001, session_end_ms=1_000_000, inactivity_gap_ms=1_800_000))

    def test_all_crash_observations_equal_literal_goldens(self) -> None:
        fixture = load_json(FIXTURES / "recovery.json")
        for case in fixture["crash_cases"]:
            with self.subTest(case=case["id"]):
                self.assertEqual(recovery_observation(case["crash_id"]), case["expected"])

    def test_checkpoint_never_passes_earliest_failure(self) -> None:
        sequence = [100, 101, 102, 103]
        self.assertEqual(checkpoint_after_batch(sequence, []), 103)
        self.assertIsNone(checkpoint_after_batch(sequence, [100]))
        self.assertEqual(checkpoint_after_batch(sequence, [102]), 101)

    def test_replay_generation_isolation_and_integrity_gate(self) -> None:
        self.assertEqual(
            replay_keys(generation_id="live-v1", event_ids=["e1", "e2", "e1"], integrity_verified=True),
            ["live-v1:e1", "live-v1:e2"],
        )
        self.assertEqual(
            replay_keys(generation_id="replay-1", event_ids=["e1"], integrity_verified=True),
            ["replay-1:e1"],
        )
        with self.assertRaisesRegex(OracleError, "RAW_INTEGRITY_REQUIRED"):
            replay_keys(generation_id="replay-1", event_ids=["e1"], integrity_verified=False)

    def test_skew_changes_evidence_not_event_semantics(self) -> None:
        self.assertEqual(skew_summary(["a", "a", "b", "b"]), {"hottest_count": 2, "hottest_ratio": "1/2"})
        self.assertEqual(skew_summary(["hot", "hot", "hot", "hot", "cold"]), {"hottest_count": 4, "hottest_ratio": "4/5"})


if __name__ == "__main__":
    unittest.main()
