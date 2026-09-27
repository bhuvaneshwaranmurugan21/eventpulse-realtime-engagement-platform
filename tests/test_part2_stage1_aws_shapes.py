from __future__ import annotations

import json
import os
import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from part2_stage1_helpers import event, record  # noqa: E402

from eventpulse.admission import admit  # noqa: E402
from eventpulse.aws import (  # noqa: E402
    AWSApplicationStore,
    CloudWatchMetricSink,
    DynamoRequestBuilder,
    JSONLogger,
    S3RawArchive,
    _item,
    create_aws_runtime,
)
from eventpulse.canonical import canonical_bytes, event_digest, sha256_bytes  # noqa: E402
from eventpulse.errors import InvariantViolation, RetryableDependencyError  # noqa: E402
from eventpulse.models import AdmittedEvent, ArchiveObject  # noqa: E402
from eventpulse.transport import parse_source  # noqa: E402


class RecordingClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def put_object(self, **kwargs: object) -> None:
        self.calls.append(("put_object", kwargs))


class FakeDynamo:
    def __init__(self, get_items: list[dict[str, object]] | None = None) -> None:
        self.get_items = list(get_items or [])
        self.query_items: list[dict[str, object]] = []
        self.calls: list[tuple[str, dict[str, object]]] = []

    def get_item(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(("get_item", kwargs))
        return self.get_items.pop(0) if self.get_items else {}

    def query(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(("query", kwargs))
        return {"Items": self.query_items}

    def transact_write_items(self, **kwargs: object) -> None:
        self.calls.append(("transact_write_items", kwargs))


class AWSShapeTests(unittest.TestCase):
    def test_s3_conditional_create_shape(self) -> None:
        client = RecordingClient()
        adapter = S3RawArchive(client, "eventpulse-private-raw")
        body = b"{}"
        adapter.put_if_absent(
            ArchiveObject("raw/x.json", body, sha256_bytes(body), {"event-digest": "d"})
        )
        name, request = client.calls[0]
        self.assertEqual(name, "put_object")
        self.assertEqual(request["IfNoneMatch"], "*")
        self.assertEqual(request["ServerSideEncryption"], "aws:kms")
        self.assertEqual(request["Metadata"]["sha256"], sha256_bytes(body))

    def test_s3_existing_digest_and_error_mapping(self) -> None:
        body = b"body"
        digest = sha256_bytes(body)

        class ExistingClient:
            def __init__(self, actual: str, status: int = 412) -> None:
                self.actual = actual
                self.status = status

            def put_object(self, **kwargs: object) -> None:
                del kwargs
                raise ClientError(
                    {
                        "Error": {"Code": str(self.status)},
                        "ResponseMetadata": {"HTTPStatusCode": self.status},
                    },
                    "PutObject",
                )

            def head_object(self, **kwargs: object) -> dict[str, object]:
                del kwargs
                return {"Metadata": {"sha256": self.actual}}

            def get_object(self, **kwargs: object) -> dict[str, object]:
                del kwargs

                class Body:
                    def read(self) -> bytes:
                        return body

                return {"Body": Body()}

        obj = ArchiveObject("raw/x.json", body, digest, {})
        existing = S3RawArchive(ExistingClient(digest), "bucket")
        existing.put_if_absent(obj)
        self.assertEqual(existing.read("raw/x.json"), body)
        with self.assertRaises(InvariantViolation):
            S3RawArchive(ExistingClient("different"), "bucket").put_if_absent(obj)
        with self.assertRaises(RetryableDependencyError):
            S3RawArchive(ExistingClient(digest, 409), "bucket").put_if_absent(obj)

    def test_dynamo_accepted_transaction_is_bounded_and_conditional(self) -> None:
        value = event("aws-shape", 10_000_000)
        admitted = admit(parse_source(record(value, "1")))
        self.assertIsInstance(admitted, AdmittedEvent)
        builder = DynamoRequestBuilder("eventpulse-state")
        request = builder.accepted_transaction(
            admitted=admitted,
            generation_id="live-v1",
            maximum_after_ms=10_000_000,
            watermark_after_ms=8_200_000,
            expected_shard_version=None,
            replaced_components=[],
            component={
                "component_id": "a" * 64,
                "start_ms": 10_000_000,
                "end_ms": 10_000_000,
            },
        )
        self.assertLessEqual(len(request["TransactItems"]), 9)
        self.assertEqual(len(request["ClientRequestToken"]), 36)
        self.assertLess(len(canonical_bytes(request)), 4 * 1024 * 1024)
        expressions = json.dumps(request, sort_keys=True)
        self.assertIn("attribute_not_exists", expressions)
        self.assertIn("expiry_ms", expressions)
        self.assertIn("gsi1pk", expressions)

    def test_quarantine_and_outbox_ids_are_stable(self) -> None:
        builder = DynamoRequestBuilder("eventpulse-state")
        kwargs = {
            "disposition": "INVALID_JSON",
            "raw_key": "rejected/key.bin",
            "source_hash": "a" * 64,
            "sequence": "7",
            "payload_digest": event_digest(event("id", 1_000)),
        }
        first = builder.quarantine_transaction(**kwargs)
        second = builder.quarantine_transaction(**kwargs)
        self.assertEqual(first, second)
        self.assertEqual(len(first["TransactItems"]), 2)

    def test_dynamo_store_new_duplicate_conflict_and_late(self) -> None:
        value = event("aws-event", 10_000_000)
        admitted = admit(parse_source(record(value, "1")))
        self.assertIsInstance(admitted, AdmittedEvent)

        client = FakeDynamo([{}, {}])
        store = AWSApplicationStore(client, "table")
        result = store.apply_event(admitted, "raw/key", "live-v1")
        self.assertEqual(result.disposition, "on_time")
        self.assertTrue(result.mutated_live_state)
        self.assertEqual(client.calls[-1][0], "transact_write_items")

        identity = {
            "Item": _item(
                {
                    "pk": "x",
                    "sk": "IDENTITY",
                    "digest": admitted.digest,
                    "first_ingest_ms": 10_000_000,
                }
            )
        }
        duplicate = AWSApplicationStore(FakeDynamo([identity, {}]), "table")
        self.assertEqual(
            duplicate.apply_event(admitted, "raw/key", "live-v1").disposition,
            "IDENTICAL_DUPLICATE",
        )

        conflict_identity = {
            "Item": _item(
                {
                    "pk": "x",
                    "sk": "IDENTITY",
                    "digest": "other",
                    "first_ingest_ms": 10_000_000,
                }
            )
        }
        conflict_client = FakeDynamo([conflict_identity, {}])
        conflict = AWSApplicationStore(conflict_client, "table")
        self.assertEqual(
            conflict.apply_event(admitted, "raw/key", "live-v1").disposition,
            "IDENTITY_CONFLICT",
        )
        self.assertEqual(conflict_client.calls[-1][0], "transact_write_items")

        late_event = event("too-late", 8_199_999, ingest_time_ms=8_199_999)
        late = admit(parse_source(record(late_event, "2")))
        shard = {
            "Item": _item(
                {
                    "pk": "s",
                    "sk": "STATE",
                    "max_event_time_ms": 10_000_000,
                    "version": 1,
                }
            )
        }
        late_client = FakeDynamo([{}, shard])
        late_store = AWSApplicationStore(late_client, "table")
        self.assertEqual(
            late_store.apply_event(late, "raw/late", "live-v1").disposition,
            "LATE_BEYOND_WATERMARK",
        )

    def test_dynamo_existing_state_bridge_and_closure_query(self) -> None:
        value = event("bridge", 10_930_000)
        admitted = admit(parse_source(record(value, "3")))
        shard = {
            "Item": _item(
                {
                    "pk": "s",
                    "sk": "STATE",
                    "max_event_time_ms": 11_860_000,
                    "version": 4,
                }
            )
        }
        client = FakeDynamo([{}, shard])
        client.query_items = [
            _item(
                {
                    "pk": "u",
                    "sk": "COMP#left",
                    "component_id": "left",
                    "start_ms": 10_000_000,
                    "end_ms": 10_000_000,
                    "version": 1,
                }
            ),
            _item(
                {
                    "pk": "u",
                    "sk": "COMP#right",
                    "component_id": "right",
                    "start_ms": 11_860_000,
                    "end_ms": 11_860_000,
                    "version": 2,
                }
            ),
        ]
        store = AWSApplicationStore(client, "table")
        self.assertEqual(
            store.apply_event(admitted, "raw/key", "live-v1").disposition,
            "accepted_late",
        )
        request = client.calls[-1][1]
        self.assertLessEqual(len(request["TransactItems"]), 9)

        empty = FakeDynamo([shard])
        self.assertFalse(AWSApplicationStore(empty, "table").drain_closures("shard", "live-v1", 20))
        due = FakeDynamo([shard])
        due.query_items = [_item({"pk": "u", "sk": "COMP#due"})]
        with self.assertRaises(RetryableDependencyError):
            AWSApplicationStore(due, "table").drain_closures("shard", "live-v1", 20)
        with self.assertRaises(InvariantViolation):
            store.drain_closures("shard", "live-v1", 21)

    def test_metric_logger_and_lazy_runtime_composition(self) -> None:
        client = RecordingClient()

        def metric_call(**kwargs: object) -> None:
            client.calls.append(("put_metric_data", kwargs))

        client.put_metric_data = metric_call  # type: ignore[attr-defined]
        CloudWatchMetricSink(client).increment("Count", dimensions={"b": "2", "a": "1"})
        metric_data = client.calls[0][1]["MetricData"]
        self.assertEqual(metric_data[0]["Dimensions"][0]["Name"], "a")
        stream = StringIO()
        with redirect_stdout(stream):
            JSONLogger().emit({"safe": "value"})
        self.assertEqual(stream.getvalue(), '{"safe":"value"}\n')

        clients: dict[str, RecordingClient] = {}

        def client_factory(name: str, *, region_name: str) -> RecordingClient:
            self.assertEqual(region_name, "ap-south-2")
            clients[name] = RecordingClient()
            return clients[name]

        environment = {
            "AWS_REGION": "ap-south-2",
            "EVENTPULSE_RAW_BUCKET": "raw",
            "EVENTPULSE_STATE_TABLE": "state",
            "EVENTPULSE_GENERATION_ID": "test-generation",
        }
        with patch.dict(os.environ, environment, clear=True), patch("boto3.client", client_factory):
            runtime = create_aws_runtime()
        self.assertEqual(runtime.generation_id, "test-generation")
        self.assertEqual(set(clients), {"s3", "dynamodb", "cloudwatch"})

        with patch.dict(os.environ, {"AWS_REGION": "ap-south-1"}, clear=True):
            with self.assertRaises(InvariantViolation):
                create_aws_runtime()


if __name__ == "__main__":
    unittest.main()
