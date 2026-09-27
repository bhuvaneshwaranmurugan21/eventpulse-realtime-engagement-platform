from __future__ import annotations

import base64
import json
import sys
import unittest
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from part2_stage1_helpers import event, record  # noqa: E402

from eventpulse.admission import admit  # noqa: E402
from eventpulse.canonical import (  # noqa: E402
    canonical_bytes,
    event_digest,
    rejected_raw_key,
    session_id,
    transaction_token,
)
from eventpulse.models import AdmittedEvent, RejectedEvent  # noqa: E402
from eventpulse.semantics import (  # noqa: E402
    classify_event_time,
    components,
    identity_disposition,
    is_closed,
)
from eventpulse.transport import decode_json, parse_source  # noqa: E402


class KernelTests(unittest.TestCase):
    def test_canonical_digest_matches_part1_oracle_golden(self) -> None:
        fixture = json.loads((ROOT / "fixtures/part1/stage3/identity.json").read_text())
        value = fixture["digest_cases"][0]
        self.assertEqual(event_digest(value["event_a"]), event_digest(value["event_b"]))
        self.assertNotIn(b" ", canonical_bytes(value["event_a"]))

    def test_session_id_matches_part1_oracle_golden(self) -> None:
        value = json.loads((ROOT / "fixtures/part1/stage3/sessions.json").read_text())[
            "session_id_case"
        ]
        self.assertEqual(
            session_id(
                value["contract_version"],
                value["generation_id"],
                value["user_id"],
                value["member_event_ids"],
            ),
            value["expected_session_id"],
        )

    def test_decoder_rejects_transport_edges_and_preserves_bytes(self) -> None:
        normal = record(event("e1", 1_000), "1")
        transport = parse_source(normal)
        self.assertIsInstance(decode_json(transport), dict)

        duplicate = record('{"x":1,"x":2}', "2")
        result = decode_json(parse_source(duplicate))
        self.assertIsInstance(result, RejectedEvent)
        self.assertEqual(result.disposition, "DUPLICATE_JSON_KEY")
        self.assertEqual(result.archive_body, b'{"x":1,"x":2}')

        invalid_utf8 = decode_json(parse_source(record(b"\xff", "3")))
        self.assertEqual(invalid_utf8.disposition, "INVALID_UTF8")
        self.assertEqual(invalid_utf8.archive_body, b"\xff")

        corrupt = deepcopy(normal)
        corrupt["kinesis"]["data"] = "not base64***"
        corrupt_result = decode_json(parse_source(corrupt))
        self.assertEqual(corrupt_result.disposition, "CORRUPT_BASE64")
        self.assertEqual(corrupt_result.archive_body, b"not base64***")

    def test_admission_precedence_and_boolean_integer_rejection(self) -> None:
        privacy = event("p1", 1_000)
        privacy["payload"] = {"email": "private@example.invalid", "unknown": 1}
        result = admit(parse_source(record(privacy, "1")))
        self.assertEqual(result.disposition, "PRIVACY_VIOLATION")

        boolean_time = event("p2", 1_000)
        boolean_time["event_time_ms"] = True
        result = admit(parse_source(record(boolean_time, "2")))
        self.assertEqual(result.disposition, "INVALID_SCHEMA")

        floating = json.dumps(event("p3", 1_000)).replace("1000", "1000.5", 1)
        result = admit(parse_source(record(floating, "3")))
        self.assertEqual(result.disposition, "INVALID_SCHEMA")
        self.assertEqual(result.archive_body, floating.encode())

    def test_partition_and_clock_boundaries(self) -> None:
        mismatch = event("m1", 1_000)
        result = admit(parse_source(record(mismatch, "1", partition_key="another-user")))
        self.assertEqual(result.disposition, "PARTITION_MISMATCH")

        future_ok = event("f1", 61_000, ingest_time_ms=1_000)
        self.assertIsInstance(admit(parse_source(record(future_ok, "2"))), AdmittedEvent)
        future_bad = event("f2", 61_001, ingest_time_ms=1_000)
        self.assertEqual(
            admit(parse_source(record(future_bad, "3"))).disposition,
            "FUTURE_CLOCK",
        )

    def test_identity_time_session_and_closure_boundaries(self) -> None:
        self.assertEqual(
            identity_disposition(
                existing_digest="a", incoming_digest="a", first_ingest_ms=0, ingest_ms=604_800_000
            ),
            "IDENTICAL_DUPLICATE",
        )
        self.assertEqual(
            identity_disposition(
                existing_digest="a", incoming_digest="a", first_ingest_ms=0, ingest_ms=604_800_001
            ),
            "EXPIRED_IDENTITY",
        )
        self.assertEqual(classify_event_time(8_200_000, 10_000_000).category, "accepted_late")
        self.assertEqual(classify_event_time(8_199_999, 10_000_000).category, "beyond_watermark")
        self.assertEqual(components([("a", 0), ("b", 1_800_000)]), [[("a", 0), ("b", 1_800_000)]])
        self.assertEqual(len(components([("a", 0), ("b", 1_800_001)])), 2)
        self.assertFalse(is_closed(watermark_ms=2_800_000, session_end_ms=1_000_000))
        self.assertTrue(is_closed(watermark_ms=2_800_001, session_end_ms=1_000_000))

    def test_malformed_keys_and_tokens_are_stable_and_bounded(self) -> None:
        kwargs = {
            "event_source_arn": "arn:test",
            "shard_id": "shard-1",
            "sequence_number": "7",
            "transport_text": base64.b64encode(b"bad").decode(),
        }
        self.assertEqual(rejected_raw_key(**kwargs), rejected_raw_key(**kwargs))
        self.assertNotEqual(
            rejected_raw_key(**kwargs), rejected_raw_key(**{**kwargs, "sequence_number": "8"})
        )
        self.assertEqual(len(transaction_token("live-v1", "e1")), 36)


if __name__ == "__main__":
    unittest.main()
