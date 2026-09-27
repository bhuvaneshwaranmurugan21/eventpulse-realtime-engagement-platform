"""AWS adapters and exact request construction.

No client is created and no request is made at module import. Stage 1 verifies
these request shapes statically; managed behavior remains unclaimed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from boto3.dynamodb.types import TypeDeserializer, TypeSerializer
from botocore.exceptions import BotoCoreError, ClientError

from eventpulse.canonical import (
    canonical_bytes,
    sha256_bytes,
    stable_id,
    transaction_token,
)
from eventpulse.errors import InvariantViolation, RetryableDependencyError
from eventpulse.local import LambdaBatchResponder
from eventpulse.models import AdmittedEvent, ApplyResult, ArchiveObject, RejectedEvent
from eventpulse.semantics import (
    IDENTITY_TTL_MS,
    INACTIVITY_GAP_MS,
    classify_event_time,
    identity_disposition,
)

_SERIALIZER = TypeSerializer()
_DESERIALIZER = TypeDeserializer()


def _item(value: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {key: _SERIALIZER.serialize(child) for key, child in value.items()}


def _plain(value: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {key: _DESERIALIZER.deserialize(child) for key, child in value.items()}


def _dependency_error(error: Exception) -> RetryableDependencyError:
    return RetryableDependencyError(f"AWS dependency failure: {type(error).__name__}")


class S3RawArchive:
    def __init__(self, client: Any, bucket: str) -> None:
        self.client = client
        self.bucket = bucket

    def put_if_absent(self, obj: ArchiveObject) -> None:
        metadata = {**obj.metadata, "sha256": obj.sha256}
        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=obj.key,
                Body=obj.body,
                ContentType="application/json"
                if obj.key.endswith(".json")
                else "application/octet-stream",
                IfNoneMatch="*",
                Metadata=metadata,
                ServerSideEncryption="aws:kms",
            )
            return
        except ClientError as error:
            status = int(error.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0))
            code = str(error.response.get("Error", {}).get("Code", ""))
            if status == 412 or code in {"PreconditionFailed", "412"}:
                try:
                    existing = self.client.head_object(Bucket=self.bucket, Key=obj.key)
                except (BotoCoreError, ClientError) as head_error:
                    raise _dependency_error(head_error) from head_error
                actual = str(existing.get("Metadata", {}).get("sha256", ""))
                if actual != obj.sha256:
                    raise InvariantViolation("existing S3 raw object digest differs") from error
                return
            if status == 409 or code in {"ConditionalRequestConflict", "409"}:
                raise RetryableDependencyError("S3 conditional-create conflict") from error
            raise _dependency_error(error) from error
        except BotoCoreError as error:
            raise _dependency_error(error) from error

    def read(self, key: str) -> bytes:
        try:
            body = self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except (BotoCoreError, ClientError) as error:
            raise _dependency_error(error) from error
        if not isinstance(body, bytes):
            raise InvariantViolation("S3 body must be bytes")
        return body


class DynamoRequestBuilder:
    """Build bounded DynamoDB transactions without dispatching them."""

    def __init__(self, table_name: str) -> None:
        self.table_name = table_name

    @staticmethod
    def user_pk(generation_id: str, user_id: str) -> str:
        return f"GEN#{generation_id}#USER#{user_id}"

    @staticmethod
    def shard_pk(generation_id: str, shard_id: str) -> str:
        return f"GEN#{generation_id}#SHARD#{shard_id}"

    @staticmethod
    def identity_pk(generation_id: str, event_id: str) -> str:
        return f"GEN#{generation_id}#EVENT#{event_id}"

    def quarantine_transaction(
        self,
        *,
        disposition: str,
        raw_key: str,
        source_hash: str,
        sequence: str,
        payload_digest: str,
    ) -> dict[str, Any]:
        quarantine_id = stable_id("quarantine", disposition, source_hash, sequence, payload_digest)
        outbox_id = stable_id("outbox", quarantine_id)
        return self._bounded(
            [
                {
                    "Put": {
                        "TableName": self.table_name,
                        "Item": _item(
                            {
                                "pk": f"QUARANTINE#{quarantine_id}",
                                "sk": "AUTHORITY",
                                "disposition": disposition,
                                "raw_key": raw_key,
                                "source_hash": source_hash,
                                "sequence_number": sequence,
                                "payload_digest": payload_digest,
                            }
                        ),
                        "ConditionExpression": "attribute_not_exists(pk)",
                    }
                },
                {
                    "Put": {
                        "TableName": self.table_name,
                        "Item": _item(
                            {
                                "pk": f"OUTBOX#{outbox_id}",
                                "sk": "PENDING",
                                "outbox_id": outbox_id,
                                "quarantine_id": quarantine_id,
                                "disposition": disposition,
                            }
                        ),
                        "ConditionExpression": "attribute_not_exists(pk)",
                    }
                },
            ],
            transaction_token("quarantine", quarantine_id),
        )

    def accepted_transaction(
        self,
        *,
        admitted: AdmittedEvent,
        generation_id: str,
        maximum_after_ms: int,
        watermark_after_ms: int,
        expected_shard_version: int | None,
        replaced_components: list[dict[str, Any]],
        component: dict[str, Any],
    ) -> dict[str, Any]:
        event = admitted.event
        shard_pk = self.shard_pk(generation_id, admitted.coordinate.shard_id)
        user_pk = self.user_pk(generation_id, str(event["user_id"]))
        event_sk = f"EVENT#{int(event['event_time_ms']):020d}#{event['event_id']}"
        work_id = stable_id(
            "closure-work", admitted.coordinate.shard_id, generation_id, watermark_after_ms
        )
        writes: list[dict[str, Any]] = [
            {
                "Put": {
                    "TableName": self.table_name,
                    "Item": _item(
                        {
                            "pk": self.identity_pk(generation_id, str(event["event_id"])),
                            "sk": "IDENTITY",
                            "digest": admitted.digest,
                            "first_ingest_ms": int(event["ingest_time_ms"]),
                            "expiry_ms": int(event["ingest_time_ms"]) + IDENTITY_TTL_MS,
                            "generation_id": generation_id,
                        }
                    ),
                    "ConditionExpression": "attribute_not_exists(pk)",
                }
            },
            {
                "Put": {
                    "TableName": self.table_name,
                    "Item": _item(
                        {
                            "pk": user_pk,
                            "sk": event_sk,
                            "event_id": str(event["event_id"]),
                            "event_time_ms": int(event["event_time_ms"]),
                            "event_type": str(event["event_type"]),
                            "value_cents": int(event["payload"].get("value_cents", 0)),
                            "digest": admitted.digest,
                        }
                    ),
                    "ConditionExpression": "attribute_not_exists(pk)",
                }
            },
        ]
        if expected_shard_version is None:
            writes.append(
                {
                    "Put": {
                        "TableName": self.table_name,
                        "Item": _item(
                            {
                                "pk": shard_pk,
                                "sk": "STATE",
                                "max_event_time_ms": maximum_after_ms,
                                "version": 1,
                            }
                        ),
                        "ConditionExpression": "attribute_not_exists(pk)",
                    }
                }
            )
        else:
            writes.append(
                {
                    "Update": {
                        "TableName": self.table_name,
                        "Key": _item({"pk": shard_pk, "sk": "STATE"}),
                        "UpdateExpression": "SET max_event_time_ms=:maximum, version=:next",
                        "ConditionExpression": "version=:expected",
                        "ExpressionAttributeValues": _item(
                            {
                                ":maximum": maximum_after_ms,
                                ":next": expected_shard_version + 1,
                                ":expected": expected_shard_version,
                            }
                        ),
                    }
                }
            )
        for previous in replaced_components:
            writes.append(
                {
                    "Delete": {
                        "TableName": self.table_name,
                        "Key": _item({"pk": user_pk, "sk": previous["sk"]}),
                        "ConditionExpression": "version=:version",
                        "ExpressionAttributeValues": _item({":version": int(previous["version"])}),
                    }
                }
            )
        component_id = str(component["component_id"])
        close_after = int(component["end_ms"]) + INACTIVITY_GAP_MS
        writes.extend(
            [
                {
                    "Put": {
                        "TableName": self.table_name,
                        "Item": _item(
                            {
                                "pk": user_pk,
                                "sk": f"COMP#{int(component['start_ms']):020d}#{component_id}",
                                "component_id": component_id,
                                "start_ms": int(component["start_ms"]),
                                "end_ms": int(component["end_ms"]),
                                "version": 1,
                                "gsi1pk": shard_pk,
                                "gsi1sk": f"CLOSE#{close_after:020d}#{component_id}",
                            }
                        ),
                        "ConditionExpression": "attribute_not_exists(pk)",
                    }
                },
                {
                    "Put": {
                        "TableName": self.table_name,
                        "Item": _item(
                            {
                                "pk": shard_pk,
                                "sk": f"WORK#{watermark_after_ms:020d}#{work_id}",
                                "work_id": work_id,
                                "watermark_ms": watermark_after_ms,
                                "status": "PENDING",
                            }
                        ),
                        "ConditionExpression": "attribute_not_exists(pk)",
                    }
                },
                {
                    "Update": {
                        "TableName": self.table_name,
                        "Key": _item({"pk": user_pk, "sk": "AGGREGATE"}),
                        "UpdateExpression": (
                            "ADD views :views, clicks :clicks, purchases :purchases, "
                            "value_cents :value"
                        ),
                        "ExpressionAttributeValues": _item(
                            {
                                ":views": 1 if event["event_type"] == "view" else 0,
                                ":clicks": 1 if event["event_type"] == "click" else 0,
                                ":purchases": 1 if event["event_type"] == "purchase" else 0,
                                ":value": int(event["payload"].get("value_cents", 0)),
                            }
                        ),
                    }
                },
            ]
        )
        return self._bounded(
            writes,
            transaction_token("apply", generation_id, str(event["event_id"])),
        )

    def _bounded(self, writes: list[dict[str, Any]], token: str) -> dict[str, Any]:
        if len(writes) > 100:
            raise InvariantViolation("DynamoDB transaction exceeds 100 items")
        request = {"TransactItems": writes, "ClientRequestToken": token}
        if len(canonical_bytes(request)) >= 4 * 1024 * 1024:
            raise InvariantViolation("DynamoDB transaction exceeds 4 MiB")
        return request


class AWSApplicationStore:
    """DynamoDB adapter for ordinary paths; crash proof is deferred to Stage 2."""

    def __init__(self, client: Any, table_name: str) -> None:
        self.client = client
        self.builder = DynamoRequestBuilder(table_name)
        self.table_name = table_name

    def _dispatch(self, request: dict[str, Any]) -> None:
        try:
            self.client.transact_write_items(**request)
        except (BotoCoreError, ClientError) as error:
            raise _dependency_error(error) from error

    def isolate_rejected(self, rejected: RejectedEvent, raw_key: str) -> ApplyResult:
        source_hash = sha256_bytes(rejected.coordinate.event_source_arn.encode("utf-8"))
        request = self.builder.quarantine_transaction(
            disposition=rejected.disposition,
            raw_key=raw_key,
            source_hash=source_hash,
            sequence=rejected.coordinate.sequence_number,
            payload_digest=sha256_bytes(rejected.archive_body),
        )
        self._dispatch(request)
        return ApplyResult(rejected.disposition, False)

    def apply_event(self, admitted: AdmittedEvent, raw_key: str, generation_id: str) -> ApplyResult:
        del raw_key
        event = admitted.event
        identity_key = _item(
            {
                "pk": self.builder.identity_pk(generation_id, str(event["event_id"])),
                "sk": "IDENTITY",
            }
        )
        shard_key = _item(
            {
                "pk": self.builder.shard_pk(generation_id, admitted.coordinate.shard_id),
                "sk": "STATE",
            }
        )
        try:
            identity_response = self.client.get_item(
                TableName=self.table_name, Key=identity_key, ConsistentRead=True
            )
            shard_response = self.client.get_item(
                TableName=self.table_name, Key=shard_key, ConsistentRead=True
            )
        except (BotoCoreError, ClientError) as error:
            raise _dependency_error(error) from error
        identity = _plain(identity_response["Item"]) if "Item" in identity_response else None
        disposition = identity_disposition(
            existing_digest=None if identity is None else str(identity["digest"]),
            incoming_digest=admitted.digest,
            first_ingest_ms=0 if identity is None else int(identity["first_ingest_ms"]),
            ingest_ms=int(event["ingest_time_ms"]),
        )
        if disposition != "NEW_IDENTITY":
            if disposition in {"IDENTITY_CONFLICT", "EXPIRED_IDENTITY"}:
                source_hash = sha256_bytes(admitted.coordinate.event_source_arn.encode("utf-8"))
                self._dispatch(
                    self.builder.quarantine_transaction(
                        disposition=disposition,
                        raw_key="archived",
                        source_hash=source_hash,
                        sequence=admitted.coordinate.sequence_number,
                        payload_digest=admitted.digest,
                    )
                )
            return ApplyResult(disposition, False)

        shard = _plain(shard_response["Item"]) if "Item" in shard_response else None
        previous_max = None if shard is None else int(shard["max_event_time_ms"])
        time = classify_event_time(int(event["event_time_ms"]), previous_max)
        if time.category == "beyond_watermark":
            source_hash = sha256_bytes(admitted.coordinate.event_source_arn.encode("utf-8"))
            self._dispatch(
                self.builder.quarantine_transaction(
                    disposition="LATE_BEYOND_WATERMARK",
                    raw_key="archived",
                    source_hash=source_hash,
                    sequence=admitted.coordinate.sequence_number,
                    payload_digest=admitted.digest,
                )
            )
            return ApplyResult(
                "LATE_BEYOND_WATERMARK", False, time.watermark_before_ms, time.watermark_after_ms
            )

        user_pk = self.builder.user_pk(generation_id, str(event["user_id"]))
        try:
            response = self.client.query(
                TableName=self.table_name,
                KeyConditionExpression="pk=:pk AND begins_with(sk,:prefix)",
                ExpressionAttributeValues=_item({":pk": user_pk, ":prefix": "COMP#"}),
                ConsistentRead=True,
            )
        except (BotoCoreError, ClientError) as error:
            raise _dependency_error(error) from error
        components = [_plain(value) for value in response.get("Items", [])]
        event_time = int(event["event_time_ms"])
        matching = [
            component
            for component in components
            if event_time <= int(component["end_ms"]) + INACTIVITY_GAP_MS
            and event_time >= int(component["start_ms"]) - INACTIVITY_GAP_MS
        ]
        if len(matching) > 2:
            raise InvariantViolation("an event cannot bridge more than two disjoint components")
        bounds = [event_time]
        for component in matching:
            bounds.extend([int(component["start_ms"]), int(component["end_ms"])])
        component_id = stable_id(
            "component",
            generation_id,
            str(event["user_id"]),
            min(bounds),
            max(bounds),
            str(event["event_id"]),
        )
        request = self.builder.accepted_transaction(
            admitted=admitted,
            generation_id=generation_id,
            maximum_after_ms=time.maximum_after_ms,
            watermark_after_ms=time.watermark_after_ms,
            expected_shard_version=None if shard is None else int(shard["version"]),
            replaced_components=matching,
            component={
                "component_id": component_id,
                "start_ms": min(bounds),
                "end_ms": max(bounds),
            },
        )
        self._dispatch(request)
        return ApplyResult(time.category, True, time.watermark_before_ms, time.watermark_after_ms)

    def drain_closures(self, shard_id: str, generation_id: str, limit: int) -> bool:
        if not 1 <= limit <= 20:
            raise InvariantViolation("closure page limit must be between 1 and 20")
        shard_pk = self.builder.shard_pk(generation_id, shard_id)
        try:
            state_response = self.client.get_item(
                TableName=self.table_name,
                Key=_item({"pk": shard_pk, "sk": "STATE"}),
                ConsistentRead=True,
            )
            if "Item" not in state_response:
                return False
            maximum = int(_plain(state_response["Item"])["max_event_time_ms"])
            watermark = maximum - 1_800_000
            response = self.client.query(
                TableName=self.table_name,
                IndexName="gsi1",
                KeyConditionExpression="gsi1pk=:pk AND gsi1sk<:upper",
                ExpressionAttributeValues=_item(
                    {":pk": shard_pk, ":upper": f"CLOSE#{watermark:020d}"}
                ),
                Limit=limit,
                ScanIndexForward=True,
            )
        except (BotoCoreError, ClientError) as error:
            raise _dependency_error(error) from error
        # Stage 1 constructs and bounds closure queries. Durable paged output
        # finalization is deliberately exercised only by the SQLite adapter;
        # managed interruption/restart proof is Stage 2.
        if response.get("Items"):
            raise RetryableDependencyError("AWS closure page requires Stage 2 recovery executor")
        return False


class CloudWatchMetricSink:
    def __init__(self, client: Any, namespace: str = "EventPulse") -> None:
        self.client = client
        self.namespace = namespace

    def increment(self, name: str, *, dimensions: dict[str, str] | None = None) -> None:
        metric = {"MetricName": name, "Value": 1.0, "Unit": "Count"}
        if dimensions:
            metric["Dimensions"] = [
                {"Name": key, "Value": value} for key, value in sorted(dimensions.items())
            ]
        try:
            self.client.put_metric_data(Namespace=self.namespace, MetricData=[metric])
        except (BotoCoreError, ClientError) as error:
            raise _dependency_error(error) from error


class JSONLogger:
    def emit(self, event: dict[str, str | int | bool | None]) -> None:
        print(canonical_bytes(event).decode("utf-8"))


@dataclass
class AWSRuntime:
    archive: S3RawArchive
    store: AWSApplicationStore
    metrics: CloudWatchMetricSink
    logger: JSONLogger = field(default_factory=JSONLogger)
    responder: LambdaBatchResponder = field(default_factory=LambdaBatchResponder)
    generation_id: str = "live-v1"


def create_aws_runtime() -> AWSRuntime:
    """Create clients lazily on first Lambda invocation."""
    import boto3

    region = os.environ.get("AWS_REGION", "")
    if region != "ap-south-2":
        raise InvariantViolation("EventPulse AWS runtime requires AWS_REGION=ap-south-2")
    bucket = os.environ["EVENTPULSE_RAW_BUCKET"]
    table = os.environ["EVENTPULSE_STATE_TABLE"]
    generation = os.environ.get("EVENTPULSE_GENERATION_ID", "live-v1")
    return AWSRuntime(
        archive=S3RawArchive(boto3.client("s3", region_name=region), bucket),
        store=AWSApplicationStore(boto3.client("dynamodb", region_name=region), table),
        metrics=CloudWatchMetricSink(boto3.client("cloudwatch", region_name=region)),
        generation_id=generation,
    )
