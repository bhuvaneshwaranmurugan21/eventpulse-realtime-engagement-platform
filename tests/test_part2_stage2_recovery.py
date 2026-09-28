from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from part2_stage1_helpers import batch, event, record  # noqa: E402

from eventpulse.canonical import canonical_bytes, event_digest  # noqa: E402
from eventpulse.errors import InvariantViolation, RetryableDependencyError  # noqa: E402
from eventpulse.handler import create_handler  # noqa: E402
from eventpulse.local import (  # noqa: E402
    FilesystemFailureDestination,
    LocalRuntime,
    create_local_runtime,
)
from eventpulse.models import (  # noqa: E402
    AdmittedEvent,
    ApplyResult,
    RejectedEvent,
    SourceCoordinate,
)
from eventpulse.recovery import replay_archived_event  # noqa: E402
from eventpulse.semantics import DEDUPE_HORIZON_MS, IDENTITY_TTL_MS  # noqa: E402


class RecoveryInvariantTests(unittest.TestCase):
    def test_logical_expiry_boundary_is_independent_of_physical_ttl(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = create_local_runtime(Path(directory))
            handler = create_handler(runtime)
            initial = event("identity", 1_000, ingest_time_ms=1_000)
            equality = event(
                "identity", 1_000, ingest_time_ms=1_000 + DEDUPE_HORIZON_MS
            )
            plus_one = event(
                "identity", 1_000, ingest_time_ms=1_001 + DEDUPE_HORIZON_MS
            )
            handler(batch(record(initial, "1")), None)
            coordinate = SourceCoordinate(
                "arn:aws:kinesis:ap-south-2:test-account:stream/eventpulse-test",
                "shard-a",
                "2",
                "user-a",
            )
            equality_result = runtime.store.apply_event(
                AdmittedEvent(
                    coordinate,
                    equality,
                    canonical_bytes(equality),
                    event_digest(equality),
                ),
                "raw/equality.json",
                "live-v1",
            )
            self.assertEqual(equality_result.disposition, "IDENTICAL_DUPLICATE")
            state = runtime.store.recovery_export()
            self.assertEqual(state["user_aggregate"][0]["views"], 1)
            self.assertEqual(state["identity_ledger"][0]["expiry_ms"], 1_000 + IDENTITY_TTL_MS)
            plus_result = runtime.store.apply_event(
                AdmittedEvent(
                    SourceCoordinate(
                        coordinate.event_source_arn,
                        coordinate.shard_id,
                        "3",
                        coordinate.partition_key,
                    ),
                    plus_one,
                    canonical_bytes(plus_one),
                    event_digest(plus_one),
                ),
                "raw/plus-one.json",
                "live-v1",
            )
            self.assertEqual(plus_result.disposition, "EXPIRED_IDENTITY")
            state = runtime.store.recovery_export()
            self.assertEqual(state["user_aggregate"][0]["views"], 1)
            self.assertEqual(state["quarantine"][0]["disposition"], "EXPIRED_IDENTITY")

    def test_restart_converges_accepted_late_bridge_and_closure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = create_handler(create_local_runtime(root))
            first(
                batch(
                    record(event("left", 10_000_000), "1"),
                    record(event("right", 11_860_000), "2"),
                ),
                None,
            )
            second = create_handler(create_local_runtime(root))
            second(batch(record(event("bridge", 10_930_000), "3")), None)
            third_runtime = create_local_runtime(root)
            create_handler(third_runtime)(
                batch(record(event("advance", 15_460_001, user_id="user-b"), "4")),
                None,
            )
            state = third_runtime.store.recovery_export()
            self.assertEqual(len(state["session_output"]), 1)
            output = state["session_output"][0]
            self.assertEqual(json.loads(output["member_ids_json"]), ["bridge", "left", "right"])
            self.assertEqual(output["output_version"], 1)

    def test_same_and_new_generation_replay_are_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = create_local_runtime(root)
            value = event("replay-1", 10_000_000)
            create_handler(runtime)(batch(record(value, "1")), None)
            commit = runtime.store.recovery_export()["processing_commit"][0]
            raw_key = str(commit["raw_key"])
            body = (root / "archive" / raw_key).read_bytes()
            coordinate = SourceCoordinate(
                "arn:aws:kinesis:ap-south-2:test-account:stream/eventpulse-test",
                "shard-a",
                "1",
                "user-a",
            )
            common: dict[str, Any] = {
                "archive": runtime.archive,
                "store": runtime.store,
                "destination": FilesystemFailureDestination(root / "failure-destination"),
                "crash_probe": runtime.crash_probe,
                "coordinate": coordinate,
                "raw_key": raw_key,
                "expected_body_sha256": hashlib.sha256(body).hexdigest(),
                "expected_event_digest": event_digest(value),
            }
            same = replay_archived_event(
                **common, generation_id="live-v1", invocation_id="same-generation"
            )
            new = replay_archived_event(
                **common, generation_id="replay-v2", invocation_id="new-generation"
            )
            self.assertEqual(same.disposition, "IDENTICAL_DUPLICATE")
            self.assertTrue(new.mutated_live_state)
            identities = runtime.store.recovery_export()["identity_ledger"]
            self.assertEqual({row["generation_id"] for row in identities}, {"live-v1", "replay-v2"})

    def test_missing_and_corrupt_raw_replay_fail_closed(self) -> None:
        for mode in ("missing", "corrupt"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                runtime = create_local_runtime(root)
                value = event("replay-fail", 10_000_000)
                create_handler(runtime)(batch(record(value, "1")), None)
                commit = runtime.store.recovery_export()["processing_commit"][0]
                raw_key = str(commit["raw_key"])
                raw_path = root / "archive" / raw_key
                body_digest = hashlib.sha256(raw_path.read_bytes()).hexdigest()
                if mode == "missing":
                    raw_path.unlink()
                else:
                    raw_path.write_bytes(b"corrupt")
                with self.assertRaises((InvariantViolation, RetryableDependencyError)):
                    replay_archived_event(
                        archive=runtime.archive,
                        store=runtime.store,
                        destination=FilesystemFailureDestination(root / "failure-destination"),
                        crash_probe=runtime.crash_probe,
                        coordinate=SourceCoordinate(
                            "arn:aws:kinesis:ap-south-2:test-account:stream/eventpulse-test",
                            "shard-a",
                            "1",
                            "user-a",
                        ),
                        raw_key=raw_key,
                        expected_body_sha256=body_digest,
                        expected_event_digest=event_digest(value),
                        generation_id="replay-v2",
                        invocation_id=f"{mode}-raw",
                    )
                state = runtime.store.recovery_export()
                self.assertEqual(state["failure_destination"][0]["status"], "UNRESOLVED")

    def test_partial_batch_stops_at_first_middle_and_last_failure(self) -> None:
        for failed_sequence in ("1", "2", "3"):
            with self.subTest(sequence=failed_sequence), tempfile.TemporaryDirectory() as directory:
                base = create_local_runtime(Path(directory))
                delegate = base.store

                @dataclass
                class FailingStore:
                    delegate: Any
                    failed_sequence: str

                    def isolate_rejected(
                        self, rejected: RejectedEvent, raw_key: str
                    ) -> ApplyResult:
                        return self.delegate.isolate_rejected(rejected, raw_key)

                    def apply_event(
                        self, admitted: AdmittedEvent, raw_key: str, generation_id: str
                    ) -> ApplyResult:
                        if admitted.coordinate.sequence_number == self.failed_sequence:
                            raise RetryableDependencyError("deterministic transient")
                        return self.delegate.apply_event(admitted, raw_key, generation_id)

                    def drain_closures(
                        self, shard_id: str, generation_id: str, limit: int
                    ) -> bool:
                        return self.delegate.drain_closures(shard_id, generation_id, limit)

                runtime = LocalRuntime(
                    base.archive,
                    FailingStore(delegate, failed_sequence),  # type: ignore[arg-type]
                    base.metrics,
                    base.logger,
                )
                response = create_handler(runtime)(
                    batch(
                        record(event("one", 1_000), "1"),
                        record(event("two", 2_000), "2"),
                        record(event("three", 3_000), "3"),
                    ),
                    None,
                )
                self.assertEqual(
                    response, {"batchItemFailures": [{"itemIdentifier": failed_sequence}]}
                )
                applied = {row["event_id"] for row in delegate.recovery_export()["identity_ledger"]}
                expected = {"one", "two", "three"} & {
                    event_id
                    for sequence, event_id in (("1", "one"), ("2", "two"), ("3", "three"))
                    if int(sequence) < int(failed_sequence)
                }
                self.assertEqual(applied, expected)


if __name__ == "__main__":
    unittest.main()
