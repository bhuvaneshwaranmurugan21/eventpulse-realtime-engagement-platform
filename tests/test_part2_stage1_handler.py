from __future__ import annotations

import json
import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from part2_stage1_helpers import batch, event, record  # noqa: E402

from eventpulse.errors import RetryableDependencyError  # noqa: E402
from eventpulse.handler import create_handler  # noqa: E402
from eventpulse.local import LocalRuntime, create_local_runtime  # noqa: E402
from eventpulse.models import AdmittedEvent, ApplyResult, RejectedEvent  # noqa: E402


class HandlerIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.runtime = create_local_runtime(self.root)
        self.handler = create_handler(self.runtime)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_valid_duplicate_conflict_and_poison_are_durable(self) -> None:
        first = event("event-1", 10_000_000)
        response = self.handler(batch(record(first, "1")), None)
        self.assertEqual(response, {"batchItemFailures": []})

        # The exact retry has no second application effect.
        self.handler(batch(record(first, "2")), None)
        state = self.runtime.store.export()
        self.assertEqual(len(state["identity_ledger"]), 1)
        self.assertEqual(state["user_aggregate"][0]["views"], 1)

        conflict = event("event-1", 10_000_001)
        self.handler(batch(record(conflict, "3")), None)
        state = self.runtime.store.export()
        self.assertEqual(state["user_aggregate"][0]["views"], 1)
        self.assertEqual(state["quarantine"][-1]["disposition"], "IDENTITY_CONFLICT")

        poison = event("poison-1", 10_000_000)
        poison["payload"] = {"email": "never-log@example.invalid"}
        self.handler(batch(record(poison, "4")), None)
        state = self.runtime.store.export()
        dispositions = {row["disposition"] for row in state["quarantine"]}
        self.assertEqual(dispositions, {"IDENTITY_CONFLICT", "PRIVACY_VIOLATION"})
        self.assertEqual(len(state["outbox"]), 2)
        self.assertNotIn("never-log", json.dumps(self.runtime.logger.events))

        # Reopening the same SQLite file proves results are not process-memory state.
        resumed = create_local_runtime(self.root)
        self.assertEqual(resumed.store.export(), state)

    def test_accepted_late_bridge_and_cross_user_closure(self) -> None:
        events = [
            record(event("left", 10_000_000, user_id="user-a"), "1"),
            record(event("right", 11_860_000, user_id="user-a"), "2"),
            record(event("bridge", 10_930_000, user_id="user-a"), "3"),
        ]
        self.handler(batch(*events), None)
        state = self.runtime.store.export()
        self.assertEqual(len(state["session_component"]), 1)
        self.assertEqual(state["session_component"][0]["start_ms"], 10_000_000)
        self.assertEqual(state["session_component"][0]["end_ms"], 11_860_000)

        # Another user's event advances the same shard watermark and closes user-a.
        advance = event("advance", 15_460_001, user_id="user-b")
        self.handler(batch(record(advance, "4")), None)
        state = self.runtime.store.export()
        self.assertEqual(len(state["session_output"]), 1)
        self.assertEqual(state["session_output"][0]["member_count"], 3)
        self.assertEqual(
            json.loads(state["session_output"][0]["member_ids_json"]),
            ["bridge", "left", "right"],
        )

    def test_watermark_is_per_shard_and_beyond_late_does_not_mutate(self) -> None:
        shard_a = "shard-a"
        shard_b = "shard-b"
        values = [
            record(event("a1", 10_000_000), "1", shard=shard_a),
            record(event("b1", 20_000_000, user_id="user-b"), "1", shard=shard_b),
            record(event("a-late", 8_199_999), "2", shard=shard_a),
        ]
        self.handler(batch(*values), None)
        state = self.runtime.store.export()
        maxima = {row["shard_id"]: row["max_event_time_ms"] for row in state["shard_state"]}
        self.assertEqual(maxima, {shard_a: 10_000_000, shard_b: 20_000_000})
        self.assertIn("LATE_BEYOND_WATERMARK", [row["disposition"] for row in state["quarantine"]])
        self.assertNotIn("a-late", [row["event_id"] for row in state["open_event"]])

    def test_malformed_retry_uses_one_raw_object_and_one_authority(self) -> None:
        value = record(b"\xff", "91")
        self.handler(batch(value), None)
        self.handler(batch(value), None)
        raw = [path for path in (self.root / "archive").rglob("*") if path.is_file()]
        state = self.runtime.store.export()
        self.assertEqual(len(raw), 1)
        self.assertEqual(len(state["quarantine"]), 1)
        self.assertEqual(len(state["outbox"]), 1)

    def test_transient_failure_stops_shard_but_not_other_shard(self) -> None:
        delegate = self.runtime.store

        @dataclass
        class FaultStore:
            delegate: object

            def isolate_rejected(self, rejected: RejectedEvent, raw_key: str) -> ApplyResult:
                return delegate.isolate_rejected(rejected, raw_key)

            def apply_event(
                self, admitted: AdmittedEvent, raw_key: str, generation_id: str
            ) -> ApplyResult:
                if admitted.event["event_id"] == "fail":
                    raise RetryableDependencyError("injected transient")
                return delegate.apply_event(admitted, raw_key, generation_id)

            def drain_closures(self, shard_id: str, generation_id: str, limit: int) -> bool:
                return delegate.drain_closures(shard_id, generation_id, limit)

        runtime = LocalRuntime(
            archive=self.runtime.archive,
            store=FaultStore(delegate),  # type: ignore[arg-type]
            metrics=self.runtime.metrics,
            logger=self.runtime.logger,
        )
        handler = create_handler(runtime)
        shard_a = "shard-a"
        shard_b = "shard-b"
        response = handler(
            batch(
                record(event("later", 2_000), "2", shard=shard_a),
                record(event("fail", 1_000), "1", shard=shard_a),
                record(event("other", 3_000, user_id="user-b"), "1", shard=shard_b),
            ),
            None,
        )
        self.assertEqual(response, {"batchItemFailures": [{"itemIdentifier": "1"}]})
        ids = [row["event_id"] for row in delegate.export()["identity_ledger"]]
        self.assertNotIn("later", ids)
        self.assertIn("other", ids)


if __name__ == "__main__":
    unittest.main()
